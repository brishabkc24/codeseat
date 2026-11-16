import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { TopBar } from "../components/TopBar";
import {
  type AdminClass,
  type AdminOverview,
  type AdminTeacher,
  ApiError,
  adminApprove,
  adminBlock,
  adminDeleteTeacher,
  adminEndClass,
  adminLogIn,
  adminLogOut,
  adminOverview,
  adminSession,
  adminSetPassword,
  errorText,
} from "../lib/api";

const REFRESH_MS = 10_000;
const MIN_PASSWORD = 8;

type Gate = "checking" | "off" | "login" | "in";

/** The site owner's page: every class and every teacher account, and the ways to stop them. */
export function Admin() {
  const [gate, setGate] = useState<Gate>("checking");
  const [gateError, setGateError] = useState("");

  useEffect(() => {
    let current = true;
    adminSession()
      .then((state) => current && setGate(state.admin ? "in" : state.configured ? "login" : "off"))
      .catch((error) => {
        if (!current) return;
        setGateError(errorText(error));
        setGate("login");
      });
    return () => {
      current = false;
    };
  }, []);

  if (gate === "in") return <AdminPage onSignedOut={() => setGate("login")} />;

  return (
    <>
      <TopBar />
      <main className="classes" aria-busy={gate === "checking"}>
        {gate === "checking" && (
          <>
            <p className="visually-hidden" role="status">
              Checking who is signed in…
            </p>
            <span className="skeleton skeleton--text" />
          </>
        )}
        {gate === "off" && (
          <div className="home__head">
            <h1>The admin page is switched off</h1>
            <p className="lead">
              It opens once the site has an admin password. Where the site is hosted, set{" "}
              <span className="mono">CODESEAT_ADMIN_PASSWORD</span> to a password of 12 characters or more, then
              start the site again.
            </p>
          </div>
        )}
        {gate === "login" && <AdminLogIn firstError={gateError} onSignedIn={() => setGate("in")} />}
      </main>
    </>
  );
}

