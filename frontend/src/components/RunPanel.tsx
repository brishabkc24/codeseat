import { type FormEvent, useEffect, useRef, useState } from "react";
import type { OutputChunk, Python } from "../lib/usePython";

const CHUNK_CLASS: Record<OutputChunk["stream"], string | undefined> = {
  stdout: undefined,
  stderr: "console__err",
  stdin: "console__in",
  note: "console__note",
};

type Props = {
  python: Python;
  onRun: () => void;
};

/** The Run and Stop control with everything the program prints beneath it. */
export function RunPanel({ python, onRun }: Props) {
  const { phase, failure, output, waitingForInput, stop, sendInput } = python;
  const outRef = useRef<HTMLPreElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [answer, setAnswer] = useState("");

  // Follow the output as it grows, like a terminal.
  useEffect(() => {
    const element = outRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [output, waitingForInput]);

  useEffect(() => {
    if (waitingForInput) inputRef.current?.focus();
  }, [waitingForInput]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    sendInput(answer);
    setAnswer("");
  };

  return (
    <section className="console" aria-label="Program output">
      <div className="pane__head">
        <h2 className="pane__title">Output</h2>
        <div className="pane__tools">
          {phase === "loading" && (
            <span className="status" role="status">
              Loading Python…
            </span>
          )}
          {phase === "running" && !waitingForInput && (
            <span className="status status--live" role="status">
              Running
            </span>
          )}
          {waitingForInput && (
            <span className="status status--live" role="status">
              Waiting for your input
            </span>
          )}
          {/* Separate keys: one element restyled in place would fade between the two looks. */}
          {phase === "running" ? (
            <button key="stop" type="button" className="btn" onClick={stop}>
              Stop
            </button>
          ) : (
            <button
              key="run"
              type="button"
              className="btn btn--primary"
              onClick={onRun}
              disabled={phase !== "ready"}
              aria-busy={phase === "loading"}
              title="Ctrl+Enter"
            >
              Run
            </button>
          )}
        </div>
      </div>

      {phase === "failed" ? (
        <div className="console__out console__out--prose" role="alert">
          <p>Python did not start, so programs cannot run in this tab.</p>
          <p className="console__note">{failure}</p>
          <p>Reload the page to try again.</p>
        </div>
      ) : (
        <pre className="console__out" ref={outRef} tabIndex={0} aria-live="polite" aria-label="Output">
          {output.length === 0 && phase !== "running" ? (
            <span className="console__note">Run your program to see what it prints.</span>
          ) : (
            output.map((chunk, index) => (
              <span key={index} className={CHUNK_CLASS[chunk.stream]}>
                {chunk.text}
              </span>
            ))
          )}
        </pre>
      )}

      {waitingForInput && (
        <form className="console__ask" onSubmit={submit}>
          <label className="visually-hidden" htmlFor="program-input">
            Answer for the program
          </label>
          <input
            id="program-input"
            ref={inputRef}
            className="input input--mono"
            value={answer}
            onChange={(event) => setAnswer(event.target.value)}
            autoComplete="off"
            spellCheck={false}
          />
          <button type="submit" className="btn">
            Enter
          </button>
        </form>
      )}
    </section>
  );
}
