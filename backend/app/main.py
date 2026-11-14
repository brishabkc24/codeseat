"""CodeSeat server.

Teachers have accounts and keep their classes; students need only a class code
and a name. A small REST API signs teachers in and manages their classes. After
that everyone in a class holds one WebSocket. The first message on a socket is
a "hello" that says who is connecting: a teacher is known by the session cookie
the browser sends with the connection, a student by a secret id. Secrets never
travel in a URL.

Messages a student sends:   take_seat, leave_seat, source, run, check, hand, dismiss_hint
Messages the teacher sends: source, watch, free_seat, lower_hand, hint, set_steps, set_current_step
Messages the server sends:  welcome, seats, you, teacher_source, student_source, steps, check, error
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from .accounts import (
    MAX_TEACHER_NAME,
    SESSION_SECONDS,
    AccountError,
    LoginBrake,
    check_password,
    clean_email,
    clean_password,
    hash_password,
    new_session_token,
    session_key,
)
from .rooms import Classroom, ClassroomStore, RoomError, Student, clean_text
from .storage import EmailTaken, Storage, TeacherRecord

HELLO_TIMEOUT_SECONDS = 10
SAVE_EVERY_SECONDS = 2
PRESENCE_EVERY_SECONDS = 20  # how often teachers are told who has gone idle
SESSION_COOKIE = "codeseat_session"
DEFAULT_DATABASE = Path(__file__).resolve().parent.parent / "data" / "codeseat.db"

# WebSocket close codes. The frontend turns these into messages for the user.
CLOSE_BAD_HELLO = 4400
CLOSE_NOT_TEACHER = 4401
CLOSE_NO_CLASS = 4404
CLOSE_REPLACED = 4409

log = logging.getLogger("codeseat")


@dataclass(eq=False)
class Connection:
    ws: WebSocket
    student: Student | None = None  # None means this socket is the teacher
    watching: int | None = None  # teacher only: the seat whose code is streamed live

    @property
    def is_teacher(self) -> bool:
        return self.student is None

    async def send(self, message: dict) -> None:
        try:
            await self.ws.send_json(message)
        except Exception:
            # The socket is already closing; its own handler does the clean-up.
            pass


class Hub:
    """Which sockets are open in which classroom."""

    def __init__(self) -> None:
        self._rooms: dict[str, set[Connection]] = {}

    def add(self, code: str, conn: Connection) -> None:
        self._rooms.setdefault(code, set()).add(conn)

    def remove(self, code: str, conn: Connection) -> None:
        connections = self._rooms.get(code)
        if connections is None:
            return
        connections.discard(conn)
        if not connections:
            del self._rooms[code]

    def teachers(self, code: str) -> list[Connection]:
        return [c for c in self._rooms.get(code, ()) if c.is_teacher]

    def students(self, code: str) -> list[Connection]:
        return [c for c in self._rooms.get(code, ()) if not c.is_teacher]

    def everyone(self, code: str) -> list[Connection]:
        return list(self._rooms.get(code, ()))

    def codes_with_teachers(self) -> list[str]:
        return [code for code, connections in self._rooms.items() if any(c.is_teacher for c in connections)]

    def for_student(self, code: str, student: Student) -> Connection | None:
        for conn in self._rooms.get(code, ()):
            if conn.student is student:
                return conn
        return None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    tasks = [asyncio.create_task(keep_saving()), asyncio.create_task(keep_presence())]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        store.flush()


async def keep_saving() -> None:
    """Copies changed classrooms to storage every few seconds and drops idle ones."""
    while True:
        await asyncio.sleep(SAVE_EVERY_SECONDS)
        try:
            store.flush()
            store.unload_idle(keep=lambda room: bool(hub.everyone(room.code)))
        except Exception:
            log.exception("Saving classrooms failed; will try again")


async def keep_presence() -> None:
    """A student going idle is the passing of time, not a message, so nothing else reports it."""
    while True:
        await asyncio.sleep(PRESENCE_EVERY_SECONDS)
        try:
            await push_presence()
        except Exception:
            log.exception("Telling teachers who is idle failed; will try again")


async def push_presence() -> None:
    """Sends teachers a fresh seat list wherever the idle marks on their map have changed."""
    watched = hub.codes_with_teachers()
    for code in [code for code in presence_sent if code not in watched]:
        del presence_sent[code]
    for code in watched:
        room = store.loaded(code)
        if room is not None and room.idle_marks() != presence_sent.get(code):
            await broadcast_seats_to_teachers(room)


app = FastAPI(title="CodeSeat", lifespan=lifespan)
store = ClassroomStore(Storage(os.environ.get("CODESEAT_DATABASE", DEFAULT_DATABASE)))
hub = Hub()
brake = LoginBrake()
presence_sent: dict[str, tuple] = {}  # per class, the idle marks teachers were last told about


# ---------------------------------------------------------------- teachers


class SignUp(BaseModel):
    name: str
    email: str
    password: str


class LogIn(BaseModel):
    email: str
    password: str


def public(teacher: TeacherRecord) -> dict:
    return {"id": teacher.id, "name": teacher.name, "email": teacher.email}


def session_teacher(request: Request) -> TeacherRecord | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return store.storage.teacher_for_session(session_key(token), time.time())


def require_teacher(request: Request) -> TeacherRecord:
    teacher = session_teacher(request)
    if teacher is None:
        raise HTTPException(status_code=401, detail="Log in to do this.")
    return teacher


def start_session(teacher: TeacherRecord, request: Request, response: Response) -> None:
    token = new_session_token()
    now = time.time()
    store.storage.add_session(session_key(token), teacher.id, now, now + SESSION_SECONDS)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_SECONDS,
        path="/",
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )


@app.post("/api/teachers", status_code=201)
def sign_up(body: SignUp, request: Request, response: Response) -> dict:
    try:
        name = clean_text(body.name, MAX_TEACHER_NAME, "Your name")
        email = clean_email(body.email)
        password = clean_password(body.password)
    except (RoomError, AccountError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    teacher = TeacherRecord(
        id=secrets.token_urlsafe(12),
        name=name,
        email=email,
        password_hash=hash_password(password),
        created_at=time.time(),
    )
    try:
        store.storage.add_teacher(teacher)
    except EmailTaken as error:
        raise HTTPException(
            status_code=409, detail="An account with this email already exists. Log in instead."
        ) from error
    start_session(teacher, request, response)
    return {"teacher": public(teacher)}


# Checked when the email is unknown, so an unknown and a wrong password take the same time.
NOBODY_HASH = hash_password(secrets.token_urlsafe(16))


@app.post("/api/session")
def log_in(body: LogIn, request: Request, response: Response) -> dict:
    email = body.email.strip().lower()
    wait = brake.wait(email)
    if wait:
        minutes = max(1, -(-wait // 60))
        raise HTTPException(
            status_code=429,
            detail=f"Too many wrong passwords. Try again in {minutes} minute{'s' if minutes > 1 else ''}.",
        )
    teacher = store.storage.teacher_by_email(email)
    if not check_password(body.password, teacher.password_hash if teacher else NOBODY_HASH) or teacher is None:
        brake.failed(email)
        raise HTTPException(status_code=401, detail="Wrong email or password.")
    brake.succeeded(email)
    start_session(teacher, request, response)
    return {"teacher": public(teacher)}


@app.get("/api/session")
def who_am_i(request: Request) -> dict:
    """Who this browser is signed in as; null is an answer, not an error."""
    teacher = session_teacher(request)
    return {"teacher": public(teacher) if teacher else None}


@app.delete("/api/session", status_code=204)
def log_out(request: Request, response: Response) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        store.storage.delete_session(session_key(token))
    response.delete_cookie(SESSION_COOKIE, path="/")


# ---------------------------------------------------------------- classes


class NewClass(BaseModel):
    title: str
    rows: int
    cols: int


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/classes")
def my_classes(teacher: TeacherRecord = Depends(require_teacher)) -> dict:
    return {"classes": store.summaries_for(teacher.id)}


@app.post("/api/classes", status_code=201)
def create_class(body: NewClass, teacher: TeacherRecord = Depends(require_teacher)) -> dict:
    try:
        room = store.create(teacher.id, body.title, body.rows, body.cols)
    except RoomError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return room.info()


@app.get("/api/classes/{code}")
def get_class(code: str) -> dict:
    room = store.get(code)
    if room is None:
        raise HTTPException(status_code=404, detail="No class has that code. Check it with your teacher.")
    return {**room.info(), "seatsTaken": len(room.seats(for_teacher=False))}


@app.delete("/api/classes/{code}", status_code=204)
async def delete_class(code: str, teacher: TeacherRecord = Depends(require_teacher)) -> None:
    room = store.get(code)
    if room is None:
        raise HTTPException(status_code=404, detail="No class has that code.")
    if room.teacher_id != teacher.id:
        raise HTTPException(status_code=403, detail="This class belongs to another teacher.")
    store.delete(room.code)
    for conn in hub.everyone(room.code):
        await close_quietly(conn.ws, CLOSE_NO_CLASS, "The teacher has deleted this class.")


# ---------------------------------------------------------------- WebSocket


async def broadcast(connections: list[Connection], message: dict) -> None:
    if connections:
        await asyncio.gather(*(conn.send(message) for conn in connections))


async def broadcast_seats_to_teachers(room: Classroom) -> None:
    message = {"type": "seats", "seats": room.seats(for_teacher=True), "lobby": room.lobby()}
    presence_sent[room.code] = room.idle_marks()
    await broadcast(hub.teachers(room.code), message)


async def broadcast_seats(room: Classroom) -> None:
    await broadcast_seats_to_teachers(room)
    await broadcast(hub.students(room.code), {"type": "seats", "seats": room.seats(for_teacher=False)})


async def broadcast_lesson(room: Classroom) -> None:
    await broadcast(hub.everyone(room.code), {"type": "steps", **room.lesson()})


def welcome(room: Classroom, conn: Connection) -> dict:
    message = {
        "type": "welcome",
        "class": room.info(),
        "seats": room.seats(for_teacher=conn.is_teacher),
        "teacherSource": room.teacher_source,
        **room.lesson(),
    }
    student = conn.student
    if student is None:
        message["lobby"] = room.lobby()
    else:
        message["you"] = {
            "id": student.id,
            "name": student.name,
            "seat": student.seat,
            "source": student.source,
            "passed": room.passed_steps(student),
            "hand": student.hand is not None,
            "hint": student.hint,
        }
    return message


def seat_and_hand(student: Student) -> dict:
    """Tells a student where they sit and whether their hand is up; the two change together."""
    return {"type": "you", "seat": student.seat, "hand": student.hand is not None}


def stop_watching(room: Classroom, seat: int) -> None:
    """End teacher streams on a seat, so its next occupant is not watched unasked."""
    for conn in hub.teachers(room.code):
        if conn.watching == seat:
            conn.watching = None


def vacate(room: Classroom, student: Student) -> None:
    seat = room.leave_seat(student)
    if seat is not None:
        stop_watching(room, seat)


def as_seat(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


async def handle_student(room: Classroom, conn: Connection, message: dict) -> None:
    student = conn.student
    assert student is not None
    kind = message.get("type")

    if kind == "take_seat":
        previous = student.seat
        room.take_seat(student, message.get("seat"))  # a refusal raises and changes nothing
        if previous is not None and previous != student.seat:
            stop_watching(room, previous)
        await conn.send(seat_and_hand(student))
        await broadcast_seats(room)

    elif kind == "leave_seat":
        vacate(room, student)
        await conn.send(seat_and_hand(student))
        await broadcast_seats(room)

    elif kind == "source":
        back_from_idle = room.set_source(student, message.get("text"))
        if student.seat is not None:
            watchers = [c for c in hub.teachers(room.code) if c.watching == student.seat]
            await broadcast(
                watchers,
                {"type": "student_source", "seat": student.seat, "text": student.source},
            )
            if back_from_idle:
                await broadcast_seats_to_teachers(room)

    elif kind == "hand":
        room.set_hand(student, message.get("up"))
        await conn.send(seat_and_hand(student))
        await broadcast_seats_to_teachers(room)

    elif kind == "dismiss_hint":
        room.set_hint(student, "")
        await conn.send({"type": "you", "hint": student.hint})
        await broadcast_seats_to_teachers(room)

    elif kind == "run":
        room.record_run(student, message.get("status"))
        await broadcast_seats_to_teachers(room)

    elif kind == "check":
        step = room.step(message.get("step"))
        passed = room.check(student, step, message.get("status"), message.get("output"))
        await conn.send({"type": "check", "step": step.id, "passed": passed})
        await broadcast_seats_to_teachers(room)


async def handle_teacher(room: Classroom, conn: Connection, message: dict) -> None:
    kind = message.get("type")

    if kind == "source":
        room.set_teacher_source(message.get("text"))
        await broadcast(
            hub.students(room.code),
            {"type": "teacher_source", "text": room.teacher_source},
        )

    elif kind == "watch":
        conn.watching = None
        if message.get("seat") is None:
            return
        seat = as_seat(message.get("seat"))
        student = room.student_at(seat) if seat is not None else None
        if student is None:
            raise RoomError("Nobody is sitting in that seat.")
        conn.watching = seat
        await conn.send({"type": "student_source", "seat": seat, "text": student.source})

    elif kind == "free_seat":
        seat = as_seat(message.get("seat"))
        student = room.student_at(seat) if seat is not None else None
        if student is None:
            return
        vacate(room, student)
        target = hub.for_student(room.code, student)
        if target is not None:
            await target.send(seat_and_hand(student))
        await broadcast_seats(room)

    elif kind == "lower_hand":
        seat = as_seat(message.get("seat"))
        student = room.student_at(seat) if seat is not None else None
        if student is None or student.hand is None:
            return
        room.set_hand(student, False)
        target = hub.for_student(room.code, student)
        if target is not None:
            await target.send(seat_and_hand(student))
        await broadcast_seats_to_teachers(room)

    elif kind == "hint":
        seat = as_seat(message.get("seat"))
        student = room.student_at(seat) if seat is not None else None
        if student is None:
            raise RoomError("Nobody is sitting in that seat.")
        room.set_hint(student, message.get("text"))
        target = hub.for_student(room.code, student)
        if target is not None:
            await target.send({"type": "you", "hint": student.hint})
        await broadcast_seats_to_teachers(room)

    elif kind == "set_steps":
        room.set_steps(message.get("steps"))
        await broadcast_lesson(room)
        # A changed check takes its passes with it, so each student is told where they stand.
        for conn_ in hub.students(room.code):
            assert conn_.student is not None
            await conn_.send({"type": "you", "passed": room.passed_steps(conn_.student)})
        await broadcast_seats_to_teachers(room)

    elif kind == "set_current_step":
        room.set_current_step(message.get("step"))
        await broadcast_lesson(room)


async def receive(ws: WebSocket) -> dict | None:
    """The next message as a dict, or None if it was not a JSON object."""
    try:
        data = await ws.receive_json()
    except (ValueError, KeyError):
        return None
    return data if isinstance(data, dict) else None


async def close_quietly(ws: WebSocket, code: int, reason: str) -> None:
    try:
        await ws.close(code=code, reason=reason)
    except Exception:
        pass


@app.websocket("/ws/{code}")
async def classroom_socket(ws: WebSocket, code: str) -> None:
    await ws.accept()
    room = store.get(code)
    if room is None:
        await close_quietly(ws, CLOSE_NO_CLASS, "This class does not exist or has ended.")
        return

    try:
        hello = await asyncio.wait_for(receive(ws), HELLO_TIMEOUT_SECONDS)
    except (asyncio.TimeoutError, WebSocketDisconnect):
        hello = None
    if hello is None or hello.get("type") != "hello":
        await close_quietly(ws, CLOSE_BAD_HELLO, "Expected a hello message.")
        return

    replaced: Connection | None = None
    if hello.get("role") == "teacher":
        token = ws.cookies.get(SESSION_COOKIE)
        teacher = store.storage.teacher_for_session(session_key(token), time.time()) if token else None
        if teacher is None or teacher.id != room.teacher_id:
            await close_quietly(ws, CLOSE_NOT_TEACHER, "Only the teacher of this class can open its desk.")
            return
        conn = Connection(ws)
    elif hello.get("role") == "student":
        try:
            student = room.join(hello.get("studentId"), hello.get("name"))
        except RoomError as error:
            await close_quietly(ws, CLOSE_BAD_HELLO, str(error))
            return
        # One live socket per student: a second tab takes over from the first.
        replaced = hub.for_student(room.code, student)
        if replaced is not None:
            hub.remove(room.code, replaced)
        student.online = True
        conn = Connection(ws, student=student)
    else:
        await close_quietly(ws, CLOSE_BAD_HELLO, "Unknown role.")
        return

    room.touch()
    hub.add(room.code, conn)
    if replaced is not None:
        await close_quietly(replaced.ws, CLOSE_REPLACED, "This class was opened in another tab.")

    await conn.send(welcome(room, conn))
    if not conn.is_teacher:
        await broadcast_seats(room)

    try:
        while True:
            message = await receive(ws)
            if message is None:
                continue
            room.touch()
            try:
                if conn.is_teacher:
                    await handle_teacher(room, conn, message)
                else:
                    await handle_student(room, conn, message)
            except RoomError as error:
                await conn.send({"type": "error", "message": str(error)})
    except WebSocketDisconnect:
        pass
    finally:
        hub.remove(room.code, conn)
        student = conn.student
        if student is not None and hub.for_student(room.code, student) is None:
            student.online = False
            # Shielded so that cancelling this socket's task (a server shutting down, or the
            # test client right after a disconnect) still lets the teacher see the seat go dark.
            await asyncio.shield(broadcast_seats(room))
