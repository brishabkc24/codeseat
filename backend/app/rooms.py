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
IDLE_SECONDS = 2 * 60 * 60  # a classroom nobody has touched for this long leaves memory
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
        elif student.name != clean:
            student.name = clean
            self.dirty = True
        return student

    def take_seat(self, student: Student, seat: object) -> None:
        if isinstance(seat, bool) or not isinstance(seat, int) or not 0 <= seat < self.seat_count:
            raise RoomError("That seat does not exist.")
        holder = self.student_at(seat)
        if holder is not None and holder is not student:
            raise RoomError("Someone just took that seat. Pick another one.")
        if student.seat != seat:
            student.seat = seat
            self.dirty = True

    def leave_seat(self, student: Student) -> int | None:
        """Empties the student's seat and returns which one it was."""
        seat = student.seat
        if seat is not None:
            student.seat = None
            self.dirty = True
        return seat

    def set_source(self, student: Student, text: object) -> None:
        source = check_source(text)
        if student.source != source:
            student.source = source
            self.dirty = True

    def set_teacher_source(self, text: object) -> None:
        source = check_source(text)
        if self.teacher_source != source:
            self.teacher_source = source
            self.dirty = True

    def record_run(self, student: Student, status: object) -> None:
        if status not in RUN_STATES:
            raise RoomError("Unknown run result.")
        student.last_run = status
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
        return passed

    def seats(self, for_teacher: bool) -> list[dict]:
        """Occupied seats. Students see who sits where; only the teacher sees run results."""
        result = []
        for student in self.students.values():
            if student.seat is None:
                continue
            entry = {"seat": student.seat, "name": student.name, "online": student.online}
            if for_teacher:
                entry["lastRun"] = student.last_run
                entry["passed"] = self.passed_steps(student)
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
            )
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

    def delete(self, code: str) -> None:
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

    def flush(self) -> int:
        """Copy every changed classroom to storage. Returns how many were written."""
        written = 0
        for room in list(self._rooms.values()):
            if room.dirty:
                room.dirty = False
                self.storage.save_class(room.record())
                written += 1
        return written

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
