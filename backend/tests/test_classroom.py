"""End-to-end tests of the classroom: real HTTP calls and real WebSockets against the app."""

from __future__ import annotations

import time
from contextlib import contextmanager
from unittest.mock import ANY

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import main
from app.accounts import LOGIN_ATTEMPTS, LOGIN_WINDOW_SECONDS, LoginBrake, Throttle, check_password, hash_password
from app.rooms import (
    IDLE_SECONDS,
    MAX_HINT,
    MAX_STEPS,
    STUCK_AFTER,
    STUDENT_IDLE_SECONDS,
    Classroom,
    ClassroomStore,
    RoomError,
    outputs_match,
    page_shows,
)
from app.storage import SqliteStorage as Storage, TeacherRecord


@pytest.fixture
def client():
    main.store = ClassroomStore(Storage(":memory:"))
    main.hub = main.Hub()
    main.brake = LoginBrake()
    main.admin_brake = LoginBrake()
    main.signups_from_one_address = Throttle(main.SIGNUPS_PER_ADDRESS, 3600)
    main.signups_in_all = Throttle(main.SIGNUPS_IN_ALL, 3600)
    main.classes_by_one_teacher = Throttle(main.NEW_CLASSES_PER_TEACHER, 3600)
    main.ADMIN_PASSWORD = ""
    main.APPROVAL_OFF = False
    main.presence_sent = {}
    main.seat_news = {}
    with TestClient(main.app) as test_client:
        yield test_client


def teacher_seat(seat, name, **changes):
    """A seat as the teacher is sent it, for a student who is online and has done nothing yet."""
    entry = {
        "seat": seat,
        "name": name,
        "online": True,
        "lastRun": None,
        "passed": [],
        "hand": None,
        "stuck": False,
        "idleMinutes": None,
        "hint": None,
    }
    return {**entry, **changes}


TEACHER = {"name": "Ms Rai", "email": "rai@example.com", "password": "correct horse battery"}


def sign_up(client, **changes):
    response = client.post("/api/teachers", json={**TEACHER, **changes})
    assert response.status_code == 201, response.text
    return response.json()["teacher"]


def open_class(client, rows=2, cols=3, **more):
    """A class of the signed-in teacher; signs one up first when the client has no session."""
    if client.get("/api/session").json()["teacher"] is None:
        sign_up(client)
    response = client.post("/api/classes", json={"title": "Intro to Python", "rows": rows, "cols": cols, **more})
    assert response.status_code == 201, response.text
    return response.json()


def next_of(ws, kind):
    """Read messages until one of the wanted type arrives."""
    while True:
        message = ws.receive_json()
        if message["type"] == kind:
            return message


@contextmanager
def student(client, code, name, student_id=None):
    with client.websocket_connect(f"/ws/{code}") as ws:
        ws.send_json({"type": "hello", "role": "student", "name": name, "studentId": student_id})
        ws.welcome = next_of(ws, "welcome")
        yield ws


@contextmanager
def teacher(client, room):
    """The teacher's socket: the client's session cookie travels with the connection."""
    with client.websocket_connect(f"/ws/{room['code']}") as ws:
        ws.send_json({"type": "hello", "role": "teacher"})
        ws.welcome = next_of(ws, "welcome")
        yield ws


def sit(ws, seat):
    ws.send_json({"type": "take_seat", "seat": seat})
    return next_of(ws, "you")


STEP = {"title": "Say hello", "instructions": "Print a greeting.", "expectedOutput": "Hello, world!\n", "input": ""}
SUM_STEP = {"title": "Add two numbers", "expectedOutput": "7", "input": "3\n4\n"}


def set_steps(desk, steps):
    desk.send_json({"type": "set_steps", "steps": steps})
    return next_of(desk, "steps")


def check(ws, step_id, output, status="ok"):
    ws.send_json({"type": "check", "step": step_id, "status": status, "output": output})
    return next_of(ws, "check")


def seats_with(desk, wanted):
    """Teacher seat lists arrive in bursts; wait for the one that satisfies `wanted`."""
    while True:
        message = next_of(desk, "seats")
        if wanted(message["seats"]):
            return message["seats"]


# ---------------------------------------------------------------- REST


def test_create_and_look_up_a_class(client):
    room = open_class(client)
    assert len(room["code"]) == 6
    assert set(room) == {"code", "title", "rows", "cols", "language"}

    found = client.get(f"/api/classes/{room['code'].lower()}")  # codes are not case sensitive
    assert found.status_code == 200
    assert found.json() == {
        "code": room["code"],
        "title": "Intro to Python",
        "rows": 2,
        "cols": 3,
        "language": "python",
        "seatsTaken": 0,
    }


def test_unknown_class_is_404(client):
    assert client.get("/api/classes/NOPE22").status_code == 404


def test_classroom_size_is_limited(client):
    sign_up(client)
    response = client.post("/api/classes", json={"title": "Too big", "rows": 50, "cols": 50})
    assert response.status_code == 400


# ---------------------------------------------------------------- joining and seats


def test_socket_to_unknown_class_is_closed(client):
    with client.websocket_connect("/ws/NOPE22") as ws:
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    assert closed.value.code == main.CLOSE_NO_CLASS


