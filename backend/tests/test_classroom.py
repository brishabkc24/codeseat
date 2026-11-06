"""End-to-end tests of the classroom: real HTTP calls and real WebSockets against the app."""

from __future__ import annotations

import time
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import main
from app.rooms import ROOM_TTL_SECONDS, ClassroomStore, RoomError


@pytest.fixture
def client():
    main.store = ClassroomStore()
    main.hub = main.Hub()
    with TestClient(main.app) as test_client:
        yield test_client


def open_class(client, rows=2, cols=3):
    response = client.post("/api/classes", json={"title": "Intro to Python", "rows": rows, "cols": cols})
    assert response.status_code == 201
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
    with client.websocket_connect(f"/ws/{room['code']}") as ws:
        ws.send_json({"type": "hello", "role": "teacher", "token": room["teacherToken"]})
        ws.welcome = next_of(ws, "welcome")
        yield ws


def sit(ws, seat):
    ws.send_json({"type": "take_seat", "seat": seat})
    return next_of(ws, "you")


# ---------------------------------------------------------------- REST


def test_create_and_look_up_a_class(client):
    room = open_class(client)
    assert len(room["code"]) == 6
    assert room["teacherToken"]

    found = client.get(f"/api/classes/{room['code'].lower()}")  # codes are not case sensitive
    assert found.status_code == 200
    assert found.json() == {
        "code": room["code"],
        "title": "Intro to Python",
        "rows": 2,
        "cols": 3,
        "seatsTaken": 0,
    }
    assert "teacherToken" not in found.json()


def test_unknown_class_is_404(client):
    assert client.get("/api/classes/NOPE22").status_code == 404


def test_classroom_size_is_limited(client):
    response = client.post("/api/classes", json={"title": "Too big", "rows": 50, "cols": 50})
    assert response.status_code == 400


# ---------------------------------------------------------------- joining and seats


def test_socket_to_unknown_class_is_closed(client):
    with client.websocket_connect("/ws/NOPE22") as ws:
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    assert closed.value.code == main.CLOSE_NO_CLASS


def test_wrong_teacher_token_is_refused(client):
    room = open_class(client)
    with client.websocket_connect(f"/ws/{room['code']}") as ws:
        ws.send_json({"type": "hello", "role": "teacher", "token": "guess"})
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
        assert sit(asha, 4) == {"type": "you", "seat": 4}

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
        assert seats["seats"] == [{"seat": 0, "name": "Asha", "online": False, "lastRun": None}]


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
        assert seats["seats"][0] == {"seat": 0, "name": "Asha", "online": True, "lastRun": "error"}
        assert seats["lobby"] == []

        bikram.send_json({"type": "leave_seat"})
        assert next_of(bikram, "you")["seat"] is None
        for seat in next_of(bikram, "seats")["seats"]:
            assert "lastRun" not in seat


def test_students_cannot_use_teacher_messages(client):
    room = open_class(client)
    with student(client, room["code"], "Asha") as asha, student(client, room["code"], "Bikram") as bikram:
        sit(asha, 0)
        sit(bikram, 1)
        bikram.send_json({"type": "free_seat", "seat": 0})
        bikram.send_json({"type": "watch", "seat": 0})
        assert sit(bikram, 1)["seat"] == 1  # still served, and the messages above did nothing
        assert main.store.get(room["code"]).student_at(0).name == "Asha"


def test_teacher_can_free_a_seat(client):
    room = open_class(client)
    with teacher(client, room) as desk, student(client, room["code"], "Asha") as asha:
        sit(asha, 5)
        desk.send_json({"type": "free_seat", "seat": 5})
        assert next_of(asha, "you") == {"type": "you", "seat": None}
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


# ---------------------------------------------------------------- rules on their own


def test_old_classrooms_are_pruned():
    store = ClassroomStore()
    old = store.create("Old", 1, 1)
    fresh = store.create("Fresh", 1, 1)
    old.created_at = time.time() - ROOM_TTL_SECONDS - 1
    store.prune()
    assert store.get(old.code) is None
    assert store.get(fresh.code) is fresh


def test_long_code_is_refused():
    store = ClassroomStore()
    room = store.create("Class", 1, 1)
    asha = room.join(None, "Asha")
    with pytest.raises(RoomError):
        room.set_source(asha, "x" * 50_001)
    assert asha.source == ""
