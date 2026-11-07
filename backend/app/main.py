"""CodeSeat server.

A small REST API opens a class; after that everyone in the class holds one
WebSocket. The first message on a socket is a "hello" that says who is
connecting, so secrets never travel in a URL.

Messages a student sends:   take_seat, leave_seat, source, run, check
Messages the teacher sends: source, watch, free_seat, set_steps, set_current_step
Messages the server sends:  welcome, seats, you, teacher_source, student_source, steps, check, error
"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from .rooms import RUN_STATES, Classroom, ClassroomStore, RoomError, Student

HELLO_TIMEOUT_SECONDS = 10

# WebSocket close codes. The frontend turns these into messages for the user.
CLOSE_BAD_HELLO = 4400
CLOSE_NOT_TEACHER = 4401
CLOSE_NO_CLASS = 4404
CLOSE_REPLACED = 4409


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

    def for_student(self, code: str, student: Student) -> Connection | None:
        for conn in self._rooms.get(code, ()):
            if conn.student is student:
                return conn
        return None


app = FastAPI(title="CodeSeat")
store = ClassroomStore()
hub = Hub()


# ---------------------------------------------------------------- REST


class NewClass(BaseModel):
    title: str
    rows: int
    cols: int


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.post("/api/classes", status_code=201)
def create_class(body: NewClass) -> dict:
    try:
        room = store.create(body.title, body.rows, body.cols)
    except RoomError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {**room.info(), "teacherToken": room.teacher_token}


@app.get("/api/classes/{code}")
def get_class(code: str) -> dict:
    room = store.get(code)
    if room is None:
        raise HTTPException(status_code=404, detail="No class has that code. Check it with your teacher.")
    return {**room.info(), "seatsTaken": len(room.seats(for_teacher=False))}


# ---------------------------------------------------------------- WebSocket


async def broadcast(connections: list[Connection], message: dict) -> None:
    if connections:
        await asyncio.gather(*(conn.send(message) for conn in connections))


async def broadcast_seats_to_teachers(room: Classroom) -> None:
    message = {"type": "seats", "seats": room.seats(for_teacher=True), "lobby": room.lobby()}
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
        }
    return message


def stop_watching(room: Classroom, seat: int) -> None:
    """End teacher streams on a seat, so its next occupant is not watched unasked."""
    for conn in hub.teachers(room.code):
        if conn.watching == seat:
            conn.watching = None


def vacate(room: Classroom, student: Student) -> None:
    seat = student.seat
    if seat is None:
        return
    student.seat = None
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
        await conn.send({"type": "you", "seat": student.seat})
        await broadcast_seats(room)

    elif kind == "leave_seat":
        vacate(room, student)
        await conn.send({"type": "you", "seat": None})
        await broadcast_seats(room)

    elif kind == "source":
        room.set_source(student, message.get("text"))
        if student.seat is not None:
            watchers = [c for c in hub.teachers(room.code) if c.watching == student.seat]
            await broadcast(
                watchers,
                {"type": "student_source", "seat": student.seat, "text": student.source},
            )

    elif kind == "run":
        status = message.get("status")
        if status not in RUN_STATES:
            raise RoomError("Unknown run result.")
        student.last_run = status
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
            await target.send({"type": "you", "seat": None})
        await broadcast_seats(room)

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
        token = hello.get("token")
        if not isinstance(token, str) or not secrets.compare_digest(token, room.teacher_token):
            await close_quietly(ws, CLOSE_NOT_TEACHER, "This browser is not the teacher of this class.")
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
