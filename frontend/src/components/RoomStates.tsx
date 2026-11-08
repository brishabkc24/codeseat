import { Link } from "react-router-dom";
import type { CloseReason } from "../lib/useClassroom";
import { TopBar } from "./TopBar";

type ClosedProps = { reason: CloseReason; detail?: string; code: string };

/** Shown when the class cannot be entered and retrying would not help. */
export function RoomClosed({ reason, detail, code }: ClosedProps) {
  return (
    <>
      <TopBar />
      <main className="closed">
        {reason === "no-class" && (
          <>
            <h1>This class is not open</h1>
            <p>
              No open class has the code <span className="mono">{code}</span>. Check the code with your teacher.
            </p>
            <Link className="btn" to="/">
              Back to the start
            </Link>
          </>
        )}
        {reason === "not-teacher" && (
          <>
            <h1>This desk is not yours to open</h1>
            <p>
              Only the teacher who made this class can open its desk. Log in with that account, or join
              the class as a student.
            </p>
            <div className="closed__actions">
              <Link className="btn btn--primary" to="/" state={{ notice: "Log in to open your class." }}>
                Log in
              </Link>
              <Link className="btn" to={`/join/${code}`}>
                Join as a student
              </Link>
            </div>
          </>
        )}
        {reason === "replaced" && (
          <>
            <h1>This class is open in another tab</h1>
            <p>Keep working there, or reload this tab to move the class here.</p>
            <button type="button" className="btn" onClick={() => window.location.reload()}>
              Reload this tab
            </button>
          </>
        )}
        {reason === "refused" && (
          <>
            <h1>The class did not let you in</h1>
            <p>{detail || "The server refused the connection."}</p>
            <Link className="btn" to={`/join/${code}`}>
              Try joining again
            </Link>
          </>
        )}
      </main>
    </>
  );
}

/** The outline of a room while the first answer from the server is on its way. */
export function RoomLoading() {
  return (
    <>
      <TopBar />
      <main className="work" aria-busy="true">
        <p className="visually-hidden" role="status">
          Connecting to the class…
        </p>
        <div className="pane">
          <div className="pane__head">
            <span className="skeleton skeleton--text" />
          </div>
          <div className="pane__body skeleton" />
        </div>
        <div className="pane">
          <div className="pane__head">
            <span className="skeleton skeleton--text" />
          </div>
          <div className="pane__body skeleton" />
        </div>
      </main>
    </>
  );
}
