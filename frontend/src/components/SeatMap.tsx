import type { CSSProperties } from "react";
import { type Seat, seatLabel } from "../lib/protocol";

type Props = {
  rows: number;
  cols: number;
  seats: Seat[];
  /**
   * pick: a student choosing a free seat. watch: the teacher choosing whose
   * code to follow. preview: nothing can be clicked.
   */
  mode: "pick" | "watch" | "preview";
  /** The student's own seat (pick) or the seat being watched (watch). */
  current?: number | null;
  onSelect?: (seat: number) => void;
  /** Smaller desks, for the preview on the start form. */
  compact?: boolean;
};

function runWord(seat: Seat): { text: string; tone: "" | "error" | "ok" } {
  if (!seat.online) return { text: "Offline", tone: "" };
  if (seat.lastRun === "error") return { text: "Error", tone: "error" };
  if (seat.lastRun === "ok") return { text: "Ran fine", tone: "ok" };
  return { text: "Not run yet", tone: "" };
}

export function SeatMap({ rows, cols, seats, mode, current = null, onSelect, compact = false }: Props) {
  const bySeat = new Map(seats.map((seat) => [seat.seat, seat]));
  const style = { "--cols": cols } as CSSProperties;

  return (
    <div className={compact ? "room room--compact" : "room"}>
      <p className="room__front">Teacher’s desk</p>
      <ol className="room__grid" style={style}>
        {Array.from({ length: rows * cols }, (_, index) => {
          const label = seatLabel(index, cols);
          const occupant = bySeat.get(index);
          const isCurrent = current === index;

          if (mode === "pick" && (!occupant || isCurrent)) {
            return (
              <li key={index}>
                <button
                  type="button"
                  className={isCurrent ? "seat seat--current" : "seat seat--free"}
                  aria-pressed={isCurrent}
                  aria-label={isCurrent ? `Seat ${label}, your seat` : `Take seat ${label}`}
                  onClick={() => onSelect?.(index)}
                >
                  <span className="seat__label">{label}</span>
                  <span className="seat__name">{isCurrent ? "You" : "Free"}</span>
                </button>
              </li>
            );
          }

          if (mode === "watch" && occupant) {
            const state = runWord(occupant);
            return (
              <li key={index}>
                <button
                  type="button"
                  className={[
                    "seat seat--taken",
                    isCurrent ? "seat--current" : "",
                    occupant.online ? "" : "seat--offline",
                  ].join(" ")}
                  aria-pressed={isCurrent}
                  aria-label={`${occupant.name}, seat ${label}, ${state.text.toLowerCase()}`}
                  onClick={() => onSelect?.(index)}
                >
                  <span className="seat__label">{label}</span>
                  <span className="seat__name">{occupant.name}</span>
                  <span className={state.tone ? `seat__state seat__state--${state.tone}` : "seat__state"}>
                    {state.text}
                  </span>
                </button>
              </li>
            );
          }

          return (
            <li key={index}>
              <div className={occupant ? "seat seat--taken" : "seat seat--empty"}>
                <span className="seat__label">{label}</span>
                {occupant && <span className="seat__name">{occupant.name}</span>}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
