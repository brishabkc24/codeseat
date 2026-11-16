"""The database layer, on SQLite always and on Postgres when one is offered.

To include Postgres, set CODESEAT_TEST_POSTGRES to the address of a database
that may be emptied, for example postgresql://postgres@127.0.0.1:5432/postgres.
"""

from __future__ import annotations

import os

import pytest

from app.rooms import Classroom, ClassroomStore
from app.storage import ClassRecord, EmailTaken, PostgresStorage, SqliteStorage, TeacherRecord, open_storage

POSTGRES = os.environ.get("CODESEAT_TEST_POSTGRES")
BACKENDS = ["sqlite", pytest.param("postgres", marks=pytest.mark.skipif(not POSTGRES, reason="no test Postgres offered"))]


@pytest.fixture(params=BACKENDS)
def storage(request):
    if request.param == "sqlite":
        made = SqliteStorage(":memory:")
    else:
        made = PostgresStorage(POSTGRES)
        for table in ("classes", "sessions", "teachers"):
            made._change(f"DELETE FROM {table}")
    yield made
    made.close()


def teacher(number=1):
    return TeacherRecord(id=f"t{number}", name="Ms Rai", email=f"rai{number}@example.com", password_hash="-", created_at=1700000000.25)


def test_teachers_are_found_by_email_and_by_id(storage):
    storage.add_teacher(teacher())
    assert storage.teacher_by_email("rai1@example.com") == teacher()
    assert storage.teacher_by_id("t1") == teacher()
    assert storage.teacher_by_email("nobody@example.com") is None
    assert storage.teacher_by_id("t9") is None


def test_an_email_can_belong_to_one_teacher_only(storage):
    storage.add_teacher(teacher())
    twin = teacher()
    twin.id = "t2"
    with pytest.raises(EmailTaken):
        storage.add_teacher(twin)
    assert storage.teacher_by_id("t2") is None


def test_a_session_names_its_teacher_until_it_expires_or_is_deleted(storage):
    storage.add_teacher(teacher())
    storage.add_session("hash-a", "t1", created_at=100.0, expires_at=200.0)
    storage.add_session("hash-b", "t1", created_at=100.0, expires_at=300.0)
    assert storage.teacher_for_session("hash-a", now=150.0) == teacher()
    assert storage.teacher_for_session("hash-a", now=200.0) is None  # expired
    assert storage.teacher_for_session("unknown", now=150.0) is None

    storage.delete_expired_sessions(now=250.0)
    assert storage.teacher_for_session("hash-a", now=150.0) is None
    assert storage.teacher_for_session("hash-b", now=250.0) == teacher()
    storage.delete_session("hash-b")
    assert storage.teacher_for_session("hash-b", now=250.0) is None


def test_a_class_is_saved_updated_listed_and_deleted(storage):
    storage.add_teacher(teacher(1))
    storage.add_teacher(teacher(2))
    first = ClassRecord("ABCDEF", "t1", "Intro", 2, 3, created_at=10.5, updated_at=10.5, state={"steps": [], "note": "नमस्ते ’quoted’ 100%?"})
    later = ClassRecord("GHJKMN", "t1", "Second", 8, 10, created_at=20.0, updated_at=20.0, state={})
    other = ClassRecord("PQRSTU", "t2", "Theirs", 1, 1, created_at=30.0, updated_at=30.0, state={})
    for record in (first, later, other):
        storage.save_class(record)

    assert storage.load_class("ABCDEF") == first  # text survives as written, percent signs and question marks too
    assert storage.class_exists("ABCDEF") and not storage.class_exists("ZZZZZZ")
    assert [record.code for record in storage.classes_for_teacher("t1")] == ["GHJKMN", "ABCDEF"]  # newest first
    assert storage.classes_for_teacher("t9") == []

    first.title, first.updated_at, first.state = "Intro, renamed", 99.0, {"steps": [{"id": "s1"}]}
    storage.save_class(first)  # saving again replaces, it does not add
    assert storage.load_class("ABCDEF") == first
    assert len(storage.classes_for_teacher("t1")) == 2

    assert storage.delete_class("ABCDEF") is True
    assert storage.delete_class("ABCDEF") is False
    assert storage.load_class("ABCDEF") is None


