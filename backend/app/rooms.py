"""In-memory classroom state for CodeSeat.

Nothing in this module knows about HTTP or WebSockets, so the classroom rules
(who may sit where, what each role is allowed to see) can be tested on their own.
A classroom belongs to a teacher and is copied to storage whenever it has
changed, so it outlives the server process; see storage.py.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field

from .storage import ClassRecord, Storage

# No 0/O or 1/I/L, so a code read aloud or off a projector is hard to mistype.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 6

MAX_ROWS = 8
MAX_COLS = 10
MAX_NAME = 30
MAX_TITLE = 60
MAX_SOURCE = 50_000
MAX_STEPS = 30
MAX_STEP_TITLE = 80
MAX_INSTRUCTIONS = 2_000
MAX_EXPECTED = 5_000
MAX_INPUT = 2_000
MAX_CHECK_OUTPUT = 20_000
MAX_HINT = 300
IDLE_SECONDS = 2 * 60 * 60  # a classroom nobody has touched for this long leaves memory
STUDENT_IDLE_SECONDS = 3 * 60  # a seated student who has not typed or run anything for this long shows as idle
STUCK_AFTER = 3  # failed tries in a row (crashes, or checks that did not pass) before a seat shows as stuck
RUN_STATES = ("ok", "error")


class RoomError(Exception):
    """A request the classroom rules do not allow. The message is shown to the user."""


def clean_text(value: object, limit: int, what: str) -> str:
    if not isinstance(value, str):
        raise RoomError(f"{what} is missing.")
    text = " ".join(value.split())
    if not text:
        raise RoomError(f"{what} is missing.")
    if len(text) > limit:
        raise RoomError(f"{what} is too long (at most {limit} characters).")
    return text


def clean_block(value: object, limit: int, what: str, required: bool = True) -> str:
    """Multi-line text, kept as typed apart from its line endings."""
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise RoomError(f"{what} must be text.")
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    if required and not text.strip():
        raise RoomError(f"{what} is missing.")
    if len(text) > limit:
        raise RoomError(f"{what} is too long (at most {limit:,} characters).")
    return text


def tidy_output(text: str) -> str:
    """Output as compared: spaces at the ends of lines and blank lines at the end do not count."""
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def outputs_match(expected: str, actual: str) -> bool:
    return tidy_output(expected) == tidy_output(actual)


@dataclass
class Step:
    """One task of the lesson. It passes when a program prints the expected output."""

    id: str
    title: str
    instructions: str = ""
    expected_output: str = ""
    input: str = ""  # lines handed to input(), one per line

    def info(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "instructions": self.instructions,
            "expectedOutput": self.expected_output,
            "input": self.input,
        }

    @classmethod
    def from_info(cls, info: dict) -> Step:
        return cls(
            id=info["id"],
            title=info["title"],
            instructions=info.get("instructions", ""),
            expected_output=info.get("expectedOutput", ""),
            input=info.get("input", ""),
        )

    def same_check(self, other: Step) -> bool:
        return self.expected_output == other.expected_output and self.input == other.input


@dataclass
class Student:
    id: str  # secret: only this student's browser knows it
    name: str
    seat: int | None = None
    source: str = ""
    online: bool = False
    last_run: str | None = None
    passed: set[str] = field(default_factory=set)  # ids of the steps this student has passed
    hand: int | None = None  # a ticket number while the hand is up; lower numbers went up first
    crashes: int = 0  # runs in a row that ended in an error
    misses: int = 0  # checks in a row that did not pass
    active_at: float = field(default_factory=time.time)  # when they last joined, typed, ran or clicked
    hint: str = ""  # the teacher's note on this student's screen; empty when there is none

    @property
    def stuck(self) -> bool:
        return self.crashes >= STUCK_AFTER or self.misses >= STUCK_AFTER


@dataclass
class Classroom:
    code: str
    title: str
    rows: int
    cols: int
    teacher_id: str
    teacher_source: str = ""
    created_at: float = field(default_factory=time.time)
    students: dict[str, Student] = field(default_factory=dict)
    steps: list[Step] = field(default_factory=list)
    current_step: str | None = None  # the step the teacher has pointed the class at
    last_active: float = field(default_factory=time.time)
    dirty: bool = False  # changed since it was last copied to storage
    next_hand: int = 1  # the ticket the next raised hand gets

    @property
    def seat_count(self) -> int:
        return self.rows * self.cols

    def info(self) -> dict:
        return {"code": self.code, "title": self.title, "rows": self.rows, "cols": self.cols}

    def lesson(self) -> dict:
        return {"steps": [step.info() for step in self.steps], "currentStep": self.current_step}

    def touch(self) -> None:
        self.last_active = time.time()

    def student_at(self, seat: int) -> Student | None:
        for student in self.students.values():
            if student.seat == seat:
                return student
        return None

    def join(self, student_id: object, name: object) -> Student:
        """Return the student for this browser, creating one on a first visit."""
        clean = clean_text(name, MAX_NAME, "Your name")
        student = self.students.get(student_id) if isinstance(student_id, str) else None
        if student is None:
            student = Student(id=secrets.token_urlsafe(16), name=clean)
            self.students[student.id] = student
            self.dirty = True
        else:
            self.active(student)  # coming back counts as doing something
            if student.name != clean:
                student.name = clean
                self.dirty = True
        return student

    def active(self, student: Student) -> bool:
        """Notes that the student just did something. True if they had been idle until now."""
        now = time.time()
        was_idle = now - student.active_at >= STUDENT_IDLE_SECONDS
        student.active_at = now
        return was_idle

    def idle_minutes(self, student: Student, now: float) -> int | None:
        """Whole minutes a seated, online student has done nothing, once that is long enough to count."""
        if not student.online or student.seat is None:
            return None
        quiet = now - student.active_at
        return int(quiet // 60) if quiet >= STUDENT_IDLE_SECONDS else None

    def idle_marks(self) -> tuple:
        """Who shows as idle, and for how many minutes. It changes only when the teacher's map would."""
        now = time.time()
        marks = ((student.seat, self.idle_minutes(student, now)) for student in self.students.values())
        return tuple(sorted(mark for mark in marks if mark[1] is not None))

    def take_seat(self, student: Student, seat: object) -> None:
        if isinstance(seat, bool) or not isinstance(seat, int) or not 0 <= seat < self.seat_count:
            raise RoomError("That seat does not exist.")
        holder = self.student_at(seat)
        if holder is not None and holder is not student:
            raise RoomError("Someone just took that seat. Pick another one.")
        self.active(student)
        if student.seat != seat:
            student.seat = seat  # a raised hand moves with its student
            self.dirty = True

    def leave_seat(self, student: Student) -> int | None:
        """Empties the student's seat and returns which one it was. A raised hand goes down."""
        seat = student.seat
        if seat is not None:
            student.seat = None
            student.hand = None
            self.active(student)
            self.dirty = True
        return seat

    def set_hand(self, student: Student, up: object) -> None:
        """Raise or lower a hand. Hands are answered in the order they went up."""
        if not isinstance(up, bool):
            raise RoomError("A hand is either up or down.")
        if up and student.seat is None:
            raise RoomError("Take a seat before raising your hand.")
        if up == (student.hand is not None):
            return
        if up:
            student.hand = self.next_hand
            self.next_hand += 1
            self.active(student)
        else:
            student.hand = None
        self.dirty = True

    def set_hint(self, student: Student, text: object) -> None:
        """Put a note from the teacher on the student's screen. Blank text takes it away."""
        hint = clean_block(text, MAX_HINT, "The hint", required=False).strip()
        if hint != student.hint:
            student.hint = hint
            self.dirty = True

    def hand_places(self) -> dict[str, int]:
        """Each raised hand's place in the queue, by student id: 1 went up first.

        A student who is offline is left out but keeps their ticket, so a reload
        or a dropped connection does not cost them their place.
        """
        waiting = [s for s in self.students.values() if s.seat is not None and s.hand is not None and s.online]
        waiting.sort(key=lambda student: student.hand)
        return {student.id: place for place, student in enumerate(waiting, start=1)}

    def set_source(self, student: Student, text: object) -> bool:
        """Stores the student's code. True if this typing ended an idle spell, so the teacher can be told."""
        source = check_source(text)
        if student.source == source:
            return False
        student.source = source
        self.dirty = True
        return self.active(student)

    def set_teacher_source(self, text: object) -> None:
        source = check_source(text)
        if self.teacher_source != source:
            self.teacher_source = source
            self.dirty = True

    def record_run(self, student: Student, status: object) -> None:
        if status not in RUN_STATES:
            raise RoomError("Unknown run result.")
        student.last_run = status
        # A run that works ends a streak of crashes. It says nothing about a step's
        # check, so it leaves the count of missed checks alone.
        student.crashes = student.crashes + 1 if status == "error" else 0
        self.active(student)
        self.dirty = True

    def step(self, step_id: object) -> Step:
        for step in self.steps:
            if step.id == step_id:
                return step
        raise RoomError("That step is not in the lesson any more.")

    def passed_steps(self, student: Student) -> list[str]:
        """The student's passed steps in lesson order."""
        return [step.id for step in self.steps if step.id in student.passed]

    def set_steps(self, raw: object) -> None:
        """Replace the lesson. Steps keep their ids, so a pass survives a change of wording."""
        if not isinstance(raw, list):
            raise RoomError("Steps must be a list.")
        if len(raw) > MAX_STEPS:
            raise RoomError(f"A lesson can have up to {MAX_STEPS} steps.")
        before = {step.id: step for step in self.steps}
        steps: list[Step] = []
        taken: set[str] = set()
        for number, item in enumerate(raw, start=1):
            if not isinstance(item, dict):
                raise RoomError(f"Step {number} is not a step.")
            step_id = item.get("id")
            if not isinstance(step_id, str) or step_id not in before or step_id in taken:
                step_id = new_id(taken | set(before))
            taken.add(step_id)
            steps.append(
                Step(
                    id=step_id,
                    title=clean_text(item.get("title"), MAX_STEP_TITLE, f"Step {number}'s title"),
                    instructions=clean_block(
                        item.get("instructions"), MAX_INSTRUCTIONS, f"Step {number}'s instructions", required=False
                    ),
                    expected_output=clean_block(
                        item.get("expectedOutput"), MAX_EXPECTED, f"Step {number}'s expected output"
                    ),
                    input=clean_block(item.get("input"), MAX_INPUT, f"Step {number}'s input", required=False),
                )
            )
        # A pass is evidence for one particular check. If the check changed, it is earned again.
        still_valid = {step.id for step in steps if step.id in before and step.same_check(before[step.id])}
        for student in self.students.values():
            student.passed &= still_valid
        self.steps = steps
        if self.current_step not in taken:
            self.current_step = None
        self.dirty = True

    def set_current_step(self, step_id: object) -> None:
        current = None if step_id is None else self.step(step_id).id
        if current != self.current_step:
            self.current_step = current
            self.dirty = True

    def check(self, student: Student, step: Step, status: object, output: object) -> bool:
        """Judge a run the student made for a step. A pass, once earned, stays."""
        if status not in RUN_STATES:
            raise RoomError("Unknown run result.")
        if not isinstance(output, str):
            raise RoomError("Output must be text.")
        self.record_run(student, status)
        passed = status == "ok" and outputs_match(step.expected_output, output[:MAX_CHECK_OUTPUT])
        if passed:
            student.passed.add(step.id)
            student.misses = 0
        else:
            student.misses += 1
        return passed

    def seats(self, for_teacher: bool) -> list[dict]:
        """Occupied seats. Students see who sits where; the rest is for the teacher only:
        run results, passes, raised hands, and who looks stuck or idle."""
        result = []
        places = self.hand_places() if for_teacher else {}
        now = time.time()
        for student in self.students.values():
            if student.seat is None:
                continue
            entry = {"seat": student.seat, "name": student.name, "online": student.online}
            if for_teacher:
                entry["lastRun"] = student.last_run
                entry["passed"] = self.passed_steps(student)
                entry["hand"] = places.get(student.id)
                entry["stuck"] = student.stuck
                entry["idleMinutes"] = self.idle_minutes(student, now)
                entry["hint"] = student.hint or None
            result.append(entry)
        result.sort(key=lambda entry: entry["seat"])
        return result

    def lobby(self) -> list[str]:
        """Names of students who are connected but have not picked a seat yet."""
        return sorted(s.name for s in self.students.values() if s.online and s.seat is None)

    # ---------------------------------------------------------------- storage

    def state(self) -> dict:
        """Everything worth keeping between server runs. Who is online is not."""
        return {
            "teacherSource": self.teacher_source,
            "steps": [step.info() for step in self.steps],
            "currentStep": self.current_step,
            "students": [
                {
                    "id": student.id,
                    "name": student.name,
                    "seat": student.seat,
                    "source": student.source,
                    "lastRun": student.last_run,
                    "passed": self.passed_steps(student),
                    "hand": student.hand,
                    "crashes": student.crashes,
                    "misses": student.misses,
                    "hint": student.hint,
                }
                for student in self.students.values()
            ],
        }

    def record(self) -> ClassRecord:
        return ClassRecord(
            code=self.code,
            teacher_id=self.teacher_id,
            title=self.title,
            rows=self.rows,
            cols=self.cols,
            created_at=self.created_at,
            updated_at=time.time(),
            state=self.state(),
        )

    @classmethod
    def from_record(cls, record: ClassRecord) -> Classroom:
        state = record.state
        room = cls(
            code=record.code,
            title=record.title,
            rows=record.rows,
            cols=record.cols,
            teacher_id=record.teacher_id,
            teacher_source=state.get("teacherSource", ""),
            created_at=record.created_at,
        )
        room.steps = [Step.from_info(info) for info in state.get("steps", [])]
        room.current_step = state.get("currentStep")
        for info in state.get("students", []):
            room.students[info["id"]] = Student(
                id=info["id"],
                name=info["name"],
                seat=info.get("seat"),
                source=info.get("source", ""),
                last_run=info.get("lastRun"),
                passed=set(info.get("passed", [])),
                hand=info.get("hand"),
                crashes=info.get("crashes", 0),
                misses=info.get("misses", 0),
                hint=info.get("hint", ""),
            )
        room.next_hand = max((s.hand for s in room.students.values() if s.hand is not None), default=0) + 1
        return room


