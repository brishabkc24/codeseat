import { classes, firstDifference, stepNumber, tidyOutput } from "../lib/lesson";
import type { RunResult, Step } from "../lib/protocol";

/** The server's verdict on a check, with what the program printed on that run. */
export type Verdict = { passed: boolean; result: RunResult; output: string };

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
}: Props) {
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
              <p className="task__label">Your program will be given</p>
              <pre className="task__block">{selected.input}</pre>
            </div>
          )}
          <div className="task__io">
            <p className="task__label">It should print</p>
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
              Runs your code{selected.input ? " with the input above" : ""} and compares what it prints.
            </p>
          </div>
          {verdict && (
            <VerdictNote
              step={selected}
              verdict={verdict}
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
  next: Step | null;
  nextNumber: (id: string) => number;
  onSelect: (id: string) => void;
};

function VerdictNote({ step, verdict, next, nextNumber, onSelect }: VerdictProps) {
  if (verdict.passed) {
    return (
      <div className="task__verdict task__verdict--ok task__verdict--row" role="status">
        <p>
          {next
            ? "Passed. Your program printed what this step asks for."
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
        Not yet. Your program stopped with an error; the output pane shows where.
      </p>
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
