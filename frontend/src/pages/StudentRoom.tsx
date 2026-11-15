import { useEffect, useMemo, useRef, useState } from "react";
import { Navigate, useLocation, useParams } from "react-router-dom";
import { CodeEditor } from "../components/CodeEditor";
import { PagePanel, PagePreview } from "../components/PagePanel";
import { RoomClosed, RoomLoading } from "../components/RoomStates";
import { RunPanel } from "../components/RunPanel";
import { SeatMap } from "../components/SeatMap";
import { StepsPane, type Verdict } from "../components/StepsPane";
import { TopBar } from "../components/TopBar";
import { type StudentIdentity, loadStudent, saveStudent } from "../lib/api";
import { type Hello, type RunResult, type Step, seatLabel } from "../lib/protocol";
import { type Classroom, useClassroom } from "../lib/useClassroom";
import { type OutputChunk, usePython } from "../lib/usePython";
import { useWebPage } from "../lib/useWebPage";
import { useThrottledSend } from "../lib/useThrottledSend";

export function StudentRoom() {
  const code = (useParams().code ?? "").toUpperCase();
  const location = useLocation();
  const [identity] = useState<StudentIdentity | null>(() => {
    const saved = loadStudent(code);
    if (saved) return saved;
    // Storage can be blocked; the join form also hands the name over directly.
    const name = (location.state as { name?: string } | null)?.name;
    return name ? { name, id: null } : null;
  });

  if (!identity) return <Navigate to={`/join/${code}`} replace />;
  return <StudentDesk code={code} identity={identity} />;
}

/** What the student's own check run printed, kept to explain the server's verdict. */
type CheckRun = { step: string; result: RunResult; output: string; page: string };

/** What a program printed, without its error text or CodeSeat's own notes. */
function printed(chunks: OutputChunk[]): string {
  return chunks
    .filter((chunk) => chunk.stream === "stdout")
    .map((chunk) => chunk.text)
    .join("");
}

