import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { SeatMap } from "../components/SeatMap";
import { TopBar } from "../components/TopBar";
import { createClass, deleteClass, errorText, listClasses } from "../lib/api";
import type { ClassSummary, Language, Teacher } from "../lib/protocol";
import { useSession } from "../lib/session";

const ROW_CHOICES = [1, 2, 3, 4, 5, 6, 7, 8];
const COL_CHOICES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];

export function Classes() {
  const session = useSession();
  if (!session.known) {
    return (
      <>
        <TopBar />
        <main className="classes" aria-busy="true">
          <p className="visually-hidden" role="status">
            Checking who is signed in…
          </p>
          <span className="skeleton skeleton--text" />
        </main>
      </>
    );
  }
  if (!session.teacher) return <Navigate to="/" replace state={{ notice: "Log in to see your classes." }} />;
  return <ClassesPage teacher={session.teacher} signOut={session.signOut} />;
}

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

function ClassesPage({ teacher, signOut }: { teacher: Teacher; signOut: () => Promise<void> }) {
  const navigate = useNavigate();

  const [classes, setClasses] = useState<ClassSummary[] | null>(null);
  const [listError, setListError] = useState("");
  const load = useCallback(async () => {
    try {
      setClasses(await listClasses());
      setListError("");
    } catch (error) {
      setListError(errorText(error));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const [title, setTitle] = useState("");
  const [rows, setRows] = useState(4);
  const [cols, setCols] = useState(6);
  const [language, setLanguage] = useState<Language>("python");
  const [startError, setStartError] = useState("");
  const [starting, setStarting] = useState(false);
  const titleRef = useRef<HTMLInputElement>(null);

  const start = async (event: FormEvent) => {
    event.preventDefault();
    const cleanTitle = title.trim();
    if (!cleanTitle) {
      setStartError("Give the class a name, such as the group or the course.");
      titleRef.current?.focus();
      return;
    }
    setStartError("");
    setStarting(true);
    try {
      const room = await createClass(cleanTitle, rows, cols, language);
      navigate(`/teach/${room.code}`);
    } catch (error) {
      setStartError(errorText(error));
    } finally {
      setStarting(false);
    }
  };

  // Deleting takes two clicks on the same row, so a slip cannot lose a class.
  const [confirming, setConfirming] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const remove = async (code: string) => {
    setDeleting(code);
    try {
      await deleteClass(code);
      setConfirming(null);
      await load();
    } catch (error) {
      setListError(errorText(error));
    } finally {
      setDeleting(null);
    }
  };

  const leave = async () => {
    await signOut();
    navigate("/");
  };

  return (
    <>
      <TopBar>
        <span className="bar__who">{teacher.name}</span>
        <button type="button" className="btn" onClick={() => void leave()}>
          Log out
        </button>
      </TopBar>
      <main className="classes">
        <div className="home__head">
          <h1>Your classes</h1>
          <p className="lead">A class keeps its join code, its lesson and every seat between lessons.</p>
        </div>

        <section className="classes__section" aria-labelledby="new-class-title">
          <h2 id="new-class-title">New class</h2>
          <form className="classes__form" onSubmit={start} noValidate>
            <div className="home__setup">
              <div className="home__fields">
                <div className="field">
                  <label className="field__label" htmlFor="start-title">
                    Class name
                  </label>
                  <input
                    id="start-title"
                    ref={titleRef}
                    className="input"
                    name="title"
                    value={title}
                    onChange={(event) => setTitle(event.target.value)}
                    maxLength={60}
                    autoComplete="off"
                    aria-required="true"
                    aria-invalid={startError !== ""}
                    aria-describedby="start-title-help"
                  />
                  <p
                    id="start-title-help"
                    className={startError ? "field__help field__help--error" : "field__help"}
                    role={startError ? "alert" : undefined}
                  >
                    {startError || "Students see this at the top of the class."}
                  </p>
                </div>
                <div className="field">
                  <label className="field__label" htmlFor="start-language">
                    The class writes
                  </label>
                  <select
                    id="start-language"
                    className="input"
                    name="language"
                    value={language}
                    onChange={(event) => setLanguage(event.target.value as Language)}
                  >
                    <option value="python">Python</option>
                    <option value="web">Web pages (HTML, CSS, JavaScript)</option>
                  </select>
                  <p className="field__help">This cannot be changed once the class is made.</p>
                </div>
                <div className="home__sizes">
                  <div className="field">
                    <label className="field__label" htmlFor="start-rows">
                      Rows
                    </label>
                    <select
                      id="start-rows"
                      className="input"
                      name="rows"
                      value={rows}
                      onChange={(event) => setRows(Number(event.target.value))}
                    >
                      {ROW_CHOICES.map((choice) => (
                        <option key={choice} value={choice}>
                          {choice}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="field">
                    <label className="field__label" htmlFor="start-cols">
                      Seats per row
                    </label>
                    <select
                      id="start-cols"
                      className="input"
                      name="cols"
                      value={cols}
                      onChange={(event) => setCols(Number(event.target.value))}
                    >
                      {COL_CHOICES.map((choice) => (
                        <option key={choice} value={choice}>
                          {choice}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
                <button type="submit" className="btn btn--primary" disabled={starting} aria-busy={starting}>
                  {starting ? "Creating…" : "Create class"}
                </button>
              </div>

              <figure className="home__preview">
                <SeatMap rows={rows} cols={cols} seats={[]} mode="preview" compact />
                <figcaption>
                  <span className="mono">{rows * cols}</span> seats, row A nearest the teacher
                </figcaption>
              </figure>
            </div>
          </form>
        </section>

        <section className="classes__section" aria-labelledby="class-list-title">
          <h2 id="class-list-title">Saved classes</h2>
          {listError && (
            <p className="notice" role="alert">
              {listError}
            </p>
          )}
          {classes === null ? (
            <span className="skeleton skeleton--text" aria-busy="true" />
          ) : classes.length === 0 ? (
            <p className="classes__none">No classes yet. The first one you make appears here.</p>
          ) : (
            <ul className="courses">
              {classes.map((item) => (
                <li key={item.code} className="course">
                  <div className="course__about">
                    <h3 className="course__title">
                      {item.title} <span className="course__kind">{item.language === "web" ? "Web pages" : "Python"}</span>
                    </h3>
                    <p className="course__meta">
                      <span className="mono">{item.code}</span> · {item.rows * item.cols} seats ·{" "}
                      {plural(item.students, "student")} · {plural(item.steps, "step")}
                    </p>
                  </div>
                  <div className="course__actions">
                    {confirming === item.code ? (
                      <>
                        <span className="status status--warn">Delete this class and its students’ work?</span>
                        <button
                          type="button"
                          className="btn"
                          onClick={() => void remove(item.code)}
                          disabled={deleting === item.code}
                          aria-busy={deleting === item.code}
                        >
                          {deleting === item.code ? "Deleting…" : "Yes, delete"}
                        </button>
                        <button type="button" className="btn" onClick={() => setConfirming(null)}>
                          Keep
                        </button>
                      </>
                    ) : (
                      <>
                        <Link className="btn btn--primary" to={`/teach/${item.code}`}>
                          Open class
                        </Link>
                        <button type="button" className="btn" onClick={() => setConfirming(item.code)}>
                          Delete
                        </button>
                      </>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </main>
    </>
  );
}