def test_teacher_socket_needs_the_owners_session(client):
    room = open_class(client)
    client.cookies.clear()
    with client.websocket_connect(f"/ws/{room['code']}") as ws:
        ws.send_json({"type": "hello", "role": "teacher"})
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    assert closed.value.code == main.CLOSE_NOT_TEACHER

    sign_up(client, email="other@example.com")
    with client.websocket_connect(f"/ws/{room['code']}") as ws:
        ws.send_json({"type": "hello", "role": "teacher"})
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    assert closed.value.code == main.CLOSE_NOT_TEACHER


def test_student_without_a_name_is_refused(client):
    room = open_class(client)
    with client.websocket_connect(f"/ws/{room['code']}") as ws:
        ws.send_json({"type": "hello", "role": "student", "name": "   "})
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    assert closed.value.code == main.CLOSE_BAD_HELLO


def test_student_takes_a_seat_and_others_see_it(client):
    room = open_class(client)
    with student(client, room["code"], "Asha") as asha, student(client, room["code"], "Bikram") as bikram:
        assert asha.welcome["you"]["seat"] is None
        assert sit(asha, 4) == {"type": "you", "seat": 4, "hand": False}

        seats = next_of(bikram, "seats")
        while not seats["seats"]:  # skip the updates from the two of them connecting
            seats = next_of(bikram, "seats")
        assert seats["seats"] == [{"seat": 4, "name": "Asha", "online": True}]


def test_a_taken_seat_cannot_be_taken_again(client):
    room = open_class(client)
    with student(client, room["code"], "Asha") as asha, student(client, room["code"], "Bikram") as bikram:
        sit(asha, 0)
        bikram.send_json({"type": "take_seat", "seat": 0})
        assert "took that seat" in next_of(bikram, "error")["message"]
        assert sit(bikram, 1)["seat"] == 1


def test_a_seat_outside_the_room_is_refused(client):
    room = open_class(client, rows=2, cols=3)
    with student(client, room["code"], "Asha") as asha:
        for bad in (6, -1, "0", True, None):
            asha.send_json({"type": "take_seat", "seat": bad})
            assert next_of(asha, "error")["message"] == "That seat does not exist."


def test_rejoining_keeps_the_seat_and_the_code(client):
    room = open_class(client)
    with student(client, room["code"], "Asha") as asha:
        student_id = asha.welcome["you"]["id"]
        sit(asha, 2)
        asha.send_json({"type": "source", "text": "print('hi')"})
        sit(asha, 2)  # a round trip, so the source above has been stored

    with student(client, room["code"], "Asha", student_id) as again:
        assert again.welcome["you"] == {
            "id": student_id,
            "name": "Asha",
            "seat": 2,
            "source": "print('hi')",
            "passed": [],
            "hand": False,
            "hint": "",
        }


def test_seat_shows_offline_after_the_student_disconnects(client):
    room = open_class(client)
    with teacher(client, room) as desk:
        with student(client, room["code"], "Asha") as asha:
            sit(asha, 0)
            seats = next_of(desk, "seats")
            while not seats["seats"]:
                seats = next_of(desk, "seats")
            assert seats["seats"][0]["online"] is True
        seats = next_of(desk, "seats")
        assert seats["seats"] == [teacher_seat(0, "Asha", online=False)]


def test_students_get_seat_changes_as_one_bundle(client):
    room = open_class(client)
    with student(client, room["code"], "Asha") as asha:
        sit(asha, 0)

        def quiet():
            """Lets any bundle on its way arrive, then reads past everything up to a marker."""
            time.sleep(main.SEAT_NEWS_SECONDS * 3)
            asha.send_json({"type": "hand", "up": "marker"})
            return next_of(asha, "error")

        quiet()
        live = main.store.get(room["code"])

        async def three_changes():
            for _ in range(3):
                await main.broadcast_seats(live)
            return len(main.seat_news)

        assert client.portal.call(three_changes) == 1  # one bundle is on its way, not three
        assert asha.receive_json()["type"] == "seats"
        time.sleep(main.SEAT_NEWS_SECONDS * 3)
        asha.send_json({"type": "hand", "up": "marker"})
        assert asha.receive_json()["type"] == "error"  # nothing else arrived in between
        assert main.seat_news == {}


# ---------------------------------------------------------------- live code


def test_teacher_code_reaches_students_live_and_on_joining(client):
    room = open_class(client)
    with teacher(client, room) as desk:
        with student(client, room["code"], "Asha") as asha:
            desk.send_json({"type": "source", "text": "x = 1"})
            assert next_of(asha, "teacher_source")["text"] == "x = 1"

        with student(client, room["code"], "Bikram") as late:
            assert late.welcome["teacherSource"] == "x = 1"


def test_teacher_watches_one_seat_live(client):
    room = open_class(client)
    with (
        teacher(client, room) as desk,
        student(client, room["code"], "Asha") as asha,
        student(client, room["code"], "Bikram") as bikram,
    ):
        sit(asha, 0)
        sit(bikram, 1)
        asha.send_json({"type": "source", "text": "a = 1"})
        sit(asha, 0)

        desk.send_json({"type": "watch", "seat": 0})
        assert next_of(desk, "student_source") == {"type": "student_source", "seat": 0, "text": "a = 1"}

        # Bikram is not being watched, so his typing must not reach the teacher.
        bikram.send_json({"type": "source", "text": "b = 2"})
        sit(bikram, 1)
        asha.send_json({"type": "source", "text": "a = 100"})
        assert next_of(desk, "student_source") == {"type": "student_source", "seat": 0, "text": "a = 100"}


