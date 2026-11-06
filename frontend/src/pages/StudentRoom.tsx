import { useEffect, useMemo, useRef, useState } from "react";
import { Navigate, useLocation, useParams } from "react-router-dom";
import { CodeEditor } from "../components/CodeEditor";
import { RoomClosed, RoomLoading } from "../components/RoomStates";
import { RunPanel } from "../components/RunPanel";
import { SeatMap } from "../components/SeatMap";
import { TopBar } from "../components/TopBar";
import { type StudentIdentity, loadStudent, saveStudent } from "../lib/api";
import { type Hello, seatLabel } from "../lib/protocol";
import { useClassroom } from "../lib/useClassroom";
import { usePython } from "../lib/usePython";
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

function StudentDesk({ code, identity }: { code: string; identity: StudentIdentity }) {
  const hello = useMemo<Hello>(
    () => ({ role: "student", name: identity.name, studentId: identity.id }),
    [identity],
  );
  const { classroom, send, dismissNotice } = useClassroom(code, hello);
  const { room, you } = classroom;

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

  const python = usePython((result) => send({ type: "run", status: result }));
  const runNow = () => python.run(sourceRef.current);

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
        <section className="pane" aria-label="Teacher’s code">
          <div className="pane__head">
            <h2 className="pane__title">Teacher’s code</h2>
            <span className={classroom.phase === "open" ? "status status--live" : "status"} role="status">
              {classroom.phase === "open" ? "Live" : "Paused"}
            </span>
          </div>
          <div className="pane__body">
            <CodeEditor
              value={classroom.teacherSource}
              label="Teacher’s code, read only"
              readOnly
              placeholder="Your teacher has not typed anything yet."
            />
          </div>
        </section>

        <section className="pane pane--split" aria-label="Your code">
          <div className="pane__head">
            <h2 className="pane__title">Your code</h2>
            <span className="pane__note">Your teacher can see this</span>
          </div>
          <div className="pane__body">
            <CodeEditor
              value={source}
              onChange={setSource}
              label="Your code"
              onRun={runNow}
              placeholder="Type your Python here."
            />
          </div>
          <RunPanel python={python} onRun={runNow} />
        </section>
      </main>
    </>
  );
}
