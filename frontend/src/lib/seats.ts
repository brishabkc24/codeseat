// What a seat tells the teacher. The facts come from the server (backend/app/rooms.py);
// this only decides which of them to say first.

import type { Seat } from "./protocol";

export type SeatTone = "" | "hand" | "error" | "ok" | "idle";

/** The one line a seat shows on the map: the most pressing thing about its student. */
export function seatState(seat: Seat): { text: string; tone: SeatTone } {
  if (!seat.online) return { text: "Offline", tone: "" };
  if (seat.hand) return { text: `Hand up · ${seat.hand}`, tone: "hand" };
  if (seat.stuck) return { text: "Stuck", tone: "error" };
  if (seat.idleMinutes) return { text: `Idle ${seat.idleMinutes} min`, tone: "idle" };
  if (seat.lastRun === "error") return { text: "Error", tone: "error" };
  if (seat.lastRun === "ok") return { text: "Ran fine", tone: "ok" };
  return { text: "Not run yet", tone: "" };
}

/** Everything worth saying about a seat, for the head of the teacher's view of it. */
export function seatWords(seat: Seat): string {
  if (!seat.online) return "Offline";
  const words: string[] = [];
  if (seat.hand) words.push("Hand up");
  if (seat.stuck) words.push("Stuck");
  if (seat.idleMinutes) words.push(`Idle ${seat.idleMinutes} min`);
  if (seat.lastRun === "error") words.push("Last run: error");
  else if (seat.lastRun === "ok") words.push("Last run: fine");
  else words.push("Not run yet");
  return words.join(" · ");
}

/**
 * Who the teacher should go to: raised hands in the order they went up, then
 * students who look stuck and have not asked.
 */
export function helpQueue(seats: Seat[]): Seat[] {
  const hands = seats.filter((seat) => seat.online && seat.hand).sort((a, b) => (a.hand ?? 0) - (b.hand ?? 0));
  const stuck = seats.filter((seat) => seat.online && seat.stuck && !seat.hand);
  return [...hands, ...stuck];
}