def test_watching_an_empty_seat_is_an_error(client):
    room = open_class(client)
    with teacher(client, room) as desk:
        desk.send_json({"type": "watch", "seat": 3})
        assert next_of(desk, "error")["message"] == "Nobody is sitting in that seat."


def test_a_new_occupant_is_not_watched_without_asking(client):
    room = open_class(client)
    with (
        teacher(client, room) as desk,
        student(client, room["code"], "Asha") as asha,
        student(client, room["code"], "Bikram") as bikram,
    ):
        sit(asha, 0)
        desk.send_json({"type": "watch", "seat": 0})
        next_of(desk, "student_source")

        asha.send_json({"type": "leave_seat"})
        assert next_of(asha, "you")["seat"] is None
        sit(bikram, 0)
        bikram.send_json({"type": "source", "text": "secret = 1"})
        sit(bikram, 0)

        desk.send_json({"type": "watch", "seat": 0})
        # The first code the teacher gets for the seat is the reply to this new request.
        assert next_of(desk, "student_source")["text"] == "secret = 1"
        assert main.hub.teachers(room["code"])[0].watching == 0


def test_run_results_go_to_the_teacher_only(client):
    room = open_class(client)
    with (
        teacher(client, room) as desk,
        student(client, room["code"], "Asha") as asha,
        student(client, room["code"], "Bikram") as bikram,
    ):
        sit(asha, 0)
        sit(bikram, 1)
        asha.send_json({"type": "run", "status": "error"})

        seats = next_of(desk, "seats")
        while not any(seat.get("lastRun") for seat in seats["seats"]):
            seats = next_of(desk, "seats")
        assert seats["seats"][0] == teacher_seat(0, "Asha", lastRun="error")
        assert seats["lobby"] == []

        bikram.send_json({"type": "leave_seat"})
        assert next_of(bikram, "you")["seat"] is None
        for seat in next_of(bikram, "seats")["seats"]:
            assert set(seat) == {"seat", "name", "online"}  # nothing a classmate should not see


def test_students_cannot_use_teacher_messages(client):
    room = open_class(client)
    with student(client, room["code"], "Asha") as asha, student(client, room["code"], "Bikram") as bikram:
        sit(asha, 0)
        sit(bikram, 1)
        asha.send_json({"type": "hand", "up": True})
        assert next_of(asha, "you")["hand"] is True
        bikram.send_json({"type": "free_seat", "seat": 0})
        bikram.send_json({"type": "watch", "seat": 0})
        bikram.send_json({"type": "lower_hand", "seat": 0})
        bikram.send_json({"type": "hint", "seat": 0, "text": "copy mine"})
        bikram.send_json({"type": "set_steps", "steps": [STEP]})
        bikram.send_json({"type": "set_current_step", "step": None})
        assert sit(bikram, 1)["seat"] == 1  # still served, and the messages above did nothing
        assert main.store.get(room["code"]).student_at(0).name == "Asha"
        assert main.store.get(room["code"]).student_at(0).hand is not None
        assert main.store.get(room["code"]).student_at(0).hint == ""
        assert main.store.get(room["code"]).steps == []


def test_teacher_can_free_a_seat(client):
    room = open_class(client)
    with teacher(client, room) as desk, student(client, room["code"], "Asha") as asha:
        sit(asha, 5)
        desk.send_json({"type": "free_seat", "seat": 5})
        assert next_of(asha, "you") == {"type": "you", "seat": None, "hand": False}
        assert main.store.get(room["code"]).student_at(5) is None


def test_a_second_tab_takes_over_from_the_first(client):
    room = open_class(client)
    with student(client, room["code"], "Asha") as first:
        student_id = first.welcome["you"]["id"]
        sit(first, 0)
        with student(client, room["code"], "Asha", student_id) as second:
            with pytest.raises(WebSocketDisconnect) as closed:
                while True:
                    first.receive_json()
            assert closed.value.code == main.CLOSE_REPLACED
            assert second.welcome["you"]["seat"] == 0
            assert main.store.get(room["code"]).students[student_id].online is True


# ---------------------------------------------------------------- lesson steps


def test_lesson_reaches_everyone_live_and_on_joining(client):
    room = open_class(client)
    with teacher(client, room) as desk, student(client, room["code"], "Asha") as asha:
        lesson = set_steps(desk, [STEP, SUM_STEP])
        assert [step["title"] for step in lesson["steps"]] == ["Say hello", "Add two numbers"]
        assert all(step["id"] for step in lesson["steps"])
        assert lesson["currentStep"] is None
        assert next_of(asha, "steps") == lesson

        with student(client, room["code"], "Bikram") as late:
            assert late.welcome["steps"] == lesson["steps"]
            assert late.welcome["you"]["passed"] == []


