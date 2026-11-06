import type { ClassInfo } from "./protocol";

export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ApiError("Could not reach the CodeSeat server. Check your connection and try again.");
  }
  if (!response.ok) {
    let detail = "";
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // The error had no readable body; the status code below is all we know.
    }
    throw new ApiError(detail || `The server answered with an error (${response.status}).`);
  }
  return response.json() as Promise<T>;
}

export function createClass(title: string, rows: number, cols: number) {
  return request<ClassInfo & { teacherToken: string }>("/api/classes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, rows, cols }),
  });
}

export function findClass(code: string) {
  return request<ClassInfo & { seatsTaken: number }>(`/api/classes/${encodeURIComponent(code)}`);
}

// ---- what this browser remembers about its classes

export type StudentIdentity = { name: string; id: string | null };

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null; // storage is blocked; the class still works until the tab closes
  }
}

function write(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // see read()
  }
}

export function saveTeacherToken(code: string, token: string): void {
  write(`codeseat.teacher.${code}`, token);
}

export function loadTeacherToken(code: string): string | null {
  return read(`codeseat.teacher.${code}`);
}

export function saveStudent(code: string, identity: StudentIdentity): void {
  write(`codeseat.student.${code}`, JSON.stringify(identity));
}

export function loadStudent(code: string): StudentIdentity | null {
  const raw = read(`codeseat.student.${code}`);
  if (!raw) return null;
  try {
    const value = JSON.parse(raw);
    if (typeof value.name !== "string" || !value.name) return null;
    return { name: value.name, id: typeof value.id === "string" ? value.id : null };
  } catch {
    return null;
  }
}
