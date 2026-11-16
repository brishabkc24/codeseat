"""The site's admin, and the limits that keep a script from flooding the site."""

from __future__ import annotations

import sqlite3
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import main
from app.accounts import (
    ADMIN_SESSION_SECONDS,
    LOGIN_ATTEMPTS,
    Throttle,
    admin_token,
    admin_token_valid,
    check_password,
)
from app.rooms import MAX_CLASSES_PER_TEACHER, SPARE_PLACES, RoomError
from app.storage import SqliteStorage
from test_classroom import TEACHER, bare_store, client, open_class, sign_up, sit, student, teacher  # noqa: F401

ADMIN_PASSWORD = "a long admin password"


@pytest.fixture
def admin(client):  # noqa: F811
    """The same browser, with the admin signed in."""
    main.ADMIN_PASSWORD = ADMIN_PASSWORD
    response = client.post("/api/admin/session", json={"password": ADMIN_PASSWORD})
    assert response.status_code == 200, response.text
    return client


def closed_with(ws):
    """Reads a socket until the server closes it; returns the close code."""
    with pytest.raises(WebSocketDisconnect) as closed:
        while True:
            ws.receive_json()
    return closed.value.code


def overview(admin):
    response = admin.get("/api/admin/overview")
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------- signing in


def test_the_admin_page_is_off_until_a_password_is_set(client):  # noqa: F811
    assert client.get("/api/admin/session").json() == {"configured": False, "admin": False}
    assert client.post("/api/admin/session", json={"password": ""}).status_code == 404
    assert client.get("/api/admin/overview").status_code == 401

    main.ADMIN_PASSWORD = "too short"  # a weak password leaves the page off
    assert client.get("/api/admin/session").json()["configured"] is False
    assert client.post("/api/admin/session", json={"password": "too short"}).status_code == 404


def test_the_admin_signs_in_and_out(client):  # noqa: F811
    main.ADMIN_PASSWORD = ADMIN_PASSWORD
    assert client.get("/api/admin/session").json() == {"configured": True, "admin": False}
    assert client.post("/api/admin/session", json={"password": "not the password"}).status_code == 401
    assert client.get("/api/admin/overview").status_code == 401

    signed_in = client.post("/api/admin/session", json={"password": ADMIN_PASSWORD})
    assert signed_in.status_code == 200
    assert "httponly" in signed_in.headers["set-cookie"].lower()
    assert client.get("/api/admin/session").json() == {"configured": True, "admin": True}
    assert client.get("/api/admin/overview").status_code == 200

    assert client.delete("/api/admin/session").status_code == 204
    assert client.get("/api/admin/overview").status_code == 401


def test_wrong_admin_passwords_are_braked(client):  # noqa: F811
    main.ADMIN_PASSWORD = ADMIN_PASSWORD
    for _ in range(LOGIN_ATTEMPTS):
        assert client.post("/api/admin/session", json={"password": "a wrong guess"}).status_code == 401
    assert client.post("/api/admin/session", json={"password": ADMIN_PASSWORD}).status_code == 429


def test_a_teacher_is_not_the_admin(client):  # noqa: F811
    main.ADMIN_PASSWORD = ADMIN_PASSWORD
    room = open_class(client)  # signed in as a teacher, not as the admin
    listed = main.store.storage.all_teachers()
    assert client.get("/api/admin/overview").status_code == 401
    assert client.delete(f"/api/admin/classes/{room['code']}").status_code == 401
    assert client.post(f"/api/admin/teachers/{listed[0].id}/block", json={"blocked": True}).status_code == 401
    assert client.post(f"/api/admin/teachers/{listed[0].id}/password", json={"password": "x" * 12}).status_code == 401
    assert client.delete(f"/api/admin/teachers/{listed[0].id}").status_code == 401
    assert main.store.get(room["code"]) is not None


def test_admin_pass_rules():
    token = admin_token("the admin password", now=1000)
    assert admin_token_valid(token, "the admin password", now=1000 + ADMIN_SESSION_SECONDS - 1)
    assert not admin_token_valid(token, "the admin password", now=1000 + ADMIN_SESSION_SECONDS)  # it has run out
    assert not admin_token_valid(token, "another password", now=1000)  # a new password ends old passes
    expires, mark = token.split(".")
    assert not admin_token_valid(f"{int(expires) + 60}.{mark}", "the admin password", now=1000)  # a stretched expiry
    for junk in (None, "", "nonsense", "1.2.3", f"{expires}."):
        assert not admin_token_valid(junk, "the admin password", now=1000)


# ---------------------------------------------------------------- what the admin sees and does