def test_lesson_is_validated_and_left_alone_on_a_bad_save(client):
    room = open_class(client)
    with teacher(client, room) as desk:
        set_steps(desk, [STEP])

        desk.send_json({"type": "set_steps", "steps": [{"title": "", "expectedOutput": "x"}]})
        assert next_of(desk, "error")["message"] == "Step 1's title is missing."
        desk.send_json({"type": "set_steps", "steps": [STEP, {"title": "No check"}]})
        assert next_of(desk, "error")["message"] == "Step 2's expected output is missing."
        desk.send_json({"type": "set_steps", "steps": [STEP] * (MAX_STEPS + 1)})
        assert next_of(desk, "error")["message"] == f"A lesson can have up to {MAX_STEPS} steps."
        desk.send_json({"type": "set_steps", "steps": "nope"})
        assert next_of(desk, "error")["message"] == "Steps must be a list."

        assert [step.title for step in main.store.get(room["code"]).steps] == ["Say hello"]


def test_a_check_passes_on_the_expected_output_and_the_teacher_sees_it(client):
    room = open_class(client)
    with teacher(client, room) as desk, student(client, room["code"], "Asha") as asha:
        hello, total = set_steps(desk, [STEP, SUM_STEP])["steps"]
        sit(asha, 0)

        # Spaces at the ends of lines and blank lines at the end do not count.
        verdict = check(asha, hello["id"], "Hello, world!   \r\n\n")
        assert verdict == {"type": "check", "step": hello["id"], "passed": True}
        seats = seats_with(desk, lambda seats: seats and seats[0]["passed"])
        assert seats[0] == teacher_seat(0, "Asha", lastRun="ok", passed=[hello["id"]])

        assert check(asha, total["id"], "8")["passed"] is False
        assert check(asha, total["id"], "7\n", status="error")["passed"] is False  # a crash never passes
        assert check(asha, total["id"], "7")["passed"] is True
        seats = seats_with(desk, lambda seats: len(seats[0]["passed"]) == 2)
        assert seats[0]["passed"] == [hello["id"], total["id"]]  # lesson order, not the order passed

        # A pass is kept, so a later failing run does not take it away.
        assert check(asha, hello["id"], "Goodbye")["passed"] is False
        student_id = asha.welcome["you"]["id"]
    with student(client, room["code"], "Asha", student_id) as back:
        assert back.welcome["you"]["passed"] == [hello["id"], total["id"]]


def test_students_never_see_who_passed(client):
    room = open_class(client)
    with teacher(client, room) as desk, student(client, room["code"], "Asha") as asha:
        (hello,) = set_steps(desk, [STEP])["steps"]
        sit(asha, 0)
        check(asha, hello["id"], "Hello, world!")
        with student(client, room["code"], "Bikram") as bikram:
            assert bikram.welcome["seats"] == [{"seat": 0, "name": "Asha", "online": True}]


def test_checking_an_unknown_step_is_an_error(client):
    room = open_class(client)
    with student(client, room["code"], "Asha") as asha:
        asha.send_json({"type": "check", "step": "gone", "status": "ok", "output": ""})
        assert next_of(asha, "error")["message"] == "That step is not in the lesson any more."


def test_editing_a_step_keeps_passes_unless_its_check_changed(client):
    room = open_class(client)
    with teacher(client, room) as desk, student(client, room["code"], "Asha") as asha:
        hello, total = set_steps(desk, [STEP, SUM_STEP])["steps"]
        sit(asha, 0)
        check(asha, hello["id"], "Hello, world!")
        check(asha, total["id"], "7")

        # Reworded and reordered, same checks: both passes stay and the ids are kept.
        reworded = {**total, "title": "Sum two numbers", "instructions": "Read two numbers."}
        lesson = set_steps(desk, [reworded, hello])
        assert [step["id"] for step in lesson["steps"]] == [total["id"], hello["id"]]
        assert next_of(asha, "you")["passed"] == [total["id"], hello["id"]]

        # A new expected output means the old pass proves nothing.
        harder = {**hello, "expectedOutput": "Hello, Asha!"}
        set_steps(desk, [total, harder])
        assert next_of(asha, "you")["passed"] == [total["id"]]
        seats = seats_with(desk, lambda seats: seats[0]["passed"] == [total["id"]])
        assert seats[0]["passed"] == [total["id"]]

        # A removed step takes its pass with it.
        set_steps(desk, [harder])
        assert next_of(asha, "you")["passed"] == []


def test_teacher_points_the_class_at_a_step(client):
    room = open_class(client)
    with teacher(client, room) as desk, student(client, room["code"], "Asha") as asha:
        hello, total = set_steps(desk, [STEP, SUM_STEP])["steps"]
        next_of(asha, "steps")

        desk.send_json({"type": "set_current_step", "step": total["id"]})
        assert next_of(desk, "steps")["currentStep"] == total["id"]
        assert next_of(asha, "steps")["currentStep"] == total["id"]

        desk.send_json({"type": "set_current_step", "step": "gone"})
        assert next_of(desk, "error")["message"] == "That step is not in the lesson any more."

        # Dropping the step the class is on clears the pointer.
        assert set_steps(desk, [hello])["currentStep"] is None

        desk.send_json({"type": "set_current_step", "step": None})
        assert next_of(desk, "steps")["currentStep"] is None


@pytest.mark.parametrize(
    ("expected", "actual", "same"),
    [
        ("7", "7\n", True),
        ("a\nb", "a  \r\nb\n\n", True),
        ("a\nb", "a\n\nb", False),  # a blank line in the middle counts
        ("Hello", "hello", False),  # case counts
        ("", "\n\n", True),
        (" x", "x", False),  # leading spaces count
    ],
)
def test_outputs_match_rules(expected, actual, same):
    assert outputs_match(expected, actual) is same