def test_the_admin_lists_blocks_and_removes_accounts(storage):
    older, newer = teacher(1), teacher(2)
    newer.created_at += 60
    storage.add_teacher(older)
    storage.add_teacher(newer)
    storage.save_class(ClassRecord("ABCDEF", "t1", "Intro", 2, 3, created_at=10.0, updated_at=50.0, state={}))
    storage.save_class(ClassRecord("GHJKMN", "t1", "Second", 2, 3, created_at=20.0, updated_at=20.0, state={}))
    storage.save_class(ClassRecord("PQRSTU", "t2", "Theirs", 1, 1, created_at=30.0, updated_at=30.0, state={}))
    assert [record.id for record in storage.all_teachers()] == ["t2", "t1"]  # newest first
    assert [record.code for record in storage.all_classes()] == ["ABCDEF", "PQRSTU", "GHJKMN"]  # latest change first
    assert (storage.count_classes("t1"), storage.count_classes("t2"), storage.count_classes("t9")) == (2, 1, 0)

    # Blocking ends the account's logins and keeps new ones from working.
    storage.add_session("hash-a", "t1", created_at=100.0, expires_at=200.0)
    storage.add_session("hash-b", "t2", created_at=100.0, expires_at=200.0)
    assert storage.set_blocked("t1", True) is True
    assert storage.teacher_by_id("t1").blocked is True
    assert storage.teacher_for_session("hash-a", now=150.0) is None
    storage.add_session("hash-c", "t1", created_at=100.0, expires_at=200.0)
    assert storage.teacher_for_session("hash-c", now=150.0) is None
    assert storage.teacher_for_session("hash-b", now=150.0) == newer  # nobody else is touched
    assert storage.set_blocked("t1", False) is True
    assert storage.teacher_for_session("hash-c", now=150.0) == older
    assert storage.set_blocked("t9", True) is False

    # A waiting account is stored as waiting, and approving it sticks.
    waiting = teacher(3)
    waiting.approved = False
    storage.add_teacher(waiting)
    assert storage.teacher_by_id("t3").approved is False
    assert storage.teacher_by_id("t1").approved is True
    assert storage.set_approved("t3", True) is True
    assert storage.teacher_by_id("t3").approved is True
    assert storage.set_approved("t9", True) is False
    assert storage.delete_teacher("t3") is True

    # A new password signs the account out everywhere.
    assert storage.set_password("t1", "new-hash") is True
    assert storage.teacher_by_id("t1").password_hash == "new-hash"
    assert storage.teacher_for_session("hash-c", now=150.0) is None
    assert storage.set_password("t9", "new-hash") is False

    # Deleting an account takes its logins and classes with it, and frees the email.
    assert storage.delete_teacher("t1") is True
    assert storage.delete_teacher("t1") is False
    assert storage.teacher_by_id("t1") is None
    assert [record.code for record in storage.all_classes()] == ["PQRSTU"]
    storage.add_teacher(older)


def test_a_classroom_goes_through_storage_and_back(storage):
    storage.add_teacher(teacher())
    store = ClassroomStore(storage)
    room = store.create("t1", "Intro", 2, 3)
    asha = room.join(None, "Asha")
    room.take_seat(asha, 4)
    room.set_source(asha, "print('hi')")
    room.set_hand(asha, True)
    room.set_hint(asha, "Mind the colon.")
    assert store.flush() == 1 and store.flush() == 0

    again = Classroom.from_record(storage.load_class(room.code))
    back = again.students[asha.id]
    assert (back.name, back.seat, back.source, back.hand, back.hint) == ("Asha", 4, "print('hi')", 1, "Mind the colon.")


def test_a_late_save_cannot_bring_back_a_deleted_class(storage):
    storage.add_teacher(teacher())
    store = ClassroomStore(storage)
    room = store.create("t1", "Intro", 1, 1)
    room.set_teacher_source("x = 1")
    waiting = store.take_changed()  # the copy is taken...
    store.delete(room.code)  # ...the teacher deletes the class...
    store.write(waiting)  # ...and only then is the copy written
    assert storage.load_class(room.code) is None


def test_a_failed_save_is_tried_again(storage):
    storage.add_teacher(teacher())
    store = ClassroomStore(storage)
    room = store.create("t1", "Intro", 1, 1)
    room.set_teacher_source("x = 1")
    real, calls = storage.save_class, []

    def broken(record):
        calls.append(record.code)
        raise RuntimeError("the database is away")

    storage.save_class = broken
    with pytest.raises(RuntimeError):
        store.flush()
    assert room.dirty is True  # still counts as changed
    storage.save_class = real
    assert store.flush() == 1
    assert storage.load_class(room.code).state["teacherSource"] == "x = 1"


def test_the_address_decides_the_database(tmp_path):
    made = open_storage(tmp_path / "nested" / "codeseat.db")
    assert isinstance(made, SqliteStorage) and (tmp_path / "nested" / "codeseat.db").is_file()
    made.close()
