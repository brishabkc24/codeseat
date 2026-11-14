import { type FormEvent, useState } from "react";
import starterLessons from "../data/starter-lessons.json";
import type { Step } from "../lib/protocol";

/** A ready-made lesson a teacher can load and then change (src/data/starter-lessons.json). */
type StarterLesson = { id: string; title: string; summary: string; steps: Omit<Step, "id">[] };

const LIBRARY = starterLessons as StarterLesson[];

/** A step as sent to the server: an existing step keeps its id, a new one has none. */
export type StepDraft = Omit<Step, "id"> & { id?: string };

type Draft = StepDraft & { key: number };

type Props = {
  steps: Step[];
  /** True from the save being sent until the server answers. */
  saving: boolean;
  /** The server's refusal of the last save, if any. */
  notice: string | null;
  onSave: (steps: StepDraft[]) => void;
  onCancel: () => void;
};

let nextKey = 1;

function blank(): Draft {
  nextKey += 1;
  return { key: nextKey, title: "", instructions: "", input: "", expectedOutput: "" };
}

function fromStep(step: Step): Draft {
  nextKey += 1;
  return { ...step, key: nextKey };
}

function incomplete(draft: Draft): boolean {
  return draft.title.trim() === "" || draft.expectedOutput.trim() === "";
}

function written(draft: Draft): boolean {
  return [draft.title, draft.instructions, draft.input, draft.expectedOutput].some((text) => text.trim() !== "");
}