# ---------------------------------------------------------------- who needs help


def test_raised_hands_queue_up_for_the_teacher_in_order(client):
    room = open_class(client)
    with (
        teacher(client, room) as desk,
        student(client, room["code"], "Asha") as asha,
        student(client, room["code"], "Bikram") as bikram,
    ):
        sit(asha, 0)
        sit(bikram, 1)
        bikram.send_json({"type": "hand", "up": True})
        assert next_of(bikram, "you") == {"type": "you", "seat": 1, "hand": True}
        asha.send_json({"type": "hand", "up": True})
        assert next_of(asha, "you") == {"type": "you", "seat": 0, "hand": True}

        seats = seats_with(desk, lambda seats: len(seats) == 2 and all(seat["hand"] for seat in seats))
        assert [seat["hand"] for seat in seats] == [2, 1]  # Bikram's went up first

        # Classmates see who sits where, never whose hand is up.
        with student(client, room["code"], "Chandra") as chandra:
            assert all(set(seat) == {"seat", "name", "online"} for seat in chandra.welcome["seats"])

        # The first hand comes down and the queue moves up.
        bikram.send_json({"type": "hand", "up": False})
        assert next_of(bikram, "you")["hand"] is False
        seats = seats_with(desk, lambda seats: len(seats) == 2 and seats[1]["hand"] is None)
        assert seats[0]["hand"] == 1

        # The teacher lowers the other one after helping, and the student is told.
        desk.send_json({"type": "lower_hand", "seat": 0})
        assert next_of(asha, "you") == {"type": "you", "seat": 0, "hand": False}
        seats = seats_with(desk, lambda seats: len(seats) == 2 and seats[0]["hand"] is None)
        assert [seat["hand"] for seat in seats] == [None, None]


def test_a_hand_needs_a_seat_and_comes_down_when_the_seat_is_left(client):
    room = open_class(client)
    with student(client, room["code"], "Asha") as asha:
        asha.send_json({"type": "hand", "up": True})
        assert next_of(asha, "error")["message"] == "Take a seat before raising your hand."

        sit(asha, 0)
        asha.send_json({"type": "hand", "up": "yes"})
        assert next_of(asha, "error")["message"] == "A hand is either up or down."
        asha.send_json({"type": "hand", "up": True})
        assert next_of(asha, "you")["hand"] is True

        # Moving to another seat keeps the hand up; leaving the seats lowers it.
        assert sit(asha, 3) == {"type": "you", "seat": 3, "hand": True}
        asha.send_json({"type": "leave_seat"})
        assert next_of(asha, "you") == {"type": "you", "seat": None, "hand": False}


def test_a_run_of_failures_marks_the_seat_as_stuck(client):
    room = open_class(client)
    with teacher(client, room) as desk, student(client, room["code"], "Asha") as asha:
        (hello,) = set_steps(desk, [STEP])["steps"]
        sit(asha, 0)

        def stuck():
            return main.store.get(room["code"]).student_at(0).stuck

        def round_trip():
            sit(asha, 0)  # answered in order, so everything sent before it has been handled

        # Checks that do not pass add up, and a run that merely works does not excuse them.
        for _ in range(STUCK_AFTER - 1):
            check(asha, hello["id"], "Hello")
        assert not stuck()
        asha.send_json({"type": "run", "status": "ok"})
        check(asha, hello["id"], "Hello")
        assert stuck()
        seats = seats_with(desk, lambda seats: bool(seats) and seats[0]["stuck"])
        assert seats[0] == teacher_seat(0, "Asha", lastRun="ok", stuck=True)

        # Passing the step clears it.
        assert check(asha, hello["id"], "Hello, world!")["passed"] is True
        assert not stuck()

        # Crashes add up on their own, and one run that works ends them.
        for _ in range(STUCK_AFTER):
            asha.send_json({"type": "run", "status": "error"})
        round_trip()
        assert stuck()
        asha.send_json({"type": "run", "status": "ok"})
        round_trip()
        assert not stuck()


def test_a_quiet_student_shows_as_idle_until_they_type_again(client):
    room = open_class(client)
    with teacher(client, room) as desk, student(client, room["code"], "Asha") as asha:
        sit(asha, 0)
        seats = seats_with(desk, lambda seats: len(seats) == 1)
        assert seats[0]["idleMinutes"] is None

        # Four minutes and a bit without typing, running or clicking.
        main.store.get(room["code"]).student_at(0).active_at -= STUDENT_IDLE_SECONDS + 65
        client.portal.call(main.push_presence)
        assert next_of(desk, "seats")["seats"] == [teacher_seat(0, "Asha", idleMinutes=4)]

        # With nothing new to tell, a second push says nothing: the next seat list
        # the teacher gets is the one sent because Asha started typing again.
        client.portal.call(main.push_presence)
        asha.send_json({"type": "source", "text": "x = 1"})
        assert next_of(desk, "seats")["seats"] == [teacher_seat(0, "Asha")]