def test_the_admin_sees_every_teacher_and_class(admin):
    room = open_class(admin, language="web")
    data = overview(admin)
    assert len(data["teachers"]) == 1
    listed = data["teachers"][0]
    assert (listed["name"], listed["email"], listed["blocked"], listed["classes"]) == ("Ms Rai", TEACHER["email"], False, 1)
    assert "password" not in " ".join(listed).lower()  # passwords are hashes; none of that leaves the server
    assert data["classes"][0] == {
        "code": room["code"],
        "title": "Intro to Python",
        "rows": 2,
        "cols": 3,
        "language": "web",
        "students": 0,
        "steps": 0,
        "createdAt": data["classes"][0]["createdAt"],
        "updatedAt": data["classes"][0]["updatedAt"],
        "teacherId": listed["id"],
        "teacherName": "Ms Rai",
        "online": 0,
        "teacherHere": False,
    }

    with teacher(admin, room), student(admin, room["code"], "Asha"), student(admin, room["code"], "Bikram"):
        running = overview(admin)["classes"][0]
        assert (running["online"], running["teacherHere"], running["students"]) == (2, True, 2)


def test_the_admin_ends_a_class(admin):
    room = open_class(admin)
    with student(admin, room["code"], "Asha") as asha:
        sit(asha, 0)
        assert admin.delete(f"/api/admin/classes/{room['code']}").status_code == 204
        assert closed_with(asha) == main.CLOSE_NO_CLASS
    assert admin.get(f"/api/classes/{room['code']}").status_code == 404
    assert overview(admin)["classes"] == []
    assert admin.delete(f"/api/admin/classes/{room['code']}").status_code == 404


def test_a_blocked_teacher_is_shut_out_until_unblocked(admin):
    room = open_class(admin)
    teacher_id = overview(admin)["teachers"][0]["id"]
    login = {"email": TEACHER["email"], "password": TEACHER["password"]}

    with teacher(admin, room) as desk:
        assert admin.post(f"/api/admin/teachers/{teacher_id}/block", json={"blocked": True}).json() == {"blocked": True}
        assert closed_with(desk) == main.CLOSE_NOT_TEACHER
    assert overview(admin)["teachers"][0]["blocked"] is True
    assert admin.get("/api/session").json()["teacher"] is None  # the open session is gone
    assert admin.post("/api/classes", json={"title": "More", "rows": 1, "cols": 1}).status_code == 401
    refused = admin.post("/api/session", json=login)
    assert refused.status_code == 403
    assert refused.json()["detail"].startswith("This account has been blocked.")
    assert admin.get(f"/api/classes/{room['code']}").status_code == 200  # the class and its work stay

    assert admin.post(f"/api/admin/teachers/{teacher_id}/block", json={"blocked": False}).json() == {"blocked": False}
    assert admin.post("/api/session", json=login).status_code == 200
    assert admin.post("/api/admin/teachers/nobody/block", json={"blocked": True}).status_code == 404


def test_the_admin_gives_an_account_a_new_password(admin):
    sign_up(admin)
    teacher_id = overview(admin)["teachers"][0]["id"]
    assert admin.post(f"/api/admin/teachers/{teacher_id}/password", json={"password": "short"}).status_code == 400
    assert admin.post(f"/api/admin/teachers/{teacher_id}/password", json={"password": "a brand new password"}).status_code == 204
    assert admin.get("/api/session").json()["teacher"] is None  # signed out everywhere
    assert check_password("a brand new password", main.store.storage.teacher_by_id(teacher_id).password_hash)
    assert admin.post("/api/session", json={"email": TEACHER["email"], "password": TEACHER["password"]}).status_code == 401
    assert admin.post("/api/session", json={"email": TEACHER["email"], "password": "a brand new password"}).status_code == 200
    assert admin.post("/api/admin/teachers/nobody/password", json={"password": "a brand new password"}).status_code == 404


def test_the_admin_deletes_an_account_and_its_classes(admin):
    room = open_class(admin)
    other = open_class(admin, rows=1, cols=1)
    teacher_id = overview(admin)["teachers"][0]["id"]
    with student(admin, room["code"], "Asha") as asha:
        assert admin.delete(f"/api/admin/teachers/{teacher_id}").status_code == 204
        assert closed_with(asha) == main.CLOSE_NO_CLASS
    assert overview(admin) == {"teachers": [], "classes": []}
    assert admin.get(f"/api/classes/{other['code']}").status_code == 404
    assert admin.get("/api/session").json()["teacher"] is None
    assert admin.delete(f"/api/admin/teachers/{teacher_id}").status_code == 404
    sign_up(admin)  # the email is free again


# ---------------------------------------------------------------- limits


