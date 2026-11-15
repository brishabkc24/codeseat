// The shapes of the messages exchanged with the server (see backend/app/main.py).

/** What a class writes: Python programs, or web pages (HTML with its CSS and JavaScript). */
export type Language = "python" | "web";

export type ClassInfo = { code: string; title: string; rows: number; cols: number; language: Language };

export type Teacher = { id: string; name: string; email: string };

/** A class as listed on the teacher's classes page. Times are seconds since 1970. */
export type ClassSummary = ClassInfo & { students: number; steps: number; createdAt: number; updatedAt: number };

export type RunResult = "ok" | "error";

/** One task of the lesson. It passes when a program prints the expected output. */
export type Step = {
  id: string;
  title: string;
  instructions: string;
  expectedOutput: string;
  /** Lines handed to input(), one per line; empty when the program gets no input. */
  input: string;
};

export type Seat = {
  seat: number;
  name: string;
  online: boolean;
  // Only the teacher receives the rest.
  lastRun?: RunResult | null;
  passed?: string[];
  /** The place in the queue of raised hands (1 went up first), or null while the hand is down. */
  hand?: number | null;
  /** Several failed tries in a row: crashes, or checks that did not pass. */
  stuck?: boolean;
  /** Whole minutes without typing, running or clicking, once that is long enough to count; else null. */
  idleMinutes?: number | null;
  /** The teacher's note now on this student's screen, or null when there is none. */
  hint?: string | null;
};

export type You = {
  id: string;
  name: string;
  seat: number | null;
  source: string;
  passed: string[];
  hand: boolean;
  /** A note from the teacher, shown above the editor; empty when there is none. */
  hint: string;
};

export type ServerMessage =
  | {
      type: "welcome";
      class: ClassInfo;
      seats: Seat[];
      teacherSource: string;
      steps: Step[];
      currentStep: string | null;
      lobby?: string[];
      you?: You;
    }
  | { type: "seats"; seats: Seat[]; lobby?: string[] }
  | { type: "you"; seat?: number | null; passed?: string[]; hand?: boolean; hint?: string }
  | { type: "teacher_source"; text: string }
  | { type: "student_source"; seat: number; text: string }
  | { type: "steps"; steps: Step[]; currentStep: string | null }
  | { type: "check"; step: string; passed: boolean }
  | { type: "error"; message: string };

/** The teacher is known by the session cookie the browser sends with the connection. */
export type Hello = { role: "teacher" } | { role: "student"; name: string; studentId: string | null };

/** Seats are numbered row by row from the front; row A is nearest the teacher. */
export function seatLabel(seat: number, cols: number): string {
  return `${String.fromCharCode(65 + Math.floor(seat / cols))}${(seat % cols) + 1}`;
}
