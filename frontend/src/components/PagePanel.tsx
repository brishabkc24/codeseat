import { useEffect, useRef, useState } from "react";
import type { OutputChunk } from "../lib/usePython";
import type { WebPage } from "../lib/useWebPage";

const CHUNK_CLASS: Record<OutputChunk["stream"], string | undefined> = {
  stdout: undefined,
  stderr: "console__err",
  stdin: "console__in",
  note: "console__note",
};

type Props = {
  web: WebPage;
  onRun: () => void;
};

/**
 * The student's or teacher's own page, running, with what it writes to the
 * console underneath. The page lives in a sandboxed frame: it may run scripts
 * but cannot reach CodeSeat, the login or the browser's storage.
 */
export function PagePanel({ web, onRun }: Props) {
  const { run, running, output, frameRef } = web;
  const outRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    const element = outRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [output]);

  return (
    <section className="console page" aria-label="Your page">
      <div className="pane__head">
        <h2 className="pane__title">Page</h2>
        <div className="pane__tools">
          {running && (
            <span className="status status--live" role="status">
              Loading
            </span>
          )}
          {run?.mode === "preview" && !running && <span className="pane__note pane__note--extra">Pop-ups are off while you type</span>}
          <button type="button" className="btn btn--primary" onClick={onRun} title="Ctrl+Enter">
            Run
          </button>
        </div>
      </div>

      {run ? (
        <iframe
          // A new frame for every run: nothing of the last page is left behind.
          key={run.id}
          ref={frameRef}
          className="page__frame"
          title="Your page"
          sandbox={run.mode === "run" ? "allow-scripts allow-modals" : "allow-scripts"}
          srcDoc={run.document}
          {...{ credentialless: "" }}
        />
      ) : (
        <p className="page__empty">Your page appears here as you type.</p>
      )}

      {output.length > 0 && (
        <pre className="console__out page__console" ref={outRef} tabIndex={0} aria-live="polite" aria-label="Console">
          {output.map((chunk, index) => (
            <span key={index} className={CHUNK_CLASS[chunk.stream]}>
              {chunk.text}
            </span>
          ))}
        </pre>
      )}
    </section>
  );
}

/**
 * Someone else's page, to look at: the teacher's on a student's screen, or a
 * student's on the teacher's. Scripts are off here, so a page that loops for
 * ever or keeps opening pop-ups cannot freeze the person looking.
 */
export function PagePreview({ source, title }: { source: string; title: string }) {
  // The picture follows the typing a moment behind, not on every keystroke.
  const [shown, setShown] = useState(source);
  useEffect(() => {
    const timer = window.setTimeout(() => setShown(source), 300);
    return () => window.clearTimeout(timer);
  }, [source]);

  return (
    <div className="page-preview">
      <iframe className="page__frame" title={title} sandbox="" srcDoc={shown} {...{ credentialless: "" }} />
      <p className="page-preview__note">Scripts are switched off in this view.</p>
    </div>
  );
}