function AdminLogIn({ firstError, onSignedIn }: { firstError: string; onSignedIn: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState(firstError);
  const [busy, setBusy] = useState(false);
  const passwordRef = useRef<HTMLInputElement>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!password) {
      setError("Type the admin password.");
      passwordRef.current?.focus();
      return;
    }
    setError("");
    setBusy(true);
    try {
      await adminLogIn(password);
      onSignedIn();
    } catch (failure) {
      setError(errorText(failure));
      passwordRef.current?.focus();
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="home__head">
        <h1>Site admin</h1>
        <p className="lead">For the person who runs this site. Teachers log in from the start page.</p>
      </div>
      <form className="classes__section admin__login" onSubmit={submit} noValidate>
        <div className="field">
          <label className="field__label" htmlFor="admin-password">
            Admin password
          </label>
          <input
            id="admin-password"
            ref={passwordRef}
            className="input"
            type="password"
            name="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            aria-required="true"
            aria-invalid={error !== ""}
            aria-describedby="admin-password-help"
          />
          <p
            id="admin-password-help"
            className={error ? "field__help field__help--error" : "field__help"}
            role={error ? "alert" : undefined}
          >
            {error || "The one set where the site is hosted."}
          </p>
        </div>
        <button type="submit" className="btn btn--primary" disabled={busy} aria-busy={busy}>
          {busy ? "Checking…" : "Log in"}
        </button>
      </form>
    </>
  );
}

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : word.endsWith("s") ? "es" : "s"}`;
}

function day(seconds: number): string {
  return new Date(seconds * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

/** What is going on in a class at this moment, or an empty string when nobody is in it. */
function liveText(item: AdminClass): string {
  if (item.online === 0) return item.teacherHere ? "Teacher at the desk" : "";
  return `${item.online} online${item.teacherHere ? ", teacher at the desk" : ", no teacher"}`;
}

// A row waiting for its second click, or for a new password to be typed.
type Asking = { kind: "end"; code: string } | { kind: "delete" | "password"; id: string } | null;

function AdminPage({ onSignedOut }: { onSignedOut: () => void }) {
  const [data, setData] = useState<AdminOverview | null>(null);
  const [error, setError] = useState("");
  const [asking, setAsking] = useState<Asking>(null);
  const [busy, setBusy] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [said, setSaid] = useState("");

  const load = useCallback(async () => {
    try {
      setData(await adminOverview());
      setError("");
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 401) onSignedOut(); // the pass has run out
      else setError(errorText(failure));
    }
  }, [onSignedOut]);

  // The lists keep themselves fresh while the page is being looked at.
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  /** Runs one admin action, then reloads the lists. */
  const act = async (key: string, action: () => Promise<unknown>, done: string) => {
    setBusy(key);
    setSaid("");
    try {
      await action();
      setAsking(null);
      setSaid(done);
      await load();
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 401) onSignedOut();
      else setError(errorText(failure));
    } finally {
      setBusy("");
    }
  };

  const savePassword = (event: FormEvent, teacher: AdminTeacher) => {
    event.preventDefault();
    if (newPassword.length < MIN_PASSWORD) {
      setError(`A password needs at least ${MIN_PASSWORD} characters.`);
      return;
    }
    void act(
      `password:${teacher.id}`,
      () => adminSetPassword(teacher.id, newPassword),
      `${teacher.name} has a new password and is signed out everywhere. Tell them what it is.`,
    );
  };

  const leave = async () => {
    try {
      await adminLogOut();
    } finally {
      onSignedOut();
    }
  };

  const classes = data?.classes ?? [];
  // Accounts waiting for approval come first: they are the ones that need something done.
  const teachers = [...(data?.teachers ?? [])].sort((a, b) => Number(a.approved) - Number(b.approved));
  const waiting = teachers.filter((teacher) => !teacher.approved).length;
  const online = classes.reduce((sum, item) => sum + item.online, 0);

  return (
    <>
      <TopBar>
        <span className="bar__who">Admin</span>
        <button type="button" className="btn" onClick={() => void leave()}>
          Log out
        </button>
      </TopBar>
      <main className="classes">
        <div className="home__head">
          <h1>Site admin</h1>
          <p className="lead">Every class and every teacher account on this site.</p>
        </div>

        {error && (
          <p className="notice" role="alert">
            {error}
          </p>
        )}
        <p className="visually-hidden" role="status">
          {said}
        </p>

        {data === null ? (
          !error && <span className="skeleton skeleton--text" aria-busy="true" />
        ) : (
          <>
            <dl className="figures admin__figures">
              <div className="figure">
                <dt>Teacher accounts</dt>
                <dd>{teachers.length}</dd>
              </div>
              <div className="figure">
                <dt>Classes</dt>
                <dd>{classes.length}</dd>
              </div>
              <div className="figure">
                <dt>Students online now</dt>
                <dd>{online}</dd>
              </div>
            </dl>
            {said && <p className="admin__said">{said}</p>}

            <section className="classes__section" aria-labelledby="admin-classes-title">
              <h2 id="admin-classes-title">Classes</h2>
              {classes.length === 0 ? (
                <p className="classes__none">No classes on the site.</p>
              ) : (
                <ul className="courses">
                  {classes.map((item) => {
                    const live = liveText(item);
                    const ending = busy === `end:${item.code}`;
                    return (
                      <li key={item.code} className="course">
                        <div className="course__about">
                          <h3 className="course__title">
                            {item.title}{" "}
                            <span className="course__kind">{item.language === "web" ? "Web pages" : "Python"}</span>
                          </h3>
                          <p className="course__meta">
                            <span className="mono">{item.code}</span> · {item.teacherName || "No teacher"} ·{" "}
                            {item.rows * item.cols} seats · {plural(item.students, "student")}
                          </p>
                          {live && <p className="status status--live">{live}</p>}
                        </div>
                        <div className="course__actions">
                          {asking?.kind === "end" && asking.code === item.code ? (
                            <>
                              <span className="status status--warn">End this class and delete its work?</span>
                              <button
                                type="button"
                                className="btn"
                                onClick={() =>
                                  void act(`end:${item.code}`, () => adminEndClass(item.code), `${item.title} has been ended.`)
                                }
                                disabled={ending}
                                aria-busy={ending}
                              >
                                {ending ? "Ending…" : "Yes, end it"}
                              </button>
                              <button type="button" className="btn" onClick={() => setAsking(null)}>
                                Keep
                              </button>
                            </>
                          ) : (
                            <button type="button" className="btn" onClick={() => setAsking({ kind: "end", code: item.code })}>
                              End class
                            </button>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>

            <section className="classes__section" aria-labelledby="admin-teachers-title">
              <h2 id="admin-teachers-title">Teachers</h2>
              <p className="admin__note">
                Passwords are kept scrambled, so nobody can read them, not even here. When a teacher forgets theirs,
                set a new one and tell them.
              </p>
              {data.approval && (
                <p className={waiting > 0 ? "admin__note admin__flag" : "admin__note"}>
                  {waiting > 0
                    ? `${plural(waiting, "account")} ${waiting === 1 ? "is" : "are"} waiting for your approval.`
                    : "A new account cannot make classes until you approve it here."}
                </p>
              )}
              {teachers.length === 0 ? (
                <p className="classes__none">Nobody has made an account.</p>
              ) : (
                <ul className="courses">
                  {teachers.map((teacher) => {
                    const mine = asking !== null && asking.kind !== "end" && asking.id === teacher.id ? asking.kind : null;
                    const blocking = busy === `block:${teacher.id}`;
                    return (
                      <li key={teacher.id} className="course">
                        <div className="course__about">
                          <h3 className="course__title">
                            {teacher.name}{" "}
                            {!teacher.approved && <span className="course__kind admin__flag">Waiting for approval</span>}
                            {teacher.blocked && <span className="course__kind admin__flag">Blocked</span>}
                          </h3>
                          <p className="course__meta">
                            <span className="mono">{teacher.email}</span> · joined {day(teacher.createdAt)} ·{" "}
                            {plural(teacher.classes, "class")}
                          </p>
                        </div>
                        <div className="course__actions">
                          {mine === "delete" && (
                            <>
                              <span className="status status--warn">Delete this account and all its classes?</span>
                              <button
                                type="button"
                                className="btn"
                                onClick={() =>
                                  void act(
                                    `delete:${teacher.id}`,
                                    () => adminDeleteTeacher(teacher.id),
                                    `${teacher.name}’s account has been deleted.`,
                                  )
                                }
                                disabled={busy === `delete:${teacher.id}`}
                                aria-busy={busy === `delete:${teacher.id}`}
                              >
                                {busy === `delete:${teacher.id}` ? "Deleting…" : "Yes, delete"}
                              </button>
                              <button type="button" className="btn" onClick={() => setAsking(null)}>
                                Keep
                              </button>
                            </>
                          )}
                          {mine === "password" && (
                            <form className="admin__password" onSubmit={(event) => savePassword(event, teacher)} noValidate>
                              <label className="visually-hidden" htmlFor={`password-${teacher.id}`}>
                                New password for {teacher.name}
                              </label>
                              <input
                                id={`password-${teacher.id}`}
                                className="input"
                                name="new-password"
                                value={newPassword}
                                onChange={(event) => setNewPassword(event.target.value)}
                                placeholder="New password"
                                autoComplete="off"
                                spellCheck={false}
                                maxLength={200}
                                autoFocus
                              />
                              <button
                                type="submit"
                                className="btn btn--primary"
                                disabled={busy === `password:${teacher.id}`}
                                aria-busy={busy === `password:${teacher.id}`}
                              >
                                Save
                              </button>
                              <button type="button" className="btn" onClick={() => setAsking(null)}>
                                Cancel
                              </button>
                            </form>
                          )}
                          {mine === null && (
                            <>
                              {!teacher.approved && (
                                <button
                                  type="button"
                                  className="btn btn--primary"
                                  onClick={() =>
                                    void act(
                                      `approve:${teacher.id}`,
                                      () => adminApprove(teacher.id),
                                      `${teacher.name} is approved and can make classes.`,
                                    )
                                  }
                                  disabled={busy === `approve:${teacher.id}`}
                                  aria-busy={busy === `approve:${teacher.id}`}
                                >
                                  Approve
                                </button>
                              )}
                              <button
                                type="button"
                                className="btn"
                                onClick={() =>
                                  void act(
                                    `block:${teacher.id}`,
                                    () => adminBlock(teacher.id, !teacher.blocked),
                                    teacher.blocked
                                      ? `${teacher.name} can log in again.`
                                      : `${teacher.name} is blocked and signed out.`,
                                  )
                                }
                                disabled={blocking}
                                aria-busy={blocking}
                              >
                                {teacher.blocked ? "Unblock" : "Block"}
                              </button>
                              <button
                                type="button"
                                className="btn"
                                onClick={() => {
                                  setNewPassword("");
                                  setError("");
                                  setAsking({ kind: "password", id: teacher.id });
                                }}
                              >
                                New password
                              </button>
                              <button type="button" className="btn" onClick={() => setAsking({ kind: "delete", id: teacher.id })}>
                                Delete
                              </button>
                            </>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
          </>
        )}
      </main>
    </>
  );
}
