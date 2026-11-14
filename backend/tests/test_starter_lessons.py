"""The ready-made lessons a teacher can load (frontend/src/data/starter-lessons.json).

Every step is proved solvable: a reference solution is run with the step's
input and must print exactly what the step expects, judged by the same rule
the server uses for a student's check. The solutions live here and not in the
lesson file, because the lesson file is sent to every browser.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

import pytest

from app.rooms import MAX_STEPS, Classroom, outputs_match

LESSONS = json.loads(
    (Path(__file__).resolve().parents[2] / "frontend" / "src" / "data" / "starter-lessons.json").read_text("utf-8")
)

GRADE = """
marks = int(input())
if marks >= 80:
    print("A")
elif marks >= 60:
    print("B")
elif marks >= 40:
    print("C")
else:
    print("F")
"""

PASS_OR_FAIL = """
marks = int(input())
if marks >= 40:
    print("Pass")
else:
    print("Fail")
"""

SQUARE = """
def square(n):
    return n * n
"""

# One working answer per step, in the order of the lesson file.
SOLUTIONS = {
    "print": [
        'print("Hello, world!")',
        'print("Python")\nprint("is fun")',
        "print(2 + 3)",
        'print("I am", 12, "years old")',
    ],
    "variables": [
        'name = "Asha"\nprint(name)',
        'name = "Asha"\nprint("Hello,", name)',
        "price = 40\ncount = 3\nprint(price * count)",
        "score = 10\nscore = score + 5\nprint(score)",
    ],
    "input": [
        "word = input()\nprint(word)",
        'name = input()\nprint("Hello, " + name + "!")',
        'city = input()\ncountry = input()\nprint(city + ", " + country)',
    ],
    "numbers": [
        "a = int(input())\nb = int(input())\nprint(a + b)",
        "width = int(input())\nheight = int(input())\nprint(width * height)",
        "a = int(input())\nb = int(input())\nc = int(input())\nprint((a + b + c) / 3)",
        "n = int(input())\nprint(n % 2)",
    ],
    "if-else": [
        PASS_OR_FAIL,
        PASS_OR_FAIL,
        'n = int(input())\nif n % 2 == 0:\n    print("Even")\nelse:\n    print("Odd")',
        "a = int(input())\nb = int(input())\nif a > b:\n    print(a)\nelse:\n    print(b)",
    ],
    "elif": [
        GRADE,
        GRADE,
        GRADE,
        'n = int(input())\nif n > 0:\n    print("Positive")\nelif n < 0:\n    print("Negative")\nelse:\n    print("Zero")',
    ],
    "for": [
        "for n in range(1, 6):\n    print(n)",
        "n = int(input())\nfor i in range(1, n + 1):\n    print(i)",
        'n = int(input())\nfor i in range(1, 6):\n    print(n, "x", i, "=", n * i)',
        "n = int(input())\ntotal = 0\nfor i in range(1, n + 1):\n    total = total + i\nprint(total)",
    ],
    "while": [
        'n = 5\nwhile n > 0:\n    print(n)\n    n = n - 1\nprint("Go!")',
        "n = int(input())\nwhile n > 0:\n    print(n)\n    n = n // 2",
        "total = 0\nn = int(input())\nwhile n != 0:\n    total = total + n\n    n = int(input())\nprint(total)",
    ],
    "lists": [
        'fruits = ["apple", "banana", "mango"]\nfor fruit in fruits:\n    print(fruit)',
        'fruits = ["apple", "banana", "mango"]\nprint(len(fruits))',
        'fruits = ["apple", "banana", "mango"]\nfruits.append("orange")\nprint(fruits[-1])\nprint(len(fruits))',
        "numbers = [4, 17, 9, 2]\nbiggest = numbers[0]\nfor n in numbers:\n    if n > biggest:\n        biggest = n\nprint(biggest)",
    ],
    "functions": [
        'def greet(name):\n    print("Hello, " + name + "!")\n\ngreet("Asha")\ngreet("Bikram")',
        SQUARE + "print(square(4))\nprint(square(9))",
        SQUARE + "print(square(int(input())))",
        "def is_even(n):\n    return n % 2 == 0\n\nprint(is_even(10))\nprint(is_even(7))",
    ],
}


def run(source: str, typed: str) -> str:
    """What the program prints when its input() calls are answered from `typed`, as a check does."""
    lines = typed.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    answers = iter(lines)

    def fake_input(prompt: str = "") -> str:
        print(prompt, end="")
        try:
            return next(answers)
        except StopIteration:
            raise EOFError("EOF when reading a line") from None

    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        exec(compile(source, "solution.py", "exec"), {"__name__": "__main__", "input": fake_input})
    return printed.getvalue()


STEPS = [
    pytest.param(lesson["id"], number, step, id=f"{lesson['id']}-{number + 1}")
    for lesson in LESSONS
    for number, step in enumerate(lesson["steps"])
]


def test_there_are_ten_lessons_with_a_solution_for_every_step():
    assert len(LESSONS) == 10
    assert len({lesson["id"] for lesson in LESSONS}) == 10
    assert len({lesson["title"] for lesson in LESSONS}) == 10
    for lesson in LESSONS:
        assert lesson["summary"].strip()
        assert 1 <= len(lesson["steps"]) <= MAX_STEPS
        assert len(SOLUTIONS[lesson["id"]]) == len(lesson["steps"]), lesson["id"]
    assert set(SOLUTIONS) == {lesson["id"] for lesson in LESSONS}


@pytest.mark.parametrize(("lesson_id", "number", "step"), STEPS)
def test_each_step_passes_with_its_reference_solution(lesson_id, number, step):
    printed = run(SOLUTIONS[lesson_id][number], step["input"])
    assert outputs_match(step["expectedOutput"], printed), printed


@pytest.mark.parametrize(("lesson_id", "number", "step"), STEPS)
def test_no_step_passes_for_a_program_that_prints_nothing(lesson_id, number, step):
    assert not outputs_match(step["expectedOutput"], "")


@pytest.mark.parametrize("lesson", LESSONS, ids=[lesson["id"] for lesson in LESSONS])
def test_each_lesson_is_accepted_by_the_classroom_rules(lesson):
    room = Classroom(code="ABCDEF", title="Intro", rows=1, cols=1, teacher_id="t1")
    room.set_steps(lesson["steps"])  # raises if a title, instruction or output breaks a limit
    assert [step.title for step in room.steps] == [step["title"] for step in lesson["steps"]]
    assert all(set(step) == {"title", "instructions", "input", "expectedOutput"} for step in lesson["steps"])