def test_teacher_sends_a_hint_to_one_seat(client):
    room = open_class(client)
    with (
        teacher(client, room) as desk,
        student(client, room["code"], "Asha") as asha,
        student(client, room["code"], "Bikram") as bikram,
    ):
        sit(asha, 0)
        sit(bikram, 1)
        desk.send_json({"type": "hint", "seat": 0, "text": "  Check the colon\r\non line 2.  "})
        assert next_of(asha, "you") == {"type": "you", "hint": "Check the colon\non line 2."}
        seats = seats_with(desk, lambda seats: len(seats) == 2 and seats[0]["hint"])
        assert seats == [teacher_seat(0, "Asha", hint="Check the colon\non line 2."), teacher_seat(1, "Bikram")]

        # It is for Asha alone: Bikram is sent nothing, and no seat list he gets mentions it.
        assert sit(bikram, 1) == {"type": "you", "seat": 1, "hand": False}
        assert all(set(seat) == {"seat", "name", "online"} for seat in next_of(bikram, "seats")["seats"])

        # A new hint replaces the old one; it is still there after a reload.
        desk.send_json({"type": "hint", "seat": 0, "text": "Indent the print."})
        assert next_of(asha, "you")["hint"] == "Indent the print."
        student_id = asha.welcome["you"]["id"]
        with student(client, room["code"], "Asha", student_id) as again:
            assert again.welcome["you"]["hint"] == "Indent the print."

            # The student puts it away, and the teacher sees that it is gone.
            again.send_json({"type": "dismiss_hint"})
            assert next_of(again, "you") == {"type": "you", "hint": ""}
            seats = seats_with(desk, lambda seats: len(seats) == 2 and seats[0]["online"] and not seats[0]["hint"])
            assert seats[0]["hint"] is None

            # The teacher can take a hint back by sending a blank one.
            desk.send_json({"type": "hint", "seat": 0, "text": "Oops"})
            assert next_of(again, "you")["hint"] == "Oops"
            desk.send_json({"type": "hint", "seat": 0, "text": "   "})
            assert next_of(again, "you")["hint"] == ""


def test_a_hint_needs_a_student_and_has_a_length_limit(client):
    room = open_class(client)
    with teacher(client, room) as desk, student(client, room["code"], "Asha") as asha:
        sit(asha, 0)
        desk.send_json({"type": "hint", "seat": 3, "text": "Hello?"})
        assert next_of(desk, "error")["message"] == "Nobody is sitting in that seat."
        desk.send_json({"type": "hint", "seat": 0, "text": "x" * (MAX_HINT + 1)})
        assert next_of(desk, "error")["message"] == f"The hint is too long (at most {MAX_HINT} characters)."
        desk.send_json({"type": "hint", "seat": 0, "text": 7})
        assert next_of(desk, "error")["message"] == "The hint must be text."
        assert main.store.get(room["code"]).student_at(0).hint == ""


def test_idle_is_only_for_students_who_are_seated_and_online():
    room = bare_store().create("t1", "Intro", 1, 2)
    asha = room.join(None, "Asha")
    asha.active_at -= STUDENT_IDLE_SECONDS + 1
    now = asha.active_at + STUDENT_IDLE_SECONDS + 1

    assert room.idle_minutes(asha, now) is None  # not seated, not online
    asha.seat = 0
    assert room.idle_minutes(asha, now) is None  # seated, but offline
    asha.online = True
    assert room.idle_minutes(asha, now) == 3
    assert room.idle_minutes(asha, now - 2) is None  # just under the limit
    assert room.idle_marks() == ((0, 3),)

    assert room.active(asha) is True  # doing something ends the idle spell, and says so once
    assert room.active(asha) is False
    assert room.idle_marks() == ()


def test_hand_tickets_carry_on_after_a_reload():
    room = bare_store().create("t1", "Intro", 1, 3)
    people = []
    for seat, name in enumerate(("Asha", "Bikram", "Chandra")):
        person = room.join(None, name)
        room.take_seat(person, seat)
        people.append(person)
    asha, bikram, chandra = people
    room.set_hand(asha, True)
    room.set_hand(bikram, True)
    room.set_hand(asha, False)

    again = Classroom.from_record(room.record())
    again.set_hand(again.students[chandra.id], True)
    again.set_hand(again.students[asha.id], True)
    assert again.hand_places() == {}  # nobody has reconnected yet
    for person in again.students.values():
        person.online = True
    assert again.hand_places() == {bikram.id: 1, chandra.id: 2, asha.id: 3}


# ---------------------------------------------------------------- web classes


def test_a_class_is_for_python_unless_it_says_web(client):
    assert open_class(client)["language"] == "python"
    web = open_class(client, language="web")
    assert web["language"] == "web"
    assert client.get(f"/api/classes/{web['code']}").json()["language"] == "web"
    with student(client, web["code"], "Asha") as asha:
        assert asha.welcome["class"]["language"] == "web"
    listed = {item["code"]: item["language"] for item in client.get("/api/classes").json()["classes"]}
    assert listed[web["code"]] == "web"

    refused = client.post("/api/classes", json={"title": "x", "rows": 1, "cols": 1, "language": "cobol"})
    assert refused.status_code == 400
    assert refused.json()["detail"] == "A class is for Python or for web pages."

    # The language is kept with the class.
    main.store.flush()
    main.store = ClassroomStore(main.store.storage)
    assert main.store.get(web["code"]).language == "web"


