import { useCallback, useEffect, useRef, useState } from "react";
import type { RunResult } from "./protocol";

export type OutputChunk = {
  /** stdin is what the student typed; note is a message from CodeSeat itself. */
  stream: "stdout" | "stderr" | "stdin" | "note";
  text: string;
};

export type PythonPhase = "loading" | "ready" | "running" | "failed";

const INPUT_BYTES = 64 * 1024;

type WorkerMessage =
  | { type: "ready" }
  | { type: "failed"; message: string }
  | { type: "output"; chunks: [OutputChunk["stream"], string][] }
  | { type: "input" }
  | { type: "done"; id: number; status: "ok" | "error" | "limit" };

/** Adds a message from CodeSeat on a line of its own. */
function withNote(current: OutputChunk[], text: string): OutputChunk[] {
  const last = current[current.length - 1];
  const midLine = last !== undefined && !last.text.endsWith("\n");
  return merge(current, [{ stream: "note", text: `${midLine ? "\n" : ""}${text}\n` }]);
}

function merge(current: OutputChunk[], incoming: OutputChunk[]): OutputChunk[] {
  const next = current.slice();
  for (const chunk of incoming) {
    const last = next[next.length - 1];
    if (last && last.stream === chunk.stream) {
      next[next.length - 1] = { stream: last.stream, text: last.text + chunk.text };
    } else {
      next.push(chunk);
    }
  }
  return next;
}

export type RunOptions = {
  /** Lines to answer input() with, one per line. Without it input() asks the user. */
  stdin?: string;
};

/**
 * Python in a Web Worker (see public/py-worker.js). `onFinish` is told how
 * each run ended and everything it printed; a run the user stopped is not reported.
 */
export function usePython(onFinish?: (result: RunResult, output: OutputChunk[]) => void) {
  const [phase, setPhaseState] = useState<PythonPhase>("loading");
  const phaseRef = useRef<PythonPhase>("loading");
  const setPhase = useCallback((next: PythonPhase) => {
    phaseRef.current = next; // read by run(), which must not wait for a re-render
    setPhaseState(next);
  }, []);
  const [failure, setFailure] = useState("");
  const [output, setOutputState] = useState<OutputChunk[]>([]);
  const outputRef = useRef<OutputChunk[]>([]);
  const setOutput = useCallback((update: (current: OutputChunk[]) => OutputChunk[]) => {
    outputRef.current = update(outputRef.current); // complete at once, for onFinish
    setOutputState(outputRef.current);
  }, []);
  const [waitingForInput, setWaitingForInput] = useState(false);

  const workerRef = useRef<Worker | null>(null);
  const stdinRef = useRef<{ meta: Int32Array; bytes: Uint8Array } | null>(null);
  const runId = useRef(0);
  const finishRef = useRef(onFinish);
  finishRef.current = onFinish;

  const boot = useCallback(() => {
    const worker = new Worker("/py-worker.js", { type: "module" });
    workerRef.current = worker;
    setPhase("loading");

    // input() pauses the worker on a shared buffer until the page fills it in.
    // Shared buffers exist only on a cross-origin isolated page (see vite.config.ts).
    const init: { type: "init"; meta?: SharedArrayBuffer; bytes?: SharedArrayBuffer } = { type: "init" };
    if (window.crossOriginIsolated && typeof SharedArrayBuffer !== "undefined") {
      init.meta = new SharedArrayBuffer(8);
      init.bytes = new SharedArrayBuffer(INPUT_BYTES);
      stdinRef.current = { meta: new Int32Array(init.meta), bytes: new Uint8Array(init.bytes) };
    } else {
      stdinRef.current = null;
    }

    worker.onmessage = (event: MessageEvent<WorkerMessage>) => {
      if (workerRef.current !== worker) return;
      const message = event.data;
      switch (message.type) {
        case "ready":
          setPhase("ready");
          break;
        case "failed":
          setFailure(message.message);
          setPhase("failed");
          break;
        case "output":
          setOutput((current) =>
            merge(
              current,
              message.chunks.map(([stream, text]) => ({ stream, text })),
            ),
          );
          break;
        case "input":
          setWaitingForInput(true);
          break;
        case "done":
          if (message.id !== runId.current) break;
          setWaitingForInput(false);
          setPhase("ready");
          if (message.status === "limit") {
            setOutput((current) =>
              withNote(current, "Stopped: the program printed more than 200,000 characters."),
            );
          }
          finishRef.current?.(message.status === "ok" ? "ok" : "error", outputRef.current);
          break;
      }
    };

    worker.onerror = () => {
      if (workerRef.current !== worker) return;
      setFailure("Python could not start in this browser.");
      setPhase("failed");
    };

    worker.postMessage(init);
  }, [setPhase, setOutput]);

  useEffect(() => {
    boot();
    return () => {
      workerRef.current?.terminate();
      workerRef.current = null;
    };
  }, [boot]);

  const run = useCallback(
    (source: string, options: RunOptions = {}) => {
      const worker = workerRef.current;
      if (!worker || phaseRef.current !== "ready") return;
      runId.current += 1;
      setOutput(() => []);
      setWaitingForInput(false);
      setPhase("running");
      worker.postMessage({ type: "run", id: runId.current, source, stdin: options.stdin });
    },
    [setPhase, setOutput],
  );

  /** Ends a running program. Python cannot be interrupted, so it is restarted. */
  const stop = useCallback(() => {
    if (!workerRef.current) return;
    workerRef.current.terminate();
    workerRef.current = null;
    runId.current += 1;
    setWaitingForInput(false);
    setOutput((current) => withNote(current, "Stopped."));
    boot();
  }, [boot, setOutput]);

  const sendInput = useCallback((text: string) => {
    const stdin = stdinRef.current;
    if (!stdin) return;
    const encoded = new TextEncoder().encode(text).subarray(0, INPUT_BYTES);
    stdin.bytes.set(encoded);
    Atomics.store(stdin.meta, 1, encoded.length);
    Atomics.store(stdin.meta, 0, 1);
    Atomics.notify(stdin.meta, 0);
    setWaitingForInput(false);
    setOutput((current) => merge(current, [{ stream: "stdin", text: `${text}\n` }]));
  }, [setOutput]);

  return { phase, failure, output, waitingForInput, run, stop, sendInput };
}

export type Python = ReturnType<typeof usePython>;