/** The teacher's form for the lesson: every step with its task, input and expected output. */
export function LessonEditor({ steps, saving, notice, onSave, onCancel }: Props) {
  const [drafts, setDrafts] = useState<Draft[]>(() => (steps.length > 0 ? steps.map(fromStep) : [blank()]));
  const [tried, setTried] = useState(false);

  // The ready-made lessons are open when there is nothing written yet. Loading one
  // over steps that hold text takes a second click, so a slip cannot lose them.
  const [browsing, setBrowsing] = useState(steps.length === 0);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [loaded, setLoaded] = useState("");
  const load = (lesson: StarterLesson) => {
    setDrafts(
      lesson.steps.map((step) => {
        nextKey += 1;
        return { ...step, key: nextKey };
      }),
    );
    setTried(false);
    setConfirming(null);
    setBrowsing(false);
    setLoaded(lesson.title);
  };

  const patch = (key: number, change: Partial<StepDraft>) =>
    setDrafts((current) => current.map((draft) => (draft.key === key ? { ...draft, ...change } : draft)));

  const move = (index: number, delta: number) =>
    setDrafts((current) => {
      const target = index + delta;
      if (target < 0 || target >= current.length) return current;
      const next = current.slice();
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setTried(true);
    if (drafts.some(incomplete)) return;
    onSave(drafts.map(({ key: _key, ...step }) => step));
  };

  return (
    <form className="lesson-editor" onSubmit={submit} noValidate>
      <div className="lesson-editor__head">
        <div className="lesson-editor__intro">
          <h2>Lesson steps</h2>
          <p className="lead">
            Each step sets a task and the exact output a program must print to pass it. Students check a step
            from their desk; passes show on the seat map.
          </p>
        </div>
        <div className="lesson-editor__actions">
          <button type="button" className="btn" onClick={onCancel}>
            Cancel
          </button>
          <button type="submit" className="btn btn--primary" disabled={saving} aria-busy={saving}>
            {saving ? "Saving…" : "Save lesson"}
          </button>
        </div>
      </div>

      {notice && (
        <p className="notice" role="alert">
          {notice}
        </p>
      )}
      {tried && drafts.some(incomplete) && (
        <p className="notice" role="alert">
          Every step needs a title and an expected output.
        </p>
      )}

      <section className="library" aria-labelledby="library-title">
        <div className="library__head">
          <h3 id="library-title" className="library__title">
            Ready-made lessons
          </h3>
          <button type="button" className="btn" aria-expanded={browsing} onClick={() => setBrowsing(!browsing)}>
            {browsing ? "Hide" : "Show"}
          </button>
        </div>
        {loaded && !browsing && (
          <p className="library__note" role="status">
            Loaded “{loaded}”. Change anything you like below, then save.
          </p>
        )}
        {browsing && (
          <>
            <p className="library__note">
              Ten first lessons in Python, in teaching order. Loading one fills in the steps below, where you
              can change anything before saving.
            </p>
            <ul className="courses">
              {LIBRARY.map((lesson) => (
                <li key={lesson.id} className="course">
                  <div className="course__about">
                    <h4 className="course__title">{lesson.title}</h4>
                    <p className="course__meta">
                      {lesson.summary} {lesson.steps.length} steps.
                    </p>
                  </div>
                  <div className="course__actions">
                    {confirming === lesson.id ? (
                      <>
                        <span className="status status--warn">Replace the steps you have written?</span>
                        <button type="button" className="btn" onClick={() => load(lesson)}>
                          Yes, replace
                        </button>
                        <button type="button" className="btn" onClick={() => setConfirming(null)}>
                          Keep mine
                        </button>
                      </>
                    ) : (
                      <button
                        type="button"
                        className="btn"
                        aria-label={`Use the lesson ${lesson.title}`}
                        onClick={() => (drafts.some(written) ? setConfirming(lesson.id) : load(lesson))}
                      >
                        Use this lesson
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      {drafts.length === 0 ? (
        <p className="lesson-editor__none">No steps. Saving now clears the lesson.</p>
      ) : (
        <ol className="lesson-editor__list">
          {drafts.map((draft, index) => {
            const id = `step-${draft.key}`;
            const titleMissing = tried && draft.title.trim() === "";
            const outputMissing = tried && draft.expectedOutput.trim() === "";
            return (
              <li key={draft.key}>
                <fieldset className="step-form">
                  <legend className="step-form__legend">Step {index + 1}</legend>
                  <div className="step-form__tools">
                    <button type="button" className="btn" onClick={() => move(index, -1)} disabled={index === 0}>
                      Move up
                    </button>
                    <button
                      type="button"
                      className="btn"
                      onClick={() => move(index, 1)}
                      disabled={index === drafts.length - 1}
                    >
                      Move down
                    </button>
                    <button
                      type="button"
                      className="btn"
                      onClick={() => setDrafts((current) => current.filter((item) => item.key !== draft.key))}
                    >
                      Remove
                    </button>
                  </div>

                  <div className="field">
                    <label className="field__label" htmlFor={`${id}-title`}>
                      Title
                    </label>
                    <input
                      id={`${id}-title`}
                      className="input"
                      value={draft.title}
                      onChange={(event) => patch(draft.key, { title: event.target.value })}
                      maxLength={80}
                      aria-invalid={titleMissing}
                      autoComplete="off"
                    />
                    <p
                      className={titleMissing ? "field__help field__help--error" : "field__help"}
                      role={titleMissing ? "alert" : undefined}
                    >
                      {titleMissing ? "Give the step a title." : "Shown in the list of steps."}
                    </p>
                  </div>

                  <div className="field">
                    <label className="field__label" htmlFor={`${id}-text`}>
                      Instructions
                    </label>
                    <textarea
                      id={`${id}-text`}
                      className="input input--area"
                      rows={3}
                      value={draft.instructions}
                      onChange={(event) => patch(draft.key, { instructions: event.target.value })}
                      maxLength={2000}
                    />
                    <p className="field__help">What the student should make the program do. Optional.</p>
                  </div>

                  <div className="step-form__io">
                    <div className="field">
                      <label className="field__label" htmlFor={`${id}-input`}>
                        Input for the program
                      </label>
                      <textarea
                        id={`${id}-input`}
                        className="input input--area input--mono"
                        rows={4}
                        value={draft.input}
                        onChange={(event) => patch(draft.key, { input: event.target.value })}
                        maxLength={2000}
                        spellCheck={false}
                      />
                      <p className="field__help">One line per input() call. Leave empty if the program asks nothing.</p>
                    </div>
                    <div className="field">
                      <label className="field__label" htmlFor={`${id}-output`}>
                        Expected output
                      </label>
                      <textarea
                        id={`${id}-output`}
                        className="input input--area input--mono"
                        rows={4}
                        value={draft.expectedOutput}
                        onChange={(event) => patch(draft.key, { expectedOutput: event.target.value })}
                        maxLength={5000}
                        aria-invalid={outputMissing}
                        spellCheck={false}
                      />
                      <p
                        className={outputMissing ? "field__help field__help--error" : "field__help"}
                        role={outputMissing ? "alert" : undefined}
                      >
                        {outputMissing
                          ? "Say what the program must print."
                          : "Exactly what the program prints. Spaces at line ends and blank lines at the end do not count."}
                      </p>
                    </div>
                  </div>
                </fieldset>
              </li>
            );
          })}
        </ol>
      )}

      <button type="button" className="btn" onClick={() => setDrafts((current) => [...current, blank()])}>
        Add a step
      </button>
    </form>
  );
}