def test_in_a_web_class_a_step_passes_on_the_console_or_on_the_page(client):
    room = open_class(client, language="web")
    with teacher(client, room) as desk, student(client, room["code"], "Asha") as asha:
        heading, greet = set_steps(
            desk,
            [
                {"title": "A heading and a line", "expectedOutput": "My page\nHello there"},
                {"title": "Say it in the console", "expectedOutput": "Hello"},
            ],
        )["steps"]
        sit(asha, 0)

        def web_check(step, output, page, status="ok"):
            asha.send_json({"type": "check", "step": step["id"], "status": status, "output": output, "page": page})
            return next_of(asha, "check")["passed"]

        # The page shows the lines: how far apart they stand, and spaces around them, do not count.
        assert web_check(heading, "", "My page\n\n   Hello   there  \n") is True
        # The console is another way to meet a step.
        assert web_check(greet, "Hello\n", "nothing to do with it") is True
        # Neither the console nor the page has it.
        assert web_check(heading, "My page", "My page") is False
        # A page whose script broke does not pass, whatever it shows.
        assert web_check(heading, "", "My page\nHello there", status="error") is False
        asha.send_json({"type": "check", "step": greet["id"], "status": "ok", "output": "", "page": 7})
        assert next_of(asha, "error")["message"] == "The page must be text."


def test_in_a_python_class_the_page_is_not_looked_at(client):
    room = open_class(client)
    with teacher(client, room) as desk, student(client, room["code"], "Asha") as asha:
        (hello,) = set_steps(desk, [STEP])["steps"]
        sit(asha, 0)
        asha.send_json({"type": "check", "step": hello["id"], "status": "ok", "output": "", "page": "Hello, world!"})
        assert next_of(asha, "check")["passed"] is False


@pytest.mark.parametrize(
    ("expected", "page", "shown"),
    [
        ("Hello", "Hello", True),
        ("A\nB", "A\n\n\nB\n", True),  # block elements stand apart on a page
        ("A  B", " A B ", True),  # runs of spaces are one space on a page
        ("A\nB", "B\nA", False),  # order counts
        ("A\nB", "A B", False),  # lines are lines
        ("Hello", "hello", False),  # case counts
        ("", "", True),
    ],
)
def test_page_shows_rules(expected, page, shown):
    assert page_shows(expected, page) is shown


# ---------------------------------------------------------------- teacher accounts


def test_sign_up_logs_the_teacher_in(client):
    teacher = sign_up(client)
    assert teacher["name"] == "Ms Rai" and teacher["email"] == "rai@example.com"
    assert "password" not in teacher and "password_hash" not in teacher
    assert client.get("/api/session").json()["teacher"] == teacher
    assert main.SESSION_COOKIE in client.cookies


def test_sign_up_is_validated(client):
    for changes, detail in [
        ({"email": "rai"}, "That does not look like an email address."),
        ({"password": "short"}, "Use a password of at least 8 characters."),
        ({"name": "  "}, "Your name is missing."),
    ]:
        response = client.post("/api/teachers", json={**TEACHER, **changes})
        assert response.status_code == 400
        assert response.json()["detail"] == detail


def test_an_email_has_one_account(client):
    sign_up(client)
    response = client.post("/api/teachers", json={**TEACHER, "email": "RAI@example.com", "name": "Other"})
    assert response.status_code == 409


def test_log_in_and_out(client):
    teacher = sign_up(client)
    client.cookies.clear()
    assert client.get("/api/session").json() == {"teacher": None}

    wrong = client.post("/api/session", json={"email": "rai@example.com", "password": "nope nope nope"})
    assert wrong.status_code == 401
    assert wrong.json()["detail"] == "Wrong email or password."
    assert main.SESSION_COOKIE not in client.cookies

    right = client.post("/api/session", json={"email": " Rai@Example.com ", "password": TEACHER["password"]})
    assert right.status_code == 200
    assert right.json()["teacher"] == teacher
    assert client.get("/api/session").json()["teacher"] == teacher

    assert client.delete("/api/session").status_code == 204
    assert client.get("/api/session").json() == {"teacher": None}


def test_wrong_passwords_are_braked(client):
    sign_up(client)
    client.cookies.clear()
    login = {"email": TEACHER["email"], "password": "wrong wrong wrong"}
    for _ in range(LOGIN_ATTEMPTS):
        assert client.post("/api/session", json=login).status_code == 401
    blocked = client.post("/api/session", json={**login, "password": TEACHER["password"]})
    assert blocked.status_code == 429
    assert blocked.json()["detail"].startswith("Too many wrong passwords.")

    # An unknown email is braked the same way, so the brake does not tell who has an account.
    stranger = {"email": "nobody@example.com", "password": "wrong wrong wrong"}
    for _ in range(LOGIN_ATTEMPTS):
        assert client.post("/api/session", json=stranger).status_code == 401
    assert client.post("/api/session", json=stranger).status_code == 429


def test_login_brake_rules():
    brake = LoginBrake()
    for moment in range(LOGIN_ATTEMPTS):
        assert brake.wait("a@b.c", now=1000 + moment) == 0
        brake.failed("a@b.c", now=1000 + moment)
    assert 0 < brake.wait("a@b.c", now=1010) <= LOGIN_WINDOW_SECONDS
    assert brake.wait("a@b.c", now=1000 + LOGIN_WINDOW_SECONDS + 1) == 0  # the window has passed
    brake.failed("a@b.c", now=2000)
    brake.succeeded("a@b.c")
    assert brake.wait("a@b.c", now=2000) == 0


