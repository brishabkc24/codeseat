# CodeSeat

A live classroom for Python. Students take a seat on a map of the room and write
code beside the teacher's editor, which updates as the teacher types. The teacher
sees every seat at a glance and can open any seat to watch that student's code live.

Python runs in each student's own browser (Pyodide), so the server never executes
anyone's code.

## Status

Milestone 1, the live classroom core, works locally:

- Start a class and get a six-character join code
- Join with the code and a name, then pick a free seat
- Teacher's editor mirrored live, read-only, on every student's screen
- Each student's own editor with Run, Stop, `input()` and Python tracebacks
- Teacher's seat map with each student's last run result, and a live view of any seat
- A reload or a dropped connection returns you to your seat with your code

Planned next: lesson steps with expected-output checks, teacher accounts and saved
classes, deployment.

## Run it

You need Python 3.11 or newer and Node.js 20 or newer.

Backend, from `backend/`:

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m uvicorn app.main:app --port 8020
```

Frontend, from `frontend/` in a second terminal:

```bash
npm install
npm run dev
```

Open http://127.0.0.1:5173. To try both roles on one computer, start a class in one
window and join it from a private window.

## Tests

```bash
cd backend
.venv\Scripts\python -m pytest
```

```bash
cd frontend
npm run typecheck
```

## How it fits together

| Part | Where | What it does |
| --- | --- | --- |
| Classroom rules | `backend/app/rooms.py` | Seats, students and what each role may see, with no web code |
| Server | `backend/app/main.py` | REST to open a class, one WebSocket per person in it |
| Live connection | `frontend/src/lib/useClassroom.ts` | Mirrors the class state and reconnects when the link drops |
| Python runner | `frontend/public/py-worker.js` | Pyodide in a Web Worker, so an endless loop cannot freeze the page |
| Screens | `frontend/src/pages/` | Start page, student room, teacher room |

Two things to know before deploying:

- Classes live in the server's memory. Restarting the server ends every class.
- `input()` needs the page to be cross-origin isolated. The dev server sends the two
  headers for that (see `frontend/vite.config.ts`); production hosting must send them too.