def test_one_address_can_make_only_a_few_accounts_an_hour(client):  # noqa: F811
    for number in range(main.SIGNUPS_PER_ADDRESS):
        sign_up(client, email=f"teacher{number}@example.com")
    refused = client.post("/api/teachers", json={**TEACHER, "email": "one-more@example.com"})
    assert refused.status_code == 429
    assert main.store.storage.teacher_by_email("one-more@example.com") is None
    # A sign-up that would fail anyway does not use up a place.
    main.signups_from_one_address = Throttle(1, 3600)
    assert client.post("/api/teachers", json={**TEACHER, "email": "not an email"}).status_code == 400
    sign_up(client, email="still-room@example.com")


def test_the_whole_site_takes_only_so_many_accounts_an_hour(client):  # noqa: F811
    main.signups_in_all = Throttle(2, 3600)
    main.signups_from_one_address = Throttle(100, 3600)
    sign_up(client, email="a@example.com")
    sign_up(client, email="b@example.com")
    assert client.post("/api/teachers", json={**TEACHER, "email": "c@example.com"}).status_code == 429


def test_a_teacher_can_open_only_so_many_classes_an_hour(client):  # noqa: F811
    for _ in range(main.NEW_CLASSES_PER_TEACHER):
        open_class(client, rows=1, cols=1)
    refused = client.post("/api/classes", json={"title": "One more", "rows": 1, "cols": 1})
    assert refused.status_code == 429
    assert len(client.get("/api/classes").json()["classes"]) == main.NEW_CLASSES_PER_TEACHER


def test_an_account_keeps_only_so_many_classes():
    store = bare_store()
    for number in range(MAX_CLASSES_PER_TEACHER):
        store.create("t1", f"Class {number}", 1, 1)
    with pytest.raises(RoomError, match="Delete one to make another"):
        store.create("t1", "One too many", 1, 1)
    store.delete(store.summaries_for("t1")[0]["code"])
    store.create("t1", "Room again", 1, 1)


def test_a_class_takes_only_so_many_people_at_once():
    room = bare_store().create("t1", "Small", 1, 2)
    for number in range(room.seat_count + SPARE_PLACES):
        room.join(None, f"Student {number}").online = True
    with pytest.raises(RoomError, match="This class is full"):
        room.join(None, "One too many")
    room.students[next(iter(room.students))].online = False  # someone leaves
    room.join(None, "Room now")


def test_visitors_who_left_nothing_behind_are_forgotten():
    room = bare_store().create("t1", "Small", 1, 2)
    asha = room.join(None, "Asha")
    asha.online = True
    room.take_seat(asha, 0)
    for number in range(30):  # a script joining and leaving
        room.join(None, f"Bot {number}")
    assert len(room.students) <= 2  # Asha and the latest arrival
    assert room.student_at(0) is asha

    # Someone with work to come back to is kept, seat or no seat.
    bikram = room.join(None, "Bikram")
    bikram.online = True
    room.set_source(bikram, "print('mine')")
    bikram.online = False
    room.join(None, "Chandra")
    assert room.join(bikram.id, "Bikram") is bikram


def test_a_socket_that_floods_is_closed(client):  # noqa: F811
    room = open_class(client)
    with student(client, room["code"], "Asha") as asha:
        sit(asha, 0)
        with pytest.raises(WebSocketDisconnect) as closed:
            for _ in range(main.MESSAGES_PER_WINDOW + 5):
                asha.send_json({"type": "source", "text": "x"})
            while True:
                asha.receive_json()
        assert closed.value.code == main.CLOSE_TOO_FAST
    # Ordinary typing is nowhere near the limit.
    with student(client, room["code"], "Bikram") as bikram:
        for _ in range(40):
            bikram.send_json({"type": "source", "text": "y"})
        assert sit(bikram, 1)["seat"] == 1


def test_throttle_rules():
    throttle = Throttle(2, 60)
    assert throttle.allow("a", now=1000) and throttle.allow("a", now=1001)
    assert not throttle.allow("a", now=1002)
    assert throttle.allow("b", now=1002)  # each key has its own count
    assert not throttle.allow("a", now=1059)  # a refusal is not counted, but the first two still stand
    assert throttle.allow("a", now=1061)  # the first has aged out


# ---------------------------------------------------------------- an older database


def test_a_database_from_before_blocking_gains_the_column(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute(
        "CREATE TABLE teachers (id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,"
        " password_hash TEXT NOT NULL, created_at REAL NOT NULL)"
    )
    old.execute("INSERT INTO teachers VALUES ('t1', 'Ms Rai', 'rai@example.com', '-', ?)", (time.time(),))
    old.commit()
    old.close()

    storage = SqliteStorage(path)
    assert storage.teacher_by_id("t1").blocked is False
    assert storage.set_blocked("t1", True)
    storage.close()
    assert SqliteStorage(path).teacher_by_id("t1").blocked is True  # opening it again changes nothing
