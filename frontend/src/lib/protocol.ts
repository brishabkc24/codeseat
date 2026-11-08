// The shapes of the messages exchanged with the server (see backend/app/main.py).

export type ClassInfo = { code: string; title: string; rows: number; cols: number };

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
  /** Only the teacher receives these two. */
  lastRun?: RunResult | null;
  passed?: string[];
};

export type You = { id: string; name: string; seat: number | null; source: string; passed: string[] };

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
  | { type: "you"; seat?: number | null; passed?: string[] }
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
