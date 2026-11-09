import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { Classroom } from "../lib/useClassroom";
import { useInstallPrompt } from "../lib/useInstallPrompt";

type Props = {
  /** The class being shown, once the server has described it. */
  classroom?: Classroom;
  children?: ReactNode;
};

export function TopBar({ classroom, children }: Props) {
  const room = classroom?.room;
  const { canInstall, install } = useInstallPrompt();
  return (
    <header className="bar">
      <Link className="bar__mark" to="/" aria-label="CodeSeat, back to the start">
        CodeSeat
      </Link>
      {room && (
        <div className="bar__class">
          <h1 className="bar__title">{room.title}</h1>
          <span className="bar__code" title="Join code">
            {room.code}
          </span>
        </div>
      )}
      <div className="bar__end">
        {canInstall && (
          <button type="button" className="btn" onClick={() => void install()}>
            Install app
          </button>
        )}
        {classroom?.phase === "reconnecting" && (
          <span className="status status--warn" role="status">
            Connection lost. Reconnecting…
          </span>
        )}
        {children}
      </div>
    </header>
  );
}
