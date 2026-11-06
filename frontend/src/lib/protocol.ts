// The shapes of the messages exchanged with the server (see backend/app/main.py).

export type ClassInfo = { code: string; title: string; rows: number; cols: number };

export type RunResult = "ok" | "error";

export type Seat = {
  seat: number;
  name: string;
  online: boolean;
  /** Only the teacher receives this. */
  lastRun?: RunResult | null;
};

export type You = { id: string; name: string; seat: number | null; source: string };

export type ServerMessage =
  | {
      type: "welcome";
      class: ClassInfo;
      seats: Seat[];
      teacherSource: string;
      lobby?: string[];
      you?: You;
    }
  | { type: "seats"; seats: Seat[]; lobby?: string[] }
  | { type: "you"; seat: number | null }
  | { type: "teacher_source"; text: string }
  | { type: "student_source"; seat: number; text: string }
  | { type: "error"; message: string };

export type Hello =
  | { role: "teacher"; token: string }
  | { role: "student"; name: string; studentId: string | null };

/** Seats are numbered row by row from the front; row A is nearest the teacher. */
export function seatLabel(seat: number, cols: number): string {
  return `${String.fromCharCode(65 + Math.floor(seat / cols))}${(seat % cols) + 1}`;
}
