import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { CodeEditor } from "../components/CodeEditor";
import { LessonEditor, type StepDraft } from "../components/LessonEditor";
import { PagePanel, PagePreview } from "../components/PagePanel";
import { RoomClosed, RoomLoading } from "../components/RoomStates";
import { RunPanel } from "../components/RunPanel";
import { SeatMap } from "../components/SeatMap";
import { TopBar } from "../components/TopBar";
import { classes } from "../lib/lesson";
import { type Hello, seatLabel } from "../lib/protocol";
import { helpQueue, seatWords } from "../lib/seats";
import { useSession } from "../lib/session";
import { useClassroom } from "../lib/useClassroom";
import { usePython } from "../lib/usePython";
import { useWebPage } from "../lib/useWebPage";
import { useThrottledSend } from "../lib/useThrottledSend";

export function TeacherRoom() {
  const code = (useParams().code ?? "").toUpperCase();
  const session = useSession();

  if (!session.known) return <RoomLoading />;
  if (!session.teacher) return <RoomClosed reason="not-teacher" code={code} />;
  return <TeacherDesk code={code} teacherName={session.teacher.name} />;
}

function parseSeat(value: string | null): number | null {
  if (value === null || !/^\d+$/.test(value)) return null;
  return Number(value);
}

function TeacherDesk({ code, teacherName }: { code: string; teacherName: string }) {
  // The session cookie goes with the socket, so the hello carries nothing secret.
  const hello = useMemo<Hello>(() => ({ role: "teacher" }), []);
  const { classroom, send, dismissNotice } = useClassroom(code, hello);
  const { room, steps } = classroom;

  const [source, setSource] = useState("");
  const sourceRef = useRef(source);
  sourceRef.current = source;
  const [adopted, setAdopted] = useState(false);

  // Same rule as a student's editor: the server's copy on first load, ours after a reconnection.
  useEffect(() => {
    if (classroom.joins === 0) return;
    if (!adopted) {
      setSource(classroom.teacherSource);
      setAdopted(true);
    } else {
      send({ type: "source", text: sourceRef.current });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [classroom.joins]);

  useThrottledSend(source, adopted, (text) => send({ type: "source", text }));

  // The watched seat lives in the URL, so a reload keeps it.
  const [params, setParams] = useSearchParams();
  const watchedSeat = parseSeat(params.get("seat"));
  const watched = watchedSeat === null ? undefined : classroom.seats.find((seat) => seat.seat === watchedSeat);
  const isWatching = watched !== undefined;

  useEffect(() => {
    if (classroom.joins === 0) return;
    send({ type: "watch", seat: isWatching ? watchedSeat : null });
  }, [classroom.joins, watchedSeat, isWatching, send]);

  // The student left the seat (or the link named an empty one): drop the selection.
  useEffect(() => {
    if (classroom.joins > 0 && watchedSeat !== null && !isWatching) setParams({}, { replace: true });
  }, [classroom.joins, watchedSeat, isWatching, setParams]);

  const watchedText =
    isWatching && classroom.studentSource?.seat === watchedSeat ? classroom.studentSource.text : null;

  // A hint is a short note that appears above the watched student's editor.
  const [hintDraft, setHintDraft] = useState("");
  useEffect(() => {
    setHintDraft("");
  }, [watchedSeat]);
  const sendHint = (event: FormEvent) => {
    event.preventDefault();
    const text = hintDraft.trim();
    if (!text || watchedSeat === null) return;
    if (send({ type: "hint", seat: watchedSeat, text })) setHintDraft("");
  };

  // Who needs the teacher: raised hands in order, then students who look stuck.
  const queue = helpQueue(classroom.seats);
  const hands = queue.filter((seat) => seat.hand).length;

  // The tab's title counts raised hands, so they show while another tab is in front.
  useEffect(() => {
    const plain = document.title.replace(/^\(\d+\) /, "");
    document.title = hands > 0 ? `(${hands}) ${plain}` : plain;
    return () => {
      document.title = plain;
    };
  }, [hands]);

  // The class writes Python or web pages; only the runner it needs is started.
  const isWeb = room?.language === "web";
  const python = usePython(undefined, room?.language === "python");
  const web = useWebPage();
  const startPage = web.start;
  const runNow = () => (isWeb ? startPage(sourceRef.current, "run") : python.run(sourceRef.current));

  // A web page shows itself as it is typed, a moment after the typing stops.
  useEffect(() => {
    if (!isWeb || !adopted) return;
    const timer = window.setTimeout(() => startPage(source, "preview"), 600);
    return () => window.clearTimeout(timer);
  }, [isWeb, adopted, source, startPage]);

  // In a web class a student's code can be looked at as code or as the page it makes.
  const [studentView, setStudentView] = useState<"code" | "page">("code");

  // "manual" means the browser refused clipboard access, so the link is shown to copy by hand.
  const [share, setShare] = useState<"" | "copied" | "manual">("");
  const joinLink = `${window.location.origin}/join/${code}`;
  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(joinLink);
      setShare("copied");
      window.setTimeout(() => setShare(""), 2000);
    } catch {
      setShare("manual");
    }
  };

  // The lesson editor replaces the desk while open. A save is pending until the
  // server broadcasts the new lesson (the editor closes) or refuses it (a notice).
  const [editing, setEditing] = useState(false);
  const [pendingSince, setPendingSince] = useState<number | null>(null);
  const saveLesson = (drafts: StepDraft[]) => {
    dismissNotice();
    setPendingSince(classroom.lessonSeq);
    send({ type: "set_steps", steps: drafts });
  };
  useEffect(() => {
    if (pendingSince === null) return;
    if (classroom.lessonSeq > pendingSince) {
      setPendingSince(null);
      setEditing(false);
    } else if (classroom.notice) {
      setPendingSince(null);
    }
  }, [pendingSince, classroom.lessonSeq, classroom.notice]);

  if (classroom.phase === "closed" && classroom.closeReason) {
    return <RoomClosed reason={classroom.closeReason} detail={classroom.closeDetail} code={code} />;
  }
  if (!room) return <RoomLoading />;

  const barEnd = (
    <>
      <span className="bar__who">{teacherName}</span>
      <Link className="btn" to="/teach">
        Your classes
      </Link>
    </>
  );

  if (editing) {
    return (
      <>
        <TopBar classroom={classroom}>{barEnd}</TopBar>
        <main className="lesson-page">
          <LessonEditor
            steps={steps}
            language={room.language}
            saving={pendingSince !== null}
            notice={classroom.notice}
            onSave={saveLesson}
            onCancel={() => {
              dismissNotice();
              setEditing(false);
            }}
          />
        </main>
      </>
    );
  }

  return (
    <>
      <TopBar classroom={classroom}>{barEnd}</TopBar>
      <main className="work">
        <section className="pane pane--split" aria-label="Your code">
          <div className="pane__head">
            <h2 className="pane__title">Your code</h2>
            <span className={classroom.phase === "open" ? "status status--live" : "status"} role="status">
              {classroom.phase === "open" ? "Students see this live" : "Paused"}
            </span>
          </div>
          <div className="pane__body">
            <CodeEditor
              value={source}
              onChange={setSource}
              label="Your code, shown to students live"
              onRun={runNow}
              placeholder="Type here. Every student sees it as you type."
              language={room.language}
            />
          </div>
          {isWeb ? <PagePanel web={web} onRun={runNow} /> : <RunPanel python={python} onRun={runNow} />}
        </section>

        <section className="pane desk" aria-label="The classroom">
          <div className="desk__top">
            <dl className="figures">
              <div className="figure">
                <dt>Join code</dt>
                <dd>{room.code}</dd>
              </div>
              <div className="figure">
                <dt>Seated</dt>
                <dd>{classroom.seats.length}</dd>
              </div>
              <div className="figure">
                <dt>Choosing a seat</dt>
                <dd>{classroom.lobby.length}</dd>
              </div>
            </dl>
            <div className="desk__share">
              <p className="desk__link">
                {share === "manual" ? (
                  <span className="mono">{joinLink}</span>
                ) : (
                  <>
                    Students join at <span className="mono">{window.location.host}</span> with the code.
                  </>
                )}
              </p>
              <button type="button" className="btn" onClick={copyLink}>
                {share === "copied" ? "Link copied" : "Copy join link"}
              </button>
            </div>
          </div>

          <section className="desk__lesson" aria-label="Lesson">
            <div className="pane__head">
              <h2 className="pane__title">Lesson</h2>
              <div className="pane__tools">
                {steps.length > 0 && (
                  <span className="pane__note">
                    {steps.length} {steps.length === 1 ? "step" : "steps"}
                  </span>
                )}
                <button type="button" className="btn" onClick={() => setEditing(true)}>
                  {steps.length > 0 ? "Edit lesson" : "Write the lesson"}
                </button>
              </div>
            </div>
            {steps.length === 0 ? (
              <p className="desk__hint">
                No steps yet. A step gives students a task and the output it must print; their passes show on
                the map.
              </p>
            ) : (
              <ol className="steps steps--desk">
                {steps.map((step, index) => {
                  const isNow = classroom.currentStep === step.id;
                  const count = classroom.seats.filter((seat) => seat.passed?.includes(step.id)).length;
                  return (
                    <li key={step.id}>
                      <button
                        type="button"
                        className={classes("step", isNow && "step--now")}
                        aria-pressed={isNow}
                        aria-label={`Step ${index + 1}: ${step.title}, passed by ${count} of ${classroom.seats.length} seated`}
                        title={isNow ? "The class is on this step. Click to clear." : "Point the class at this step"}
                        onClick={() => send({ type: "set_current_step", step: isNow ? null : step.id })}
                      >
                        <span className="step__num">{index + 1}</span>
                        <span className="step__title">{step.title}</span>
                        {isNow && <span className="step__now">Now</span>}
                        <span className="step__count">
                          {count}/{classroom.seats.length}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ol>
            )}
          </section>

          <div className="desk__map">
            {queue.length > 0 && (
              <section className="help" aria-label="Needs help" aria-live="polite">
                <h2 className="pane__title">Needs help</h2>
                <ol className="help__list">
                  {queue.map((seat) => (
                    <li key={seat.seat}>
                      <button
                        type="button"
                        className={classes(
                          "help__item",
                          !seat.hand && "help__item--stuck",
                          seat.seat === watchedSeat && "help__item--open",
                        )}
                        aria-pressed={seat.seat === watchedSeat}
                        aria-label={
                          seat.hand
                            ? `Hand ${seat.hand}: ${seat.name}, seat ${seatLabel(seat.seat, room.cols)}`
                            : `Stuck: ${seat.name}, seat ${seatLabel(seat.seat, room.cols)}`
                        }
                        onClick={() => setParams({ seat: String(seat.seat) })}
                      >
                        <span className="help__place">{seat.hand ? seat.hand : "Stuck"}</span>
                        <span className="help__name">{seat.name}</span>
                        <span className="help__seat">{seatLabel(seat.seat, room.cols)}</span>
                      </button>
                    </li>
                  ))}
                </ol>
              </section>
            )}
            <SeatMap
              rows={room.rows}
              cols={room.cols}
              seats={classroom.seats}
              mode="watch"
              current={isWatching ? watchedSeat : null}
              onSelect={(seat) => setParams(seat === watchedSeat ? {} : { seat: String(seat) })}
              stepCount={steps.length}
            />
          </div>

          <section className={watched ? "viewer viewer--open" : "viewer"} aria-label="Student’s code">
            {watched && watchedSeat !== null ? (
              <>
                <div className="pane__head">
                  <h2 className="pane__title">
                    {watched.name}, seat <span className="mono">{seatLabel(watchedSeat, room.cols)}</span>
                  </h2>
                  <div className="pane__tools">
                    {steps.length > 0 && (
                      <ol
                        className="marks"
                        aria-label={`${watched.passed?.length ?? 0} of ${steps.length} steps passed`}
                      >
                        {steps.map((step, index) => (
                          <li
                            key={step.id}
                            className={watched.passed?.includes(step.id) ? "mark mark--passed" : "mark"}
                            title={step.title}
                          >
                            {index + 1}
                          </li>
                        ))}
                      </ol>
                    )}
                    <span className={watched.online && watched.hand ? "status status--warn" : "status"} role="status">
                      {seatWords(watched)}
                    </span>
                    {isWeb && (
                      <button
                        type="button"
                        className="btn"
                        onClick={() => setStudentView(studentView === "code" ? "page" : "code")}
                      >
                        {studentView === "code" ? "Show page" : "Show code"}
                      </button>
                    )}
                    {watched.hand != null && (
                      <button
                        type="button"
                        className="btn"
                        onClick={() => send({ type: "lower_hand", seat: watchedSeat })}
                      >
                        Lower hand
                      </button>
                    )}
                    <button
                      type="button"
                      className="btn"
                      onClick={() => send({ type: "free_seat", seat: watchedSeat })}
                    >
                      Free this seat
                    </button>
                    <button type="button" className="btn" onClick={() => setParams({})}>
                      Close
                    </button>
                  </div>
                </div>
                <form className="hintbar" onSubmit={sendHint}>
                  <label className="visually-hidden" htmlFor="hint-text">
                    A hint for {watched.name}
                  </label>
                  <input
                    id="hint-text"
                    className="input"
                    value={hintDraft}
                    onChange={(event) => setHintDraft(event.target.value)}
                    maxLength={300}
                    autoComplete="off"
                    placeholder={`A hint for ${watched.name}, shown above their code`}
                  />
                  <button type="submit" className="btn" disabled={!hintDraft.trim() || classroom.phase !== "open"}>
                    Send hint
                  </button>
                  {watched.hint && (
                    <p className="hintbar__live" role="status">
                      <span className="hintbar__quote">On their screen: {watched.hint}</span>
                      <button
                        type="button"
                        className="btn"
                        onClick={() => send({ type: "hint", seat: watchedSeat, text: "" })}
                      >
                        Take back
                      </button>
                    </p>
                  )}
                </form>
                <div className="pane__body">
                  {watchedText === null ? (
                    <div className="skeleton viewer__loading" aria-busy="true" />
                  ) : isWeb && studentView === "page" ? (
                    <PagePreview source={watchedText} title={`${watched.name}’s page`} />
                  ) : (
                    <CodeEditor
                      value={watchedText}
                      label={`${watched.name}’s code, read only`}
                      readOnly
                      placeholder={`${watched.name} has not typed anything yet.`}
                      language={room.language}
                    />
                  )}
                </div>
              </>
            ) : (
              <div className="empty">
                <h2 className="pane__title">
                  {classroom.seats.length === 0 ? "Nobody has sat down yet" : "No seat selected"}
                </h2>
                <p>
                  {classroom.seats.length === 0
                    ? "Share the join code. Each student appears on the map as they take a seat."
                    : "Select a seat on the map to watch that student’s code as they type."}
                </p>
              </div>
            )}
          </section>
        </section>
      </main>
    </>
  );
}
