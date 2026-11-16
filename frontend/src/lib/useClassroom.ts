import { useCallback, useEffect, useReducer, useRef } from "react";
import type { ClassInfo, Hello, Seat, ServerMessage, Step, You } from "./protocol";

export type CloseReason = "no-class" | "not-teacher" | "replaced" | "refused";

// Close codes after which retrying is pointless (they match backend/app/main.py).
const FATAL: Record<number, CloseReason> = {
  4400: "refused",
  4401: "not-teacher",
  4404: "no-class",
  4409: "replaced",
  4429: "refused", // far too many messages at once; the reason says so
};

export type Classroom = {
  phase: "connecting" | "open" | "reconnecting" | "closed";
  closeReason: CloseReason | null;
  closeDetail: string;
  room: ClassInfo | null;
  seats: Seat[];
  /** Teacher only: names of students who have not picked a seat yet. */
  lobby: string[];
  teacherSource: string;
  steps: Step[];
  /** The step the teacher has pointed the class at, if any. */
  currentStep: string | null;
  /** Counts lesson updates, so the editor can tell when its save has landed. */
  lessonSeq: number;
  /** Student only. */
  you: You | null;
  /** Student only: the server's verdict on the latest check; seq tells one from the next. */
  lastCheck: { step: string; passed: boolean; seq: number } | null;
  /** Teacher only: the latest code of the seat being watched. */
  studentSource: { seat: number; text: string } | null;
  /** The last refusal from the server, for example a seat that was just taken. */
  notice: string | null;
  /** Counts welcomes, so a page can tell a first connection from a reconnection. */
  joins: number;
};

const initial: Classroom = {
  phase: "connecting",
  closeReason: null,
  closeDetail: "",
  room: null,
  seats: [],
  lobby: [],
  teacherSource: "",
  steps: [],
  currentStep: null,
  lessonSeq: 0,
  you: null,
  lastCheck: null,
  studentSource: null,
  notice: null,
  joins: 0,
};

type Action =
  | { kind: "reset" }
  | { kind: "reconnecting" }
  | { kind: "closed"; reason: CloseReason; detail: string }
  | { kind: "dismiss" }
  | { kind: "server"; message: ServerMessage };

function reduce(state: Classroom, action: Action): Classroom {
  switch (action.kind) {
    case "reset":
      return initial;
    case "reconnecting":
      return { ...state, phase: state.room ? "reconnecting" : "connecting" };
    case "closed":
      return { ...state, phase: "closed", closeReason: action.reason, closeDetail: action.detail };
    case "dismiss":
      return state.notice === null ? state : { ...state, notice: null };
    case "server": {
      const message = action.message;
      switch (message.type) {
        case "welcome":
          return {
            ...state,
            phase: "open",
            closeReason: null,
            room: message.class,
            seats: message.seats,
            lobby: message.lobby ?? [],
            teacherSource: message.teacherSource,
            steps: message.steps,
            currentStep: message.currentStep,
            you: message.you ?? null,
            notice: null,
            joins: state.joins + 1,
          };
        case "seats":
          return { ...state, seats: message.seats, lobby: message.lobby ?? state.lobby };
        case "you": {
          if (!state.you) return state;
          const you = { ...state.you };
          if (message.seat !== undefined) you.seat = message.seat;
          if (message.passed !== undefined) you.passed = message.passed;
          if (message.hand !== undefined) you.hand = message.hand;
          if (message.hint !== undefined) you.hint = message.hint;
          return { ...state, you };
        }
        case "teacher_source":
          return { ...state, teacherSource: message.text };
        case "student_source":
          return { ...state, studentSource: { seat: message.seat, text: message.text } };
        case "steps":
          return {
            ...state,
            steps: message.steps,
            currentStep: message.currentStep,
            lessonSeq: state.lessonSeq + 1,
          };
        case "check": {
          const seq = (state.lastCheck?.seq ?? 0) + 1;
          const you =
            state.you && message.passed && !state.you.passed.includes(message.step)
              ? { ...state.you, passed: [...state.you.passed, message.step] }
              : state.you;
          return { ...state, you, lastCheck: { step: message.step, passed: message.passed, seq } };
        }
        case "error":
          return { ...state, notice: message.message };
        default:
          return state;
      }
    }
  }
}

/**
 * Keeps one WebSocket open to a class and mirrors what the server says about it.
 * Pass `null` as hello to stay disconnected. A dropped connection is retried
 * with a growing delay; the server remembers the seat and the code meanwhile.
 */
export function useClassroom(code: string, hello: Hello | null) {
  const [state, dispatch] = useReducer(reduce, initial);
  const socketRef = useRef<WebSocket | null>(null);
  const helloRef = useRef(hello);
  helloRef.current = hello;
  const enabled = hello !== null;

  useEffect(() => {
    if (!enabled) return;
    let stopped = false;
    let attempt = 0;
    let timer: number | undefined;
    let studentId: string | null = null; // issued by the server on the first welcome

    const connect = () => {
      const current = helloRef.current;
      if (stopped || !current) return;
      const scheme = location.protocol === "https:" ? "wss" : "ws";
      const socket = new WebSocket(`${scheme}://${location.host}/ws/${encodeURIComponent(code)}`);
      socketRef.current = socket;

      socket.onopen = () => {
        const who =
          current.role === "student"
            ? { ...current, studentId: studentId ?? current.studentId }
            : current;
        socket.send(JSON.stringify({ type: "hello", ...who }));
      };

      socket.onmessage = (event) => {
        let message: ServerMessage;
        try {
          message = JSON.parse(event.data);
        } catch {
          return;
        }
        if (message.type === "welcome") {
          attempt = 0;
          if (message.you) studentId = message.you.id;
        }
        dispatch({ kind: "server", message });
      };

      socket.onclose = (event) => {
        if (socketRef.current === socket) socketRef.current = null;
        if (stopped) return;
        const reason = FATAL[event.code];
        if (reason) {
          dispatch({ kind: "closed", reason, detail: event.reason });
          return;
        }
        dispatch({ kind: "reconnecting" });
        timer = window.setTimeout(connect, Math.min(1000 * 2 ** attempt, 8000));
        attempt += 1;
      };
    };

    dispatch({ kind: "reset" });
    connect();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [code, enabled]);

  /** Returns false when the message could not be sent because the socket is down. */
  const send = useCallback((message: object): boolean => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return false;
    socket.send(JSON.stringify(message));
    return true;
  }, []);

  const dismissNotice = useCallback(() => dispatch({ kind: "dismiss" }), []);

  return { classroom: state, send, dismissNotice };
}