def test_passwords_are_hashed_and_checked():
    stored = hash_password("correct horse battery")
    assert stored.startswith("scrypt$") and "correct" not in stored
    assert check_password("correct horse battery", stored)
    assert not check_password("correct horse batter", stored)
    assert not check_password("anything", "not a hash")
    assert hash_password("same") != hash_password("same")  # salted


# ---------------------------------------------------------------- saved classes


def test_classes_need_a_signed_in_teacher(client):
    assert client.post("/api/classes", json={"title": "x", "rows": 1, "cols": 1}).status_code == 401
    assert client.get("/api/classes").status_code == 401
    assert client.delete("/api/classes/ABCDEF").status_code == 401


def test_teacher_lists_and_deletes_own_classes(client):
    room = open_class(client)
    other = open_class(client, rows=1, cols=1)
    listed = client.get("/api/classes").json()["classes"]
    assert [item["code"] for item in listed] == [other["code"], room["code"]]  # newest first
    assert listed[1] == {
        "code": room["code"],
        "title": "Intro to Python",
        "rows": 2,
        "cols": 3,
        "language": "python",
        "students": 0,
        "steps": 0,
        "createdAt": ANY,
        "updatedAt": ANY,
    }

    with student(client, room["code"], "Asha") as asha:
        sit(asha, 0)
        assert client.delete(f"/api/classes/{room['code']}").status_code == 204
        with pytest.raises(WebSocketDisconnect) as closed:
            while True:
                asha.receive_json()
        assert closed.value.code == main.CLOSE_NO_CLASS
    assert client.get(f"/api/classes/{room['code']}").status_code == 404
    assert [item["code"] for item in client.get("/api/classes").json()["classes"]] == [other["code"]]


def test_another_teacher_cannot_touch_the_class(client):
    room = open_class(client)
    client.cookies.clear()
    sign_up(client, email="other@example.com")
    assert client.delete(f"/api/classes/{room['code']}").status_code == 403
    assert client.get("/api/classes").json()["classes"] == []
    # Students need no account; the class is still there for them.
    assert client.get(f"/api/classes/{room['code']}").status_code == 200


def test_a_class_survives_a_server_restart(client):
    room = open_class(client)
    with teacher(client, room) as desk, student(client, room["code"], "Asha") as asha:
        (hello,) = set_steps(desk, [STEP])["steps"]
        desk.send_json({"type": "source", "text": "# lesson 1"})
        sit(asha, 4)
        asha.send_json({"type": "source", "text": "print('hi')"})
        check(asha, hello["id"], "Hello, world!")
        asha.send_json({"type": "hand", "up": True})
        assert next_of(asha, "you")["hand"] is True
        student_id = asha.welcome["you"]["id"]

    # A new store over the same database is what a restarted server sees.
    main.store.flush()
    main.store = ClassroomStore(main.store.storage)
    with student(client, room["code"], "Asha", student_id) as back:
        assert back.welcome["you"]["seat"] == 4
        assert back.welcome["you"]["source"] == "print('hi')"
        assert back.welcome["you"]["passed"] == [hello["id"]]
        assert back.welcome["you"]["hand"] is True
        assert back.welcome["teacherSource"] == "# lesson 1"
        assert back.welcome["steps"][0]["id"] == hello["id"]
        with teacher(client, room) as desk:
            assert desk.welcome["seats"] == [teacher_seat(4, "Asha", lastRun="ok", passed=[hello["id"]], hand=1)]
    # Once she is offline her hand leaves the queue, though she keeps her place in it.
    with teacher(client, room) as desk:
        assert desk.welcome["seats"] == [teacher_seat(4, "Asha", online=False, lastRun="ok", passed=[hello["id"]])]
    assert main.store.get(room["code"]).student_at(4).hand == 1
    listed = client.get("/api/classes").json()["classes"][0]
    assert (listed["students"], listed["steps"]) == (1, 1)


# ---------------------------------------------------------------- rules on their own


def bare_store():
    """A store on its own database, with one teacher in it to own the classes."""
    storage = Storage(":memory:")
    storage.add_teacher(TeacherRecord(id="t1", name="Ms Rai", email="rai@example.com", password_hash="-", created_at=0))
    return ClassroomStore(storage)


def test_idle_classrooms_leave_memory_and_come_back():
    store = bare_store()
    room = store.create("t1", "Intro", 2, 3)
    room.set_teacher_source("x = 1")
    room.last_active = 0
    store.unload_idle(now=IDLE_SECONDS + 1, keep=lambda r: False)
    again = store.get(room.code)
    assert again is not room
    assert again.teacher_source == "x = 1"  # saved before it left memory

    # A classroom with sockets open stays, however long it has been quiet.
    again.last_active = 0
    store.unload_idle(now=IDLE_SECONDS + 1, keep=lambda r: True)
    assert store.get(room.code) is again


def test_long_code_is_refused():
    store = bare_store()
    room = store.create("t1", "Class", 1, 1)
    asha = room.join(None, "Asha")
    with pytest.raises(RoomError):
        room.set_source(asha, "x" * 50_001)
    assert asha.source == ""
