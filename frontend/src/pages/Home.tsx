import { type FormEvent, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { SeatMap } from "../components/SeatMap";
import { TopBar } from "../components/TopBar";
import { ApiError, createClass, findClass, loadStudent, saveStudent, saveTeacherToken } from "../lib/api";

const ROW_CHOICES = [1, 2, 3, 4, 5, 6, 7, 8];
const COL_CHOICES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];

type JoinError = { field: "code" | "name"; text: string };

function message(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong. Try again.";
}

export function Home() {
  const navigate = useNavigate();
  const linkedCode = (useParams().code ?? "").toUpperCase();

  const [code, setCode] = useState(linkedCode);
  const [name, setName] = useState("");
  const [joinError, setJoinError] = useState<JoinError | null>(null);
  const [joining, setJoining] = useState(false);
  const codeRef = useRef<HTMLInputElement>(null);
  const nameRef = useRef<HTMLInputElement>(null);

  const [title, setTitle] = useState("");
  const [rows, setRows] = useState(4);
  const [cols, setCols] = useState(6);
  const [startError, setStartError] = useState("");
  const [starting, setStarting] = useState(false);
  const titleRef = useRef<HTMLInputElement>(null);

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
      setJoinError({ field: "code", text: message(error) });
      codeRef.current?.focus();
    } finally {
      setJoining(false);
    }
  };

  const start = async (event: FormEvent) => {
    event.preventDefault();
    const cleanTitle = title.trim();
    if (!cleanTitle) {
      setStartError("Give the class a name, such as the lesson or the group.");
      titleRef.current?.focus();
      return;
    }
    setStartError("");
    setStarting(true);
    try {
      const room = await createClass(cleanTitle, rows, cols);
      saveTeacherToken(room.code, room.teacherToken);
      navigate(`/teach/${room.code}`, { state: { token: room.teacherToken } });
    } catch (error) {
      setStartError(message(error));
    } finally {
      setStarting(false);
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

          <form className="home__form" onSubmit={start} noValidate>
            <h2>Start a class</h2>
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
                <button type="submit" className="btn" disabled={starting} aria-busy={starting}>
                  {starting ? "Opening…" : "Open classroom"}
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
        </div>
      </main>
    </>
  );
}