def check_source(text: object) -> str:
    if not isinstance(text, str):
        raise RoomError("Code must be text.")
    if len(text) > MAX_SOURCE:
        raise RoomError(f"Code is too long (at most {MAX_SOURCE:,} characters).")
    return text


def new_id(taken: set[str]) -> str:
    while True:
        candidate = secrets.token_urlsafe(6)
        if candidate not in taken:
            return candidate


class ClassroomStore:
    """Live classrooms: loaded from storage when first needed, copied back as they change."""

    def __init__(self, storage: Storage) -> None:
        self.storage = storage
        self._rooms: dict[str, Classroom] = {}
        self._deleted: set[str] = set()  # codes of deleted classes, so a late save cannot bring one back

    def create(self, teacher_id: str, title: object, rows: int, cols: int) -> Classroom:
        clean = clean_text(title, MAX_TITLE, "The class name")
        if not 1 <= rows <= MAX_ROWS or not 1 <= cols <= MAX_COLS:
            raise RoomError(f"A classroom can have up to {MAX_ROWS} rows and {MAX_COLS} seats per row.")
        room = Classroom(code=self._new_code(), title=clean, rows=rows, cols=cols, teacher_id=teacher_id)
        self._rooms[room.code] = room
        self.storage.save_class(room.record())
        return room

    def get(self, code: object) -> Classroom | None:
        if not isinstance(code, str):
            return None
        key = code.strip().upper()
        room = self._rooms.get(key)
        if room is None:
            record = self.storage.load_class(key)
            if record is None:
                return None
            room = Classroom.from_record(record)
            self._rooms[key] = room
        return room

    def loaded(self, code: str) -> Classroom | None:
        """The classroom if it is in memory, without going to storage for it."""
        return self._rooms.get(code)

    def delete(self, code: str) -> None:
        self._deleted.add(code)
        self._rooms.pop(code, None)
        self.storage.delete_class(code)

    def summaries_for(self, teacher_id: str) -> list[dict]:
        """The teacher's classes, newest first, with live counts for the ones in memory."""
        summaries = []
        for record in self.storage.classes_for_teacher(teacher_id):
            live = self._rooms.get(record.code)
            if live is not None:
                students, steps = len(live.students), len(live.steps)
            else:
                students = len(record.state.get("students", []))
                steps = len(record.state.get("steps", []))
            summaries.append(
                {
                    "code": record.code,
                    "title": record.title,
                    "rows": record.rows,
                    "cols": record.cols,
                    "students": students,
                    "steps": steps,
                    "createdAt": record.created_at,
                    "updatedAt": record.updated_at,
                }
            )
        return summaries

    def take_changed(self) -> list[tuple[Classroom, ClassRecord]]:
        """Every changed classroom with a copy of what to save. The classrooms are marked saved.

        Taking the copies is quick and happens where the classrooms are changed;
        writing them (see `write`) may be slow and can then happen on another thread.
        """
        changed = []
        for room in list(self._rooms.values()):
            if room.dirty:
                room.dirty = False
                changed.append((room, room.record()))
        return changed

    def write(self, changed: list[tuple[Classroom, ClassRecord]]) -> None:
        """Writes the copies to storage. A classroom whose write fails counts as changed again."""
        failure: Exception | None = None
        for room, record in changed:
            if record.code in self._deleted:
                continue  # deleted while its copy waited; writing it would bring the class back
            try:
                self.storage.save_class(record)
            except Exception as error:
                room.dirty = True
                failure = failure or error
        if failure is not None:
            raise failure

    def flush(self) -> int:
        """Copy every changed classroom to storage. Returns how many were written."""
        changed = self.take_changed()
        self.write(changed)
        return len(changed)

    def unload_idle(self, now: float | None = None, keep=None) -> None:
        """Drop classrooms nobody has touched for a while, saving them first.

        `keep(room)` may say a room must stay, for example while sockets are open in it.
        A dropped classroom comes back from storage the next time someone asks for it.
        """
        cutoff = (time.time() if now is None else now) - IDLE_SECONDS
        for code, room in list(self._rooms.items()):
            if room.last_active >= cutoff or (keep is not None and keep(room)):
                continue
            if room.dirty:
                room.dirty = False
                self.storage.save_class(room.record())
            del self._rooms[code]

    def _new_code(self) -> str:
        while True:
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            if code not in self._rooms and not self.storage.class_exists(code):
                return code
