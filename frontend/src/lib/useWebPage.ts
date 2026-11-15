import { useCallback, useEffect, useRef, useState } from "react";
import type { RunResult } from "./protocol";
import { type OutputChunk, merge, withNote } from "./usePython";

/**
 * How a page is run.
 * - "preview": while typing. Pop-ups are switched off and nobody is told.
 * - "run": the student pressed Run. alert(), confirm() and prompt() work.
 * - "check": for a lesson step. prompt() answers come from the step's input.
 */
export type PageMode = "preview" | "run" | "check";

export type PageRun = {
  /** Changes with every run; the frame is made anew each time. */
  id: number;
  /** The page with CodeSeat's listener in front of it. */
  document: string;
  mode: PageMode;
};

export type PageFinish = {
  mode: PageMode;
  result: RunResult;
  /** What the page wrote with console.log and friends. */
  output: OutputChunk[];
  /** The text the page shows once loaded. */
  page: string;
};

const MAX_OUTPUT = 200_000; // characters a single run may write to the console
const SETTLE_MS = 250; // after the page has loaded, time for its first scripts and timers to speak
const GIVE_UP_MS = 6_000; // a page that has not loaded by then is reported as broken

/** "3\n4\n" and "3\n4" are both two lines; "" is none. The same rule as the Python runner. */
function toLines(text: string): string[] {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  if (lines[lines.length - 1] === "") lines.pop();
  return lines;
}

/**
 * The script put in front of the student's page. It runs inside the sandboxed
 * frame, passes console output and errors to CodeSeat, and says when the page
 * has loaded and what it shows. It is written on one line and without a line
 * break after it, so line numbers in errors are the student's own.
 */
function listener(token: string, mode: PageMode, answers: string[]): string {
  const popups =
    mode === "run"
      ? ""
      : `var answers=${JSON.stringify(answers)};window.prompt=function(){return answers.length?answers.shift():null};` +
        "window.alert=function(){};window.confirm=function(){return true};";
  const code =
    "(function(){" +
    `var token=${JSON.stringify(token)};` +
    'function send(kind,text){try{parent.postMessage({codeseat:token,kind:kind,text:String(text)},"*")}catch(e){}}' +
    'function show(v){if(typeof v==="string")return v;' +
    'try{if(v instanceof Error)return v.name+": "+v.message;' +
    'if(typeof v==="object"&&v!==null)return JSON.stringify(v)}catch(e){}return String(v)}' +
    '["log","info","debug","warn","error"].forEach(function(name){var real=console[name];' +
    'console[name]=function(){var text=Array.prototype.map.call(arguments,show).join(" ");' +
    'send(name==="error"?"stderr":"stdout",text+"\\n");if(real)real.apply(console,arguments)}});' +
    'window.addEventListener("error",function(e){' +
    'send("error",(e.message||"The page could not load something")+(e.lineno?" (line "+e.lineno+")":"")+"\\n")});' +
    'window.addEventListener("unhandledrejection",function(e){send("error","Uncaught (in promise) "+show(e.reason)+"\\n")});' +
    popups +
    `window.addEventListener("load",function(){setTimeout(function(){send("done",document.body?document.body.innerText:"")},${SETTLE_MS})});` +
    "})();";
  return `<script>${code}</script>`;
}

/** The student's page with the listener in front; a doctype stays first so the page keeps its mode. */
export function instrument(source: string, token: string, mode: PageMode, stdin: string): string {
  const script = listener(token, mode, toLines(stdin));
  const doctype = /^\s*<!doctype[^>]*>/i.exec(source);
  if (doctype) return doctype[0] + script + source.slice(doctype[0].length);
  return script + source;
}

/**
 * Runs a web page in a sandboxed frame and listens to it. The frame has no
 * access to CodeSeat itself: it cannot read the page around it, the login
 * cookie or anything stored in the browser.
 */
export function useWebPage(onFinish?: (finish: PageFinish) => void) {
  const [run, setRun] = useState<PageRun | null>(null);
  const [running, setRunning] = useState(false);
  const [output, setOutputState] = useState<OutputChunk[]>([]);
  const outputRef = useRef<OutputChunk[]>([]);
  const setOutput = useCallback((update: (current: OutputChunk[]) => OutputChunk[]) => {
    outputRef.current = update(outputRef.current);
    setOutputState(outputRef.current);
  }, []);

  const frameRef = useRef<HTMLIFrameElement | null>(null);
  const live = useRef<{ id: number; token: string; mode: PageMode; failed: boolean; written: number } | null>(null);
  const counter = useRef(0);
  const timer = useRef<number | undefined>(undefined);
  const finishRef = useRef(onFinish);
  finishRef.current = onFinish;

  const finish = useCallback(
    (page: string, failed: boolean) => {
      const current = live.current;
      if (!current) return;
      live.current = null;
      window.clearTimeout(timer.current);
      setRunning(false);
      finishRef.current?.({
        mode: current.mode,
        result: failed || current.failed ? "error" : "ok",
        output: outputRef.current,
        page,
      });
    },
    [],
  );

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      const current = live.current;
      const data = event.data as { codeseat?: string; kind?: string; text?: string } | null;
      if (!current || !data || data.codeseat !== current.token) return;
      if (event.source !== frameRef.current?.contentWindow) return;
      const text = typeof data.text === "string" ? data.text : "";
      if (data.kind === "done") {
        finish(text, false);
        return;
      }
      if (data.kind === "error") current.failed = true;
      if (current.written > MAX_OUTPUT) return;
      current.written += text.length;
      const stream = data.kind === "stdout" ? "stdout" : "stderr";
      setOutput((before) => merge(before, [{ stream, text }]));
      if (current.written > MAX_OUTPUT) {
        setOutput((before) => withNote(before, "The page wrote more than 200,000 characters; the rest is not shown."));
      }
    };
    window.addEventListener("message", onMessage);
    return () => {
      window.removeEventListener("message", onMessage);
      window.clearTimeout(timer.current);
    };
  }, [finish, setOutput]);

  const start = useCallback(
    (source: string, mode: PageMode, stdin = "") => {
      counter.current += 1;
      const token = `${counter.current}-${Math.random().toString(36).slice(2)}`;
      live.current = { id: counter.current, token, mode, failed: false, written: 0 };
      setOutput(() => []);
      setRunning(true);
      setRun({ id: counter.current, document: instrument(source, token, mode, stdin), mode });
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => {
        if (live.current?.token !== token) return;
        setOutput((before) => withNote(before, "The page did not finish loading. A loop that never ends can cause this."));
        finish("", true);
      }, GIVE_UP_MS);
    },
    [finish, setOutput],
  );

  /** Takes the page away. Nobody is told how it ended. */
  const stop = useCallback(() => {
    live.current = null;
    window.clearTimeout(timer.current);
    setRunning(false);
    setRun(null);
    setOutput(() => []);
  }, [setOutput]);

  return { run, running, output, frameRef, start, stop };
}

export type WebPage = ReturnType<typeof useWebPage>;
