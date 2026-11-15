"""A full class on a real server: does CodeSeat hold up with every seat taken?

    .venv\\Scripts\\python tools\\loadtest.py                  30 students for 30 seconds
    .venv\\Scripts\\python tools\\loadtest.py --students 80    the biggest room there is
    .venv\\Scripts\\python tools\\loadtest.py --url https://…  against a server that is already running

Without --url the script starts its own server on a free port with a temporary
database, so it never touches real classes. One teacher and N students connect
over real WebSockets and behave like a lesson: the teacher types and looks at
seats in turn, students type, run, check steps and raise hands. The script
measures how long the server takes to answer and to pass messages on, then
checks that what the server holds at the end is what was sent.

It exits with 1 if anything was lost, refused, slow or wrong.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, WebSocketException

BACKEND = Path(__file__).resolve().parent.parent
REPLY_TIMEOUT = 10  # seconds to wait for the server's answer to one message
SLOW_MS = 500  # a message whose 95th percentile is above this fails the run
SLOW_TO_GET_IN_MS = 5000  # getting in happens once and includes setting up a secure connection

STEPS = [
    {"title": "Say hello", "instructions": "Print Hello.", "input": "", "expectedOutput": "Hello"},
    {"title": "Add two numbers", "instructions": "Read two numbers, print the sum.", "input": "3\n4\n", "expectedOutput": "7"},
]
RIGHT_OUTPUT = ["Hello\n", "7\n"]


@dataclass
class Stats:
    latency: dict[str, list[float]] = field(default_factory=dict)
    sent_by_students: int = 0
    sent_by_teacher: int = 0
    received: int = 0
    conflicts_refused: int = 0
    unexpected_errors: list[str] = field(default_factory=list)
    timeouts: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    retries: list[str] = field(default_factory=list)  # connections that needed a second try to open
    tick_sent: dict[int, float] = field(default_factory=dict)  # teacher's typing, by tick number
    source_sent: dict[tuple[int, int], float] = field(default_factory=dict)  # students' typing, by seat and count

    def took(self, what: str, started: float) -> None:
        self.latency.setdefault(what, []).append((time.perf_counter() - started) * 1000)


class Person:
    """One socket, with a reader that answers whoever is waiting for a reply."""

    def __init__(self, name: str, stats: Stats) -> None:
        self.name = name
        self.stats = stats
        self.ws: ClientConnection | None = None
        self.waiting: tuple[str, asyncio.Future] | None = None
        self.closing = False
        self.reader: asyncio.Task | None = None

    async def open(self, ws_url: str, hello: dict, headers: dict | None = None) -> dict:
        self.ws = await connect(ws_url, additional_headers=headers, max_size=None, open_timeout=30)
        await self.ws.send(json.dumps({"type": "hello", **hello}))
        welcome = json.loads(await asyncio.wait_for(self.ws.recv(), REPLY_TIMEOUT))
        if welcome.get("type") != "welcome":
            raise RuntimeError(f"{self.name}: expected a welcome, got {welcome}")
        self.reader = asyncio.create_task(self.read())
        return welcome

    async def read(self) -> None:
        assert self.ws is not None
        try:
            async for raw in self.ws:
                self.stats.received += 1
                message = json.loads(raw)
                self.handle(message)
                if self.waiting and message.get("type") in (self.waiting[0], "error"):
                    wanted, future = self.waiting
                    if self.accepts(wanted, message) and not future.done():
                        future.set_result(message)
                        self.waiting = None
        except ConnectionClosed as closed:
            if not self.closing:
                self.stats.dropped.append(f"{self.name}: {closed}")
        if self.waiting and not self.waiting[1].done():
            self.waiting[1].cancel()

    def accepts(self, wanted: str, message: dict) -> bool:
        return True

    def handle(self, message: dict) -> None:
        pass

    async def send(self, message: dict) -> None:
        assert self.ws is not None
        await self.ws.send(json.dumps(message))

    async def ask(self, message: dict, reply: str, label: str | None = None) -> dict | None:
        """Send a message and wait for the server's answer of the given type (or an error)."""
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self.waiting = (reply, future)
        started = time.perf_counter()
        try:
            await self.send(message)
            answer = await asyncio.wait_for(future, REPLY_TIMEOUT)
        except (asyncio.TimeoutError, asyncio.CancelledError, ConnectionClosed):
            self.waiting = None
            self.stats.timeouts.append(f"{self.name}: no answer to {message.get('type')}")
            return None
        if label:
            self.stats.took(label, started)
        return answer

    async def close(self) -> None:
        self.closing = True
        if self.ws is not None:
            await self.ws.close()
        if self.reader is not None:
            await asyncio.gather(self.reader, return_exceptions=True)


