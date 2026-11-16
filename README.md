# CodeSeat

A live classroom for Python and for web pages. Students take a seat on a map of the room and write
code beside the teacher's editor, which updates as the teacher types. The teacher
sees every seat at a glance and can open any seat to watch that student's code live.

Python runs in each student's own browser (Pyodide), and a web page runs in a
sandboxed frame there, so the server never executes anyone's code.

**Try it: https://codeseat.onrender.com** It runs on free hosting, which sleeps when
nobody is using it, so the first visit after a quiet spell takes about a minute to load.

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
- Ten ready-made first lessons (print, variables, input, numbers, if, elif, for,
  while, lists, functions) load into the lesson editor in one click and can be changed
  before saving. Each of their 38 steps is tested against a reference solution

Milestone 3, teacher accounts and saved classes, works locally:

- Teachers sign up with an email and a password; the session is a cookie
- A class belongs to its teacher and is kept in SQLite: its join code, lesson, seats
  and every student's code and passes survive a server restart
- The classes page lists a teacher's classes with their counts, makes new ones and
  deletes old ones
- Students still need only the code and a name

A class is made for Python or for web pages (HTML, with its CSS and JavaScript in
the same file). In a web class:

- The page shows itself beside the editor as it is typed, with what it writes to the
  console underneath. Errors name the student's own line
- The page runs in a sandboxed frame: it cannot reach CodeSeat, the login cookie or
  the browser's storage
- A lesson step passes when the console prints the expected lines or the page shows
  them, so both JavaScript and HTML can be set as steps. Styling cannot be checked;
  the teacher looks at it
- The teacher's page, and any student's, can be looked at as code or as the page it
  makes. In that view scripts are off, so someone else's endless loop or pop-ups
  cannot freeze the person looking
- Six ready-made lessons cover first pages, lists and links, CSS, first JavaScript,
  if and else, and changing the page from a script

Limits of web classes: one file per student, a page's own endless loop can still
freeze that student's tab (a reload brings the code back), and pictures or scripts
from other sites load only if those sites allow it.

The teacher also sees who needs help:

- A student can raise a hand. Hands queue up above the seat map in the order they
  went up, the seat fills with the signal colour, and the tab's title counts them
- A seat shows "Stuck" after three failed tries in a row (crashes, or checks that did
  not pass) and "Idle" after three minutes without typing, running or clicking
- The teacher can send a short hint to one seat. It appears above that student's
  editor until they put it away or the teacher takes it back
- Only the teacher sees any of this; classmates see who sits where and nothing more

The person who runs the site has an admin page at `/admin`:

- It lists every class (whose it is, how many students are in it right now, whether
  the teacher is at the desk) and every teacher account (name, email, when it was
  made, how many classes it has)
- A class can be ended, which sends everyone out and deletes it. An account can be
  blocked (its logins end at once and new ones are refused; its classes stay),
  given a new password, or deleted with all its classes
- A new account waits for the admin's approval. Until then its teacher can log in
  but cannot make a class; their page says so and changes by itself once the
  admin presses Approve. Accounts made before this existed, or on a site with
  no admin, need no approval. `CODESEAT_APPROVAL=off` lets everyone straight in
- Passwords cannot be shown: only a one-way hash of each is stored. Setting a new
  one is the way to help a teacher who has forgotten theirs
- The page is off until `CODESEAT_ADMIN_PASSWORD` is set to 12 characters or more

Limits keep a script from flooding the site:

- One address can make 5 accounts an hour, and the whole site 60
- An account can make 10 classes an hour and keep 20
- A class takes its seats plus 10 people at once, and forgets visitors who left
  without taking a seat or writing anything
- A connection that sends more than 150 messages in 10 seconds is closed

CodeSeat is also an installable web app: browsers that allow it show an "Install app"
button in the top bar, and the installed app opens to its own screen, with its icon
on the home screen or taskbar.

