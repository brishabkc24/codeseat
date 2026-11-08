import { type FormEvent, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { TopBar } from "../components/TopBar";
import { errorText, findClass, loadStudent, logIn, saveStudent } from "../lib/api";
import { useSession } from "../lib/session";

type JoinError = { field: "code" | "name"; text: string };

export function Home() {
  const navigate = useNavigate();
  const location = useLocation();
  const linkedCode = (useParams().code ?? "").toUpperCase();
  // Pages that need a teacher send people here with a word about why.
  const notice = (location.state as { notice?: string } | null)?.notice ?? "";

  const [code, setCode] = useState(linkedCode);
  const [name, setName] = useState("");
  const [joinError, setJoinError] = useState<JoinError | null>(null);
  const [joining, setJoining] = useState(false);
  const codeRef = useRef<HTMLInputElement>(null);
  const nameRef = useRef<HTMLInputElement>(null);

  const join = async (event: FormEvent) => {
    event.preventDefault();
    const cleanCode = code.trim().toUpperCase();
    const cleanName = name.trim();
    if (cleanCode.length !== 6) {
      setJoinError({ field: "code", text: "A class code has 6 characters. Check it with your teacher." });
      codeRef.current?.focus();
      return;
    }
    if (!cleanName) {
      setJoinError({ field: "name", text: "Type the name your teacher knows you by." });
      nameRef.current?.focus();
      return;
    }
    setJoinError(null);
    setJoining(true);
    try {
      await findClass(cleanCode);
      // Keep the id from an earlier visit, so the student gets the same seat back.
      saveStudent(cleanCode, { name: cleanName, id: loadStudent(cleanCode)?.id ?? null });
      navigate(`/class/${cleanCode}`, { state: { name: cleanName } });
    } catch (error) {
      setJoinError({ field: "code", text: errorText(error) });
      codeRef.current?.focus();
    } finally {
      setJoining(false);
    }
  };

  return (
    <>
      <TopBar />
      <main className="home">
        <div className="home__head">
          <h1>Live Python lessons, one seat each.</h1>
          <p className="lead">Students code beside the teacher, who sees every seat.</p>
        </div>

        {notice && (
          <p className="notice" role="status">
            {notice}
          </p>
        )}

        <div className="home__forms">
          <form className="home__form" onSubmit={join} noValidate>
            <h2>Join a class</h2>
            <div className="field">
              <label className="field__label" htmlFor="join-code">
                Class code
              </label>
              <input
                id="join-code"
                ref={codeRef}
                className="input input--mono"
                name="code"
                value={code}
                onChange={(event) => setCode(event.target.value.toUpperCase())}
                maxLength={6}
                autoComplete="off"
                autoCapitalize="characters"
                spellCheck={false}
                placeholder="K7M2QX"
                aria-required="true"
                aria-invalid={joinError?.field === "code"}
                aria-describedby="join-code-help"
              />
              <p
                id="join-code-help"
                className={joinError?.field === "code" ? "field__help field__help--error" : "field__help"}
                role={joinError?.field === "code" ? "alert" : undefined}
              >
                {joinError?.field === "code" ? joinError.text : "Six characters, from your teacher."}
              </p>
            </div>
            <div className="field">
              <label className="field__label" htmlFor="join-name">
                Your name
              </label>
              <input
                id="join-name"
                ref={nameRef}
                className="input"
                name="name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                maxLength={30}
                autoComplete="given-name"
                aria-required="true"
                aria-invalid={joinError?.field === "name"}
                aria-describedby="join-name-help"
              />
              <p
                id="join-name-help"
                className={joinError?.field === "name" ? "field__help field__help--error" : "field__help"}
                role={joinError?.field === "name" ? "alert" : undefined}
              >
                {joinError?.field === "name" ? joinError.text : "Shown on your seat."}
              </p>
            </div>
            <button type="submit" className="btn btn--primary" disabled={joining} aria-busy={joining}>
              {joining ? "Joining…" : "Join class"}
            </button>
          </form>

          <section className="home__form" aria-labelledby="teachers-title">
            <h2 id="teachers-title">Teachers</h2>
            <TeacherPanel />
          </section>
        </div>
      </main>
    </>
  );
}

/** Who is signed in, or the way in: a login form with a link to make an account. */
function TeacherPanel() {
  const navigate = useNavigate();
  const session = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const emailRef = useRef<HTMLInputElement>(null);

  if (!session.known) {
    return (
      <p className="field__help" role="status">
        Checking who is signed in…
      </p>
    );
  }

  if (session.teacher) {
    return (
      <>
        <p>
          Signed in as <strong>{session.teacher.name}</strong>.
        </p>
        <div className="home__actions">
          <Link className="btn btn--primary" to="/teach">
            Your classes
          </Link>
          <button type="button" className="btn" onClick={() => void session.signOut()}>
            Log out
          </button>
        </div>
      </>
    );
  }

  const login = async (event: FormEvent) => {
    event.preventDefault();
    if (!email.trim() || !password) {
      setError("Type your email and password.");
      emailRef.current?.focus();
      return;
    }
    setError("");
    setBusy(true);
    try {
      session.signedIn(await logIn(email.trim(), password));
      navigate("/teach");
    } catch (failure) {
      setError(errorText(failure));
      emailRef.current?.focus();
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="home__login" onSubmit={login} noValidate>
      <div className="field">
        <label className="field__label" htmlFor="login-email">
          Email
        </label>
        <input
          id="login-email"
          ref={emailRef}
          className="input"
          type="email"
          name="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          autoComplete="email"
          aria-required="true"
          aria-invalid={error !== ""}
        />
      </div>
      <div className="field">
        <label className="field__label" htmlFor="login-password">
          Password
        </label>
        <input
          id="login-password"
          className="input"
          type="password"
          name="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete="current-password"
          aria-required="true"
          aria-invalid={error !== ""}
        />
        <p
          className={error ? "field__help field__help--error" : "field__help"}
          role={error ? "alert" : undefined}
        >
          {error || "Your classes, their lessons and seats are kept with your account."}
        </p>
      </div>
      <button type="submit" className="btn btn--primary" disabled={busy} aria-busy={busy}>
        {busy ? "Logging in…" : "Log in"}
      </button>
      <p className="home__alt">
        New here? <Link to="/signup">Create a teacher account</Link>.
      </p>
    </form>
  );
}