class Student(Person):
    def __init__(self, index: int, stats: Stats) -> None:
        super().__init__(f"student {index + 1}", stats)
        self.seat = index
        self.count = 0  # how many versions of the code have been sent
        self.text = ""
        self.should_have_passed: set[str] = set()
        self.random = random.Random(1000 + index)

    def handle(self, message: dict) -> None:
        if message.get("type") == "teacher_source":
            tick = re.match(r"# tick (\d+)", message.get("text", ""))
            if tick and int(tick.group(1)) in self.stats.tick_sent:
                self.stats.took("teacher's typing reaches a student", self.stats.tick_sent[int(tick.group(1))])
        elif message.get("type") == "error" and self.waiting is None:
            self.stats.unexpected_errors.append(f"{self.name}: {message.get('message')}")

    async def type_some(self) -> None:
        self.count += 1
        lines = min(40, self.count)
        self.text = f"# seq {self.count}\n" + "".join(f"total = total + {n}\n" for n in range(lines))
        self.stats.source_sent[(self.seat, self.count)] = time.perf_counter()
        await self.send({"type": "source", "text": self.text})
        self.stats.sent_by_students += 1

    async def lesson(self, step_ids: list[str], until: float) -> None:
        next_run = time.perf_counter() + self.random.uniform(3, 10)
        next_hand = time.perf_counter() + self.random.uniform(4, 20)
        while time.perf_counter() < until:
            await asyncio.sleep(self.random.uniform(0.25, 1.0))  # a burst of typing every so often
            await self.type_some()
            now = time.perf_counter()
            if now >= next_run:
                next_run = now + self.random.uniform(6, 12)
                choice = self.random.random()
                if choice < 0.4:
                    await self.send({"type": "run", "status": self.random.choice(["ok", "ok", "error"])})
                    self.stats.sent_by_students += 1
                else:
                    which = self.random.randrange(len(step_ids))
                    right = choice < 0.8
                    output = RIGHT_OUTPUT[which] if right else "something else\n"
                    answer = await self.ask(
                        {"type": "check", "step": step_ids[which], "status": "ok", "output": output},
                        reply="check",
                        label="a step check is judged",
                    )
                    self.stats.sent_by_students += 1
                    if answer is not None:
                        if answer.get("type") != "check" or answer.get("passed") is not right:
                            self.stats.unexpected_errors.append(f"{self.name}: wrong verdict {answer}")
                        elif right:
                            self.should_have_passed.add(step_ids[which])
            if now >= next_hand:
                next_hand = now + self.random.uniform(10, 25)
                for up in (True, False):
                    answer = await self.ask({"type": "hand", "up": up}, reply="you", label="a hand goes up or down")
                    self.stats.sent_by_students += 1
                    if answer is not None and answer.get("hand") is not up:
                        self.stats.unexpected_errors.append(f"{self.name}: hand not {up}: {answer}")
                    await asyncio.sleep(self.random.uniform(0.5, 2.0))


class Teacher(Person):
    def __init__(self, stats: Stats) -> None:
        super().__init__("teacher", stats)
        self.seats: list[dict] = []
        self.watching: int | None = None
        self.snapshot_due: int | None = None  # the first code sent for a newly watched seat is not live typing
        self.tick = 0

    def accepts(self, wanted: str, message: dict) -> bool:
        if wanted == "student_source" and message.get("type") == "student_source":
            return message.get("seat") == self.watching
        return True

    def handle(self, message: dict) -> None:
        kind = message.get("type")
        if kind == "seats":
            self.seats = message["seats"]
        elif kind == "student_source":
            if message["seat"] == self.snapshot_due:
                self.snapshot_due = None
                return
            seq = re.match(r"# seq (\d+)", message.get("text", ""))
            sent = self.stats.source_sent.get((message["seat"], int(seq.group(1)))) if seq else None
            if sent is not None:
                self.stats.took("a student's typing reaches the teacher", sent)
        elif kind == "error" and self.waiting is None:
            self.stats.unexpected_errors.append(f"teacher: {message.get('message')}")

    async def lesson(self, seat_count: int, until: float) -> None:
        look_at = 0
        next_look = 0.0
        while time.perf_counter() < until:
            self.tick += 1
            self.stats.tick_sent[self.tick] = time.perf_counter()
            await self.send({"type": "source", "text": f"# tick {self.tick}\n" + "print('hello')\n" * (self.tick % 30)})
            self.stats.sent_by_teacher += 1
            if time.perf_counter() >= next_look:  # open the next seat, as a teacher walking the room would
                next_look = time.perf_counter() + 2
                self.watching = self.snapshot_due = look_at % seat_count
                await self.send({"type": "watch", "seat": self.watching})
                self.stats.sent_by_teacher += 1
                look_at += 1
            await asyncio.sleep(0.5)


def percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(share * len(ordered)) - 1)]


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


async def wait_until_up(base: str, server: subprocess.Popen) -> None:
    async with httpx.AsyncClient(base_url=base) as client:
        for _ in range(100):
            if server.poll() is not None:
                raise RuntimeError("The test server stopped while starting; see its log.")
            try:
                if (await client.get("/api/health")).status_code == 200:
                    return
            except httpx.TransportError:
                pass
            await asyncio.sleep(0.2)
    raise RuntimeError("The test server did not come up within 20 seconds.")


async def run(base: str, students: int, seconds: float, arrive_over: float) -> tuple[Stats, list[str]]:
    """Runs one lesson. Returns the measurements and the lines of the final-state report."""
    stats = Stats()
    cols = min(10, students)
    rows = math.ceil(students / cols)
    ws_base = base.replace("http", "ws", 1)

    async with httpx.AsyncClient(base_url=base, timeout=30) as client:
        signup = await client.post(
            "/api/teachers",
            json={"name": "Load Test", "email": f"loadtest-{secrets.token_hex(6)}@example.com", "password": secrets.token_urlsafe(16)},
        )
        signup.raise_for_status()
        made = await client.post("/api/classes", json={"title": "Load test", "rows": rows, "cols": cols})
        made.raise_for_status()
        code = made.json()["code"]
        cookie = "; ".join(f"{name}={value}" for name, value in client.cookies.items())

        teacher = Teacher(stats)
        people: list[Student] = []
        try:
            await teacher.open(f"{ws_base}/ws/{code}", {"role": "teacher"}, headers={"Cookie": cookie})
            lesson = await teacher.ask({"type": "set_steps", "steps": STEPS}, reply="steps")
            if lesson is None or lesson.get("type") != "steps":
                raise RuntimeError(f"The lesson was not saved: {lesson}")
            step_ids = [step["id"] for step in lesson["steps"]]

            # Everyone arrives together, as a class does when the code goes up on the board:
            # all at once on a local server, over a few seconds across the internet.
            people = [Student(index, stats) for index in range(students)]
            arriving = time.perf_counter()

            async def arrive(person: Student) -> None:
                await asyncio.sleep(arrive_over * person.seat / students)
                for attempt in range(4):
                    started = time.perf_counter()
                    try:
                        await person.open(f"{ws_base}/ws/{code}", {"role": "student", "name": f"Student {person.seat + 1}", "studentId": None})
                    except (OSError, TimeoutError, WebSocketException) as error:
                        if attempt == 3:
                            raise
                        stats.retries.append(f"{person.name}: {type(error).__name__}")
                        await asyncio.sleep(1 + attempt)
                    else:
                        stats.took("a student gets in", started)
                        return

            await arrive(people[0])
            await people[0].ask({"type": "take_seat", "seat": 0}, reply="you", label="a seat is taken")
            await asyncio.gather(*(arrive(person) for person in people[1:]))

            async def sit(person: Student) -> None:
                if 1 <= person.seat <= 5:  # a few reach for a seat that is already taken
                    refused = await person.ask({"type": "take_seat", "seat": 0}, reply="you")
                    if refused is not None and refused.get("type") == "error":
                        stats.conflicts_refused += 1
                    else:
                        stats.unexpected_errors.append(f"{person.name}: took an occupied seat: {refused}")
                answer = await person.ask({"type": "take_seat", "seat": person.seat}, reply="you", label="a seat is taken")
                if answer is None or answer.get("seat") != person.seat:
                    stats.unexpected_errors.append(f"{person.name}: did not get seat {person.seat}: {answer}")

            await asyncio.gather(*(sit(person) for person in people[1:]))
            joined_in = time.perf_counter() - arriving

            until = time.perf_counter() + seconds
            await asyncio.gather(teacher.lesson(students, until), *(person.lesson(step_ids, until) for person in people))
            await asyncio.sleep(1)  # let the last messages land

            # ---- what the server holds must be what was sent
            report = [f"everyone in and seated       {students}/{students} in {joined_in:.2f} s"]
            seated = {seat["seat"] for seat in teacher.seats}
            online = sum(1 for seat in teacher.seats if seat["online"])
            report.append(f"seats on the teacher's map   {len(seated)}/{students} taken, {online} online")
            if len(seated) != students or online != students:
                stats.unexpected_errors.append("the teacher's map does not show every student seated and online")

            same = 0
            for person in people:
                teacher.watching = teacher.snapshot_due = person.seat  # a stored copy, not live typing to be timed
                answer = await teacher.ask({"type": "watch", "seat": person.seat}, reply="student_source")
                if answer is not None and answer.get("text") == person.text:
                    same += 1
            report.append(f"code held as last typed      {same}/{students}")
            if same != students:
                stats.unexpected_errors.append(f"{students - same} students' code on the server is not what they last sent")

            by_seat = {seat["seat"]: seat for seat in teacher.seats}
            expected = sum(len(person.should_have_passed) for person in people)
            recorded = sum(len(person.should_have_passed & set(by_seat.get(person.seat, {}).get("passed", []))) for person in people)
            report.append(f"passes recorded              {recorded}/{expected}")
            if recorded != expected:
                stats.unexpected_errors.append("some passed checks are missing from the teacher's map")

            listed = (await client.get("/api/classes")).json()["classes"]
            saved = next((item["students"] for item in listed if item["code"] == code), None)
            report.append(f"students in the saved class  {saved}/{students}")
            if saved != students:
                stats.unexpected_errors.append("the saved class does not list every student")

        finally:
            # Whatever happened, leave nothing behind: sockets closed, the test class deleted.
            await asyncio.gather(teacher.close(), *(person.close() for person in people), return_exceptions=True)
            await client.delete(f"/api/classes/{code}")
    return stats, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Fill a CodeSeat class and see whether the server keeps up.")
    parser.add_argument("--students", type=int, default=30, help="how many students join (1 to 80, default 30)")
    parser.add_argument("--seconds", type=float, default=30, help="how long the lesson lasts (default 30)")
    parser.add_argument("--url", help="test a server that is already running, for example https://codeseat.example")
    parser.add_argument(
        "--arrive-over",
        type=float,
        help="seconds over which the students connect (default 0 for the script's own server, 5 with --url)",
    )
    args = parser.parse_args()
    if not 1 <= args.students <= 80:
        parser.error("a classroom holds 1 to 80 students")

    server = None
    log_path = None
    if args.url:
        base = args.url.rstrip("/")
        where = f"{base} (already running; a test teacher account is left behind there)"
    else:
        folder = tempfile.mkdtemp(prefix="codeseat-loadtest-")
        log_path = Path(folder) / "server.log"
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        where = f"its own server on port {port}, temporary database"
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir", str(BACKEND), "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
            env={**os.environ, "CODESEAT_DATABASE": str(Path(folder) / "loadtest.db")},
            stdout=log_path.open("w"),
            stderr=subprocess.STDOUT,
        )

    print(f"CodeSeat load test: {args.students} students and a teacher for {args.seconds:g} s, on {where}")
    try:
        if server is not None:
            asyncio.run(wait_until_up(base, server))
        arrive_over = args.arrive_over if args.arrive_over is not None else (5.0 if args.url else 0.0)
        stats, report = asyncio.run(run(base, args.students, args.seconds, arrive_over))
    finally:
        if server is not None:
            server.terminate()
            server.wait(timeout=10)

    server_errors = 0
    if log_path is not None:
        log = log_path.read_text(errors="replace")
        server_errors = log.count("Traceback") + len(re.findall(r"^ERROR", log, re.MULTILINE))

    print()
    for line in report:
        print(" ", line)
    print(f"  seat conflicts refused       {stats.conflicts_refused}/{min(5, args.students - 1)}")
    print(f"  connections that needed a retry  {len(stats.retries)}")
    print(f"  messages                     {stats.sent_by_students:,} from students, {stats.sent_by_teacher:,} from the teacher, {stats.received:,} delivered")
    print()
    print(f"  {'how long the server took (ms)':42}{'median':>8}{'95%':>8}{'worst':>8}{'count':>8}")
    slow = []
    for what, values in stats.latency.items():
        p95 = percentile(values, 0.95)
        print(f"  {what:42}{percentile(values, 0.5):8.1f}{p95:8.1f}{max(values):8.1f}{len(values):8,}")
        limit = SLOW_TO_GET_IN_MS if what == "a student gets in" else SLOW_MS
        if p95 > limit:
            slow.append(f"{what} (over {limit} ms)")
    print()

    problems = []
    if stats.dropped:
        problems.append(f"{len(stats.dropped)} connections dropped, first: {stats.dropped[0]}")
    if stats.timeouts:
        problems.append(f"{len(stats.timeouts)} messages got no answer, first: {stats.timeouts[0]}")
    if stats.unexpected_errors:
        problems.append(f"{len(stats.unexpected_errors)} things went wrong, first: {stats.unexpected_errors[0]}")
    if stats.conflicts_refused != min(5, args.students - 1):
        problems.append("a seat that was already taken was not refused every time")
    if slow:
        problems.append(f"too slow at the 95th percentile: {', '.join(slow)}")
    if server_errors:
        problems.append(f"{server_errors} errors in the server's log: {log_path}")

    if problems:
        print("RESULT: FAIL")
        for problem in problems:
            print("  -", problem)
        return 1
    print("RESULT: PASS. Nothing dropped, lost, refused or slow.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
