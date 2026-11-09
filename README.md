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

Milestone 2, lesson steps, works locally:

- The teacher writes the lesson as numbered steps: a task, optional lines for
  `input()`, and the exact output a program must print
- Students see the steps beside their editor, open one and check it: their program
  runs with the step's input and the server compares what it printed
- A pass shows on the student's list, as a count on their seat on the teacher's map,
  and step by step when the teacher opens that seat
- The teacher can point the class at a step, marked "Now" on every screen

Milestone 3, teacher accounts and saved classes, works locally:

- Teachers sign up with an email and a password; the session is a cookie
- A class belongs to its teacher and is kept in SQLite: its join code, lesson, seats
  and every student's code and passes survive a server restart
- The classes page lists a teacher's classes with their counts, makes new ones and
  deletes old ones
- Students still need only the code and a name

CodeSeat is also an installable web app: browsers that allow it show an "Install app"
button in the top bar, and the installed app opens to its own screen, with its icon
on the home screen or taskbar.

Planned next: deployment.

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

Open http://127.0.0.1:5173. To try both roles on one computer, open the teacher's
class in one window and join it from a private window.

The server keeps teachers and their classes in `backend/data/codeseat.db`, which it
creates on first start. Set `CODESEAT_DATABASE` to put the file elsewhere.

The development server leaves the service worker out, so "Install app" does not
appear there. To try the installable build, run `npm run build` and then
`npm run preview` in `frontend/`, and open http://127.0.0.1:4173. The icons come
from `frontend/scripts/make-icons.py`, which draws them from the theme's colours.

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
| Classroom rules | `backend/app/rooms.py` | Seats, students, lesson steps and what each role may see, with no web code |
| Accounts | `backend/app/accounts.py` | Password hashing (scrypt), session tokens, a brake on password guessing |
| Storage | `backend/app/storage.py` | SQLite: teachers, sessions, and one JSON document per class |
| Server | `backend/app/main.py` | REST for accounts and classes, one WebSocket per person in a class |
| Live connection | `frontend/src/lib/useClassroom.ts` | Mirrors the class state and reconnects when the link drops |
| Python runner | `frontend/public/py-worker.js` | Pyodide in a Web Worker, so an endless loop cannot freeze the page |
| Screens | `frontend/src/pages/` | Start page, student room, teacher room |

Four things to know before deploying:

- Accounts and classes live in one SQLite file, so the server needs a disk that
  survives restarts and deploys. A host with an ephemeral filesystem would lose every
  account on each deploy.
- The session cookie is marked `Secure` only when the request arrives over HTTPS.
  Behind a proxy, run uvicorn with `--proxy-headers` so it knows the real scheme.
- `input()` needs the page to be cross-origin isolated. The dev server sends the two
  headers for that (see `frontend/vite.config.ts`); production hosting must send them too.
- A step check is judged by the server, but from the output the student's browser
  reports, since code never runs on the server. That keeps a lesson honest in class; it
  is not proof against a student who edits what their browser sends.
