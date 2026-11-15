import { classes, firstDifference, stepNumber, tidyOutput } from "../lib/lesson";
import type { Language, RunResult, Step } from "../lib/protocol";

/** The server's verdict on a check, with what the program printed (and, for a web page, showed) on that run. */
export type Verdict = { passed: boolean; result: RunResult; output: string; page: string };

type Props = {
  steps: Step[];
  currentStep: string | null;
  passed: string[];
  selected: Step;
  onSelect: (id: string) => void;
  onCheck: (step: Step) => void;
  /** The id of the step whose check is running, if any. */
  checking: string | null;
  /** False while Python is still loading or another program is running. */
  canCheck: boolean;
  /** The verdict on the selected step, if it was checked on this visit. */
  verdict: Verdict | null;
  language: Language;
};

/** The student's side of the lesson: the steps, the selected task and the check on it. */
export function StepsPane({
  steps,
  currentStep,
  passed,
  selected,
  onSelect,
  onCheck,
  checking,
  canCheck,
  verdict,
  language,
}: Props) {
  const web = language === "web";
  const done = passed.includes(selected.id);

  return (
    <section className="pane lesson" aria-label="Lesson">
      <div className="pane__head">
        <h2 className="pane__title">Lesson</h2>
        <span className="pane__note">
          {passed.length} of {steps.length} passed
        </span>
      </div>
      <div className="pane__body lesson__body">
        <ol className="steps">
          {steps.map((step, index) => {
            const isSelected = step.id === selected.id;
            const isDone = passed.includes(step.id);
            const isNow = step.id === currentStep;
            const label = [`Step ${index + 1}: ${step.title}`, isNow && "the class is on this step", isDone && "passed"]
              .filter(Boolean)
              .join(", ");
            return (
              <li key={step.id}>
                <button
                  type="button"
                  className={classes("step", isDone && "step--passed", isSelected && "step--selected")}
                  aria-pressed={isSelected}
                  aria-label={label}
                  onClick={() => onSelect(step.id)}
                >
                  <span className="step__num">{index + 1}</span>
                  <span className="step__title">{step.title}</span>
                  {isNow && <span className="step__now">Now</span>}
                  <span className="step__mark">{isDone ? "Passed" : ""}</span>
                </button>
              </li>
            );
          })}
        </ol>

        <article className="task">
          <h3 className="task__title">
            Step {stepNumber(steps, selected.id)}: {selected.title}
          </h3>
          {selected.instructions && <p className="task__text">{selected.instructions}</p>}
          {selected.input && (
            <div className="task__io">
              <p className="task__label">{web ? "prompt() on your page will be answered with" : "Your program will be given"}</p>
              <pre className="task__block">{selected.input}</pre>
            </div>
          )}
          <div className="task__io">
            <p className="task__label">{web ? "The page, or its console, should show" : "It should print"}</p>
            <pre className="task__block">{selected.expectedOutput}</pre>
          </div>
          <div className="task__actions">
            <button
              type="button"
              className="btn btn--primary"
              disabled={!canCheck || checking !== null}
              aria-busy={checking === selected.id}
              onClick={() => onCheck(selected)}
            >
              {checking === selected.id ? "Checking…" : done ? "Check again" : "Check this step"}
            </button>
            <p className="task__hint">
              {web
                ? `Loads your page${selected.input ? " with the answers above" : ""} and compares what it shows.`
                : `Runs your code${selected.input ? " with the input above" : ""} and compares what it prints.`}
            </p>
          </div>
          {verdict && (
            <VerdictNote
              step={selected}
              verdict={verdict}
              web={web}
              next={nextStep(steps, passed, selected)}
              nextNumber={(id) => stepNumber(steps, id)}
              onSelect={onSelect}
            />
          )}
        </article>
      </div>
    </section>
  );
}

/** Where to go after a pass: the next step not yet passed, looking after this one first. */
function nextStep(steps: Step[], passed: string[], current: Step): Step | null {
  const at = steps.findIndex((step) => step.id === current.id);
  const open = (step: Step) => step.id !== current.id && !passed.includes(step.id);
  return steps.slice(at + 1).find(open) ?? steps.slice(0, at).find(open) ?? null;
}

type VerdictProps = {
  step: Step;
  verdict: Verdict;
  web: boolean;
  next: Step | null;
  nextNumber: (id: string) => number;
  onSelect: (id: string) => void;
};

/** The lines a page shows, as the server compares them: blank lines and outer spaces do not count. */
function shownLines(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim().replace(/\s+/g, " "))
    .filter((line) => line !== "");
}

function VerdictNote({ step, verdict, web, next, nextNumber, onSelect }: VerdictProps) {
  if (verdict.passed) {
    return (
      <div className="task__verdict task__verdict--ok task__verdict--row" role="status">
        <p>
          {next
            ? `Passed. Your ${web ? "page shows" : "program printed"} what this step asks for.`
            : "Passed. That was the last one: every step is done."}
        </p>
        {next && (
          <button type="button" className="btn" onClick={() => onSelect(next.id)}>
            Next: step {nextNumber(next.id)}
          </button>
        )}
      </div>
    );
  }
  if (verdict.result === "error") {
    return (
      <p className="task__verdict task__verdict--no" role="status">
        {web
          ? "Not yet. A script on your page stopped with an error; the console under the page says where."
          : "Not yet. Your program stopped with an error; the output pane shows where."}
      </p>
    );
  }
  if (web) {
    const consoleLines = tidyOutput(verdict.output);
    const pageLines = shownLines(verdict.page);
    return (
      <div className="task__verdict task__verdict--no" role="status">
        <p>Not yet. Neither the page nor its console shows exactly what the step asks for.</p>
        <p className="task__label">Your page shows</p>
        <pre className="task__block">
          {pageLines.length === 0 ? <span className="console__note">Nothing</span> : pageLines.join("\n")}
        </pre>
        {consoleLines.length > 0 && (
          <>
            <p className="task__label">Its console printed</p>
            <pre className="task__block">{consoleLines.join("\n")}</pre>
          </>
        )}
      </div>
    );
  }
  const line = firstDifference(step.expectedOutput, verdict.output);
  const printed = tidyOutput(verdict.output);
  return (
    <div className="task__verdict task__verdict--no" role="status">
      <p>Not yet. The output differs{line !== null ? ` from line ${line}` : ""}.</p>
      <p className="task__label">Your program printed</p>
      {printed.length === 0 ? (
        <pre className="task__block">
          <span className="console__note">Nothing</span>
        </pre>
      ) : (
        <pre className="task__block">
          {printed.map((text, index) => (
            <span key={index} className={index + 1 === line ? "task__line task__line--diff" : "task__line"}>
              {text}
              {"\n"}
            </span>
          ))}
        </pre>
      )}
    </div>
  );
}