function StudentDesk({ code, identity }: { code: string; identity: StudentIdentity }) {
  const hello = useMemo<Hello>(
    () => ({ role: "student", name: identity.name, studentId: identity.id }),
    [identity],
  );
  const { classroom, send, dismissNotice } = useClassroom(code, hello);
  const { room, you, steps } = classroom;

  const [source, setSource] = useState("");
  const sourceRef = useRef(source);
  sourceRef.current = source;
  const [adopted, setAdopted] = useState(false);
  const [choosing, setChoosing] = useState(false);

  // On the first connection the server's copy of my code wins (it survives a
  // reload). On a reconnection mine wins, since I may have typed while offline.
  useEffect(() => {
    if (classroom.joins === 0 || !classroom.you) return;
    if (!adopted) {
      setSource(classroom.you.source);
      setAdopted(true);
    } else {
      send({ type: "source", text: sourceRef.current });
    }
    // Runs once per (re)connection, not on every change of the values it reads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [classroom.joins]);

  useThrottledSend(source, adopted, (text) => send({ type: "source", text }));

  // Remember who I am in this class, so a reload returns me to my seat.
  const myId = you?.id;
  const myName = you?.name;
  useEffect(() => {
    if (myId && myName) saveStudent(code, { name: myName, id: myId });
  }, [code, myId, myName]);

  const mySeat = you?.seat ?? null;
  useEffect(() => {
    setChoosing(false);
  }, [mySeat]);

  // A check is a run with the step's input; the server judges what it printed.
  const [checking, setChecking] = useState<Step | null>(null);
  const checkingRef = useRef<Step | null>(null);
  const [checkRun, setCheckRun] = useState<CheckRun | null>(null);
  /** A run has ended: tell the server, as a check if it was made for a step. */
  const report = (result: RunResult, output: string, page: string | null) => {
    const step = checkingRef.current;
    checkingRef.current = null;
    setChecking(null);
    if (!step) {
      send({ type: "run", status: result });
      return;
    }
    setCheckRun({ step: step.id, result, output, page: page ?? "" });
    send({ type: "check", step: step.id, status: result, output, ...(page === null ? {} : { page }) });
  };

  // The class writes Python or web pages. Both runners are named here, but the
  // Python one starts only in a Python class, and the web one costs nothing idle.
  const isWeb = room?.language === "web";
  const python = usePython((result, chunks) => report(result, printed(chunks), null), room?.language === "python");
  const web = useWebPage((finish) => {
    if (finish.mode !== "preview") report(finish.result, printed(finish.output), finish.page);
  });
  const startPage = web.start;

  const runNow = () => (isWeb ? startPage(sourceRef.current, "run") : python.run(sourceRef.current));
  const checkStep = (step: Step) => {
    // Stay on this step afterwards, so its verdict is seen; a pass must not skip ahead unread.
    setPicked(step.id);
    checkingRef.current = step;
    setChecking(step);
    if (isWeb) startPage(sourceRef.current, "check", step.input);
    else python.run(sourceRef.current, { stdin: step.input });
  };
  const stopNow = () => {
    checkingRef.current = null;
    setChecking(null);
    python.stop();
  };

  // A web page shows itself as it is typed, a moment after the typing stops.
  // These previews are quiet: pop-ups are off and the teacher is not told.
  const seated = (you?.seat ?? null) !== null;
  useEffect(() => {
    if (!isWeb || !adopted || !seated) return;
    const timer = window.setTimeout(() => {
      if (checkingRef.current === null) startPage(source, "preview");
    }, 600);
    return () => window.clearTimeout(timer);
  }, [isWeb, adopted, seated, source, startPage]);

  // In a web class the teacher's code can be looked at as code or as the page it makes.
  const [teacherView, setTeacherView] = useState<"code" | "page">("code");

  // Which step is open: the one I picked, else where the teacher points, else my next one.
  const [picked, setPicked] = useState<string | null>(null);
  const selected = chooseStep(steps, picked, classroom);
  const verdict = verdictFor(selected, classroom, checkRun);

  if (classroom.phase === "closed" && classroom.closeReason) {
    return <RoomClosed reason={classroom.closeReason} detail={classroom.closeDetail} code={code} />;
  }
  if (!room || !you) return <RoomLoading />;

  if (mySeat === null || choosing) {
    const full = mySeat === null && classroom.seats.length >= room.rows * room.cols;
    return (
      <>
        <TopBar classroom={classroom}>
          <span className="bar__who">{you.name}</span>
        </TopBar>
        <main className="picker">
          <div className="picker__head">
            <div>
              <h2 className="picker__title">Pick your seat</h2>
              <p className="lead">
                {full
                  ? "Every seat is taken. Ask your teacher to free one."
                  : "Free seats are outlined. Click one to sit down."}
              </p>
            </div>
            {mySeat !== null && (
              <button type="button" className="btn" onClick={() => setChoosing(false)}>
                Back to my code
              </button>
            )}
          </div>
          {classroom.notice && (
            <p className="notice" role="alert">
              {classroom.notice}
            </p>
          )}
          <SeatMap
            rows={room.rows}
            cols={room.cols}
            seats={classroom.seats}
            mode="pick"
            current={mySeat}
            onSelect={(seat) => {
              dismissNotice();
              if (seat === mySeat) setChoosing(false);
              else send({ type: "take_seat", seat });
            }}
          />
        </main>
      </>
    );
  }

  const teacherPane = (
    <section className="pane" aria-label="Teacher’s code">
      <div className="pane__head">
        <h2 className="pane__title">Teacher’s code</h2>
        <div className="pane__tools">
          <span className={classroom.phase === "open" ? "status status--live" : "status"} role="status">
            {classroom.phase === "open" ? "Live" : "Paused"}
          </span>
          {isWeb && (
            <button
              type="button"
              className="btn"
              onClick={() => setTeacherView(teacherView === "code" ? "page" : "code")}
            >
              {teacherView === "code" ? "Show page" : "Show code"}
            </button>
          )}
        </div>
      </div>
      <div className="pane__body">
        {isWeb && teacherView === "page" ? (
          <PagePreview source={classroom.teacherSource} title="Teacher’s page" />
        ) : (
          <CodeEditor
            value={classroom.teacherSource}
            label="Teacher’s code, read only"
            readOnly
            placeholder="Your teacher has not typed anything yet."
            language={room.language}
          />
        )}
      </div>
    </section>
  );

  return (
    <>
      <TopBar classroom={classroom}>
        <span className="bar__who">
          {you.name}, seat <span className="mono">{seatLabel(mySeat, room.cols)}</span>
        </span>
        <button type="button" className="btn" onClick={() => setChoosing(true)}>
          Change seat
        </button>
      </TopBar>
      <main className="work">
        {selected ? (
          <div className="column">
            <StepsPane
              steps={steps}
              currentStep={classroom.currentStep}
              passed={you.passed}
              selected={selected}
              onSelect={setPicked}
              onCheck={checkStep}
              checking={checking?.id ?? null}
              canCheck={isWeb || python.phase === "ready"}
              verdict={verdict}
              language={room.language}
            />
            {teacherPane}
          </div>
        ) : (
          teacherPane
        )}

        <section className="pane pane--split" aria-label="Your code">
          <div className="pane__head">
            <h2 className="pane__title">Your code</h2>
            <div className="pane__tools">
              <span className={you.hand ? "status status--warn" : "pane__note pane__note--extra"} role="status">
                {you.hand ? "Hand up" : "Your teacher can see this"}
              </span>
              <button
                type="button"
                className="btn"
                aria-pressed={you.hand}
                disabled={classroom.phase !== "open"}
                onClick={() => send({ type: "hand", up: !you.hand })}
              >
                {you.hand ? "Lower hand" : "Raise hand"}
              </button>
            </div>
          </div>
          <div className="pane__body pane__body--stack">
            {you.hint && (
              <aside className="hint" role="status" aria-label="A hint from your teacher">
                <p className="hint__text">
                  <span className="hint__from">Your teacher: </span>
                  {you.hint}
                </p>
                <button type="button" className="btn" onClick={() => send({ type: "dismiss_hint" })}>
                  Got it
                </button>
              </aside>
            )}
            <CodeEditor
              value={source}
              onChange={setSource}
              label="Your code"
              onRun={runNow}
              placeholder={isWeb ? "Type your HTML here. CSS goes in <style>, JavaScript in <script>." : "Type your Python here."}
              language={room.language}
            />
          </div>
          {isWeb ? <PagePanel web={web} onRun={runNow} /> : <RunPanel python={{ ...python, stop: stopNow }} onRun={runNow} />}
        </section>
      </main>
    </>
  );
}

function chooseStep(steps: Step[], picked: string | null, classroom: Classroom): Step | null {
  if (steps.length === 0) return null;
  const passed = classroom.you?.passed ?? [];
  return (
    steps.find((step) => step.id === picked) ??
    steps.find((step) => step.id === classroom.currentStep) ??
    steps.find((step) => !passed.includes(step.id)) ??
    steps[0]
  );
}

/** The verdict to show for the open step: the server's answer to my latest check of it. */
function verdictFor(selected: Step | null, classroom: Classroom, checkRun: CheckRun | null): Verdict | null {
  const answer = classroom.lastCheck;
  if (!selected || !answer || answer.step !== selected.id) return null;
  const run = checkRun?.step === selected.id ? checkRun : null;
  return { passed: answer.passed, result: run?.result ?? "ok", output: run?.output ?? "", page: run?.page ?? "" };
}
