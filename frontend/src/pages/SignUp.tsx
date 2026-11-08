import { type FormEvent, useRef, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { TopBar } from "../components/TopBar";
import { ApiError, errorText, signUp } from "../lib/api";
import { useSession } from "../lib/session";

type Field = "name" | "email" | "password";
type Problem = { field: Field; text: string };

export function SignUp() {
  const navigate = useNavigate();
  const session = useSession();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [problem, setProblem] = useState<Problem | null>(null);
  const [busy, setBusy] = useState(false);
  const refs = {
    name: useRef<HTMLInputElement>(null),
    email: useRef<HTMLInputElement>(null),
    password: useRef<HTMLInputElement>(null),
  };

  if (session.teacher) return <Navigate to="/teach" replace />;

  const fail = (field: Field, text: string) => {
    setProblem({ field, text });
    refs[field].current?.focus();
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return fail("name", "Type the name your students know you by.");
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())) return fail("email", "That does not look like an email address.");
    if (password.length < 8) return fail("password", "Use a password of at least 8 characters.");
    setProblem(null);
    setBusy(true);
    try {
      session.signedIn(await signUp(name.trim(), email.trim(), password));
      navigate("/teach");
    } catch (error) {
      // The server names the field for the two refusals it can make about one.
      const field: Field = error instanceof ApiError && error.status === 409 ? "email" : "name";
      fail(field, errorText(error));
    } finally {
      setBusy(false);
    }
  };

  const help = (field: Field, usual: string) => (
    <p
      id={`signup-${field}-help`}
      className={problem?.field === field ? "field__help field__help--error" : "field__help"}
      role={problem?.field === field ? "alert" : undefined}
    >
      {problem?.field === field ? problem.text : usual}
    </p>
  );

  return (
    <>
      <TopBar />
      <main className="home">
        <div className="home__head">
          <h1>Create a teacher account</h1>
          <p className="lead">Your classes stay with it: the lesson, the seats and every student’s code.</p>
        </div>
        <form className="home__single" onSubmit={submit} noValidate>
          <div className="field">
            <label className="field__label" htmlFor="signup-name">
              Your name
            </label>
            <input
              id="signup-name"
              ref={refs.name}
              className="input"
              name="name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              maxLength={60}
              autoComplete="name"
              aria-required="true"
              aria-invalid={problem?.field === "name"}
              aria-describedby="signup-name-help"
            />
            {help("name", "As your students know you.")}
          </div>
          <div className="field">
            <label className="field__label" htmlFor="signup-email">
              Email
            </label>
            <input
              id="signup-email"
              ref={refs.email}
              className="input"
              type="email"
              name="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              maxLength={200}
              autoComplete="email"
              aria-required="true"
              aria-invalid={problem?.field === "email"}
              aria-describedby="signup-email-help"
            />
            {help("email", "You log in with it. Nothing is sent to it.")}
          </div>
          <div className="field">
            <label className="field__label" htmlFor="signup-password">
              Password
            </label>
            <input
              id="signup-password"
              ref={refs.password}
              className="input"
              type="password"
              name="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              maxLength={200}
              autoComplete="new-password"
              aria-required="true"
              aria-invalid={problem?.field === "password"}
              aria-describedby="signup-password-help"
            />
            {help("password", "At least 8 characters.")}
          </div>
          <button type="submit" className="btn btn--primary" disabled={busy} aria-busy={busy}>
            {busy ? "Creating…" : "Create account"}
          </button>
          <p className="home__alt">
            Already have one? <Link to="/">Log in</Link>.
          </p>
        </form>
      </main>
    </>
  );
}