It is online at https://codeseat.onrender.com; "Putting it online" below says how.

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

### A full class

`backend/tools/loadtest.py` starts its own server with a temporary database, connects
a teacher and a room of students over real WebSockets, and lets them behave like a
lesson: typing, running, checking steps, raising hands. It measures how long the
server takes and checks that nothing was lost. It exits with 1 on any failure.

```bash
cd backend
.venv\Scripts\python tools\loadtest.py
```

The default is 30 students for 30 seconds. `--students 80` fills the biggest room,
`--seconds 100` runs longer, and `--url https://…` tests a server that is already
running. On a laptop, 80 students at once pass: the teacher's typing reaches a
student in about 13 ms, and a whole class is seated in under a second.

Against the live site, 30 students pass too: nothing lost, and a message takes about
105 ms from Nepal, which is the trip to the server in Singapore and back. With `--url`
the students arrive over five seconds; `--arrive-over 40` spreads them further, which
is needed on a computer whose antivirus scans secure connections and cannot open
many at once. Each run against a live site leaves one test teacher account behind.

## How it fits together

| Part | Where | What it does |
| --- | --- | --- |
| Classroom rules | `backend/app/rooms.py` | Seats, students, lesson steps, raised hands and what each role may see, with no web code |
| Accounts | `backend/app/accounts.py` | Password hashing (scrypt), session tokens, a brake on password guessing |
| Storage | `backend/app/storage.py` | SQLite or Postgres: teachers, sessions, and one JSON document per class |
| Website in production | `backend/app/site.py` | Serves the built pages from the server, with the isolation headers |
| Server | `backend/app/main.py` | REST for accounts and classes, one WebSocket per person in a class |
| Live connection | `frontend/src/lib/useClassroom.ts` | Mirrors the class state and reconnects when the link drops |
| Python runner | `frontend/public/py-worker.js` | Pyodide in a Web Worker, so an endless loop cannot freeze the page |
| Web page runner | `frontend/src/lib/useWebPage.ts` | A sandboxed frame with a listener in front of the page for its console, errors and text |
| Screens | `frontend/src/pages/` | Start page, student room, teacher room |

## Putting it online

In production one server does everything. The `Dockerfile` builds the website and
puts it beside the backend, which then serves the pages, the API and the class
sockets from a single address (`backend/app/site.py`).

Where the data lives depends on one setting:

- With `DATABASE_URL` set to a `postgres://` address, teachers and classes are kept
  in that Postgres database. Use this on any host whose disk does not survive a
  restart, which includes most free plans.
- Without it, they are kept in a SQLite file, as on your own computer.

`render.yaml` describes a free web service on [Render](https://render.com) built from
the Dockerfile. With a free Postgres database from [Neon](https://neon.com):

1. Create a Neon project and copy its connection string.
2. On Render choose New, then Blueprint, pick this repository, and paste the
   connection string as `DATABASE_URL` when asked.

Things to know about that setup:

- To switch on the admin page, add `CODESEAT_ADMIN_PASSWORD` in the service's
  Environment settings: a long password of your own, 12 characters or more.
  Changing it signs the admin out everywhere. From then on each new teacher
  account waits on that page for your approval before it can make classes.

- A free Render service sleeps after 15 minutes without visitors and takes about a
  minute to wake. Open the site before the lesson starts. A class in progress keeps
  it awake.
- Live classes are copied to the database two seconds after any change, so a
  restart loses at most the last two seconds of typing.
- The session cookie is marked `Secure` when the request arrives over HTTPS. The
  Dockerfile starts uvicorn with `--proxy-headers` so it knows that behind the
  host's proxy.
- `input()` needs the page to be cross-origin isolated. The server sends the two
  headers for that on every answer.

One limit to know in any setup: a step check is judged by the server, but from the
output the student's browser reports, since code never runs on the server. That
keeps a lesson honest in class; it is not proof against a student who edits what
their browser sends.
