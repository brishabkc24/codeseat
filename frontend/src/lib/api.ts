import type { ClassInfo, ClassSummary, Language, Teacher } from "./protocol";

export class ApiError extends Error {
  /** The HTTP status, or 0 when the server could not be reached. */
  status: number;

  constructor(message: string, status = 0) {
    super(message);
    this.status = status;
  }
}

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
    throw new ApiError(detail || `The server answered with an error (${response.status}).`, response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

/** What to tell the user about a failed request. */
export function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong. Try again.";
}

function posting(body: unknown): RequestInit {
  return { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

// ---- teachers: the session lives in a cookie the browser sends by itself

export async function signUp(name: string, email: string, password: string): Promise<Teacher> {
  const reply = await request<{ teacher: Teacher }>("/api/teachers", posting({ name, email, password }));
  return reply.teacher;
}

export async function logIn(email: string, password: string): Promise<Teacher> {
  const reply = await request<{ teacher: Teacher }>("/api/session", posting({ email, password }));
  return reply.teacher;
}

export function logOut(): Promise<void> {
  return request<void>("/api/session", { method: "DELETE" });
}

/** The signed-in teacher, or null when this browser has no session. */
export async function whoAmI(): Promise<Teacher | null> {
  const reply = await request<{ teacher: Teacher | null }>("/api/session");
  return reply.teacher;
}

// ---- classes

export async function listClasses(): Promise<ClassSummary[]> {
  const reply = await request<{ classes: ClassSummary[] }>("/api/classes");
  return reply.classes;
}

export function createClass(title: string, rows: number, cols: number, language: Language): Promise<ClassInfo> {
  return request<ClassInfo>("/api/classes", posting({ title, rows, cols, language }));
}

export function deleteClass(code: string): Promise<void> {
  return request<void>(`/api/classes/${encodeURIComponent(code)}`, { method: "DELETE" });
}

export function findClass(code: string) {
  return request<ClassInfo & { seatsTaken: number }>(`/api/classes/${encodeURIComponent(code)}`);
}

// ---- the site's admin: a separate sign-in, with its own cookie

export type AdminTeacher = Teacher & { createdAt: number; blocked: boolean; classes: number };

/** A class as the admin sees it: whose it is, and who is in it at this moment. */
export type AdminClass = ClassSummary & { teacherId: string; teacherName: string; online: number; teacherHere: boolean };

export type AdminOverview = { teachers: AdminTeacher[]; classes: AdminClass[] };

/** `configured` is false when the site has no admin password, which switches the page off. */
export type AdminSession = { configured: boolean; admin: boolean };

export function adminSession(): Promise<AdminSession> {
  return request<AdminSession>("/api/admin/session");
}

export function adminLogIn(password: string): Promise<AdminSession> {
  return request<AdminSession>("/api/admin/session", posting({ password }));
}

export function adminLogOut(): Promise<void> {
  return request<void>("/api/admin/session", { method: "DELETE" });
}

export function adminOverview(): Promise<AdminOverview> {
  return request<AdminOverview>("/api/admin/overview");
}

export function adminEndClass(code: string): Promise<void> {
  return request<void>(`/api/admin/classes/${encodeURIComponent(code)}`, { method: "DELETE" });
}

export function adminBlock(teacherId: string, blocked: boolean): Promise<{ blocked: boolean }> {
  return request<{ blocked: boolean }>(`/api/admin/teachers/${encodeURIComponent(teacherId)}/block`, posting({ blocked }));
}

export function adminSetPassword(teacherId: string, password: string): Promise<void> {
  return request<void>(`/api/admin/teachers/${encodeURIComponent(teacherId)}/password`, posting({ password }));
}

export function adminDeleteTeacher(teacherId: string): Promise<void> {
  return request<void>(`/api/admin/teachers/${encodeURIComponent(teacherId)}`, { method: "DELETE" });
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
