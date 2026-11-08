import { type ReactNode, createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { logOut, whoAmI } from "./api";
import type { Teacher } from "./protocol";

export type Session = {
  /** The signed-in teacher, or null: nobody, or not known yet (see `known`). */
  teacher: Teacher | null;
  /** False until the server has said whether this browser is signed in. */
  known: boolean;
  signedIn: (teacher: Teacher) => void;
  signOut: () => Promise<void>;
};

const SessionContext = createContext<Session | null>(null);

/** Asks the server once who is signed in, then keeps the answer for every page. */
export function SessionProvider({ children }: { children: ReactNode }) {
  const [teacher, setTeacher] = useState<Teacher | null>(null);
  const [known, setKnown] = useState(false);

  useEffect(() => {
    let cancelled = false;
    whoAmI().then(
      (found) => {
        if (cancelled) return;
        setTeacher(found);
        setKnown(true);
      },
      () => {
        // The server could not be reached; pages that need a teacher will say so.
        if (!cancelled) setKnown(true);
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);

  const signOut = useCallback(async () => {
    try {
      await logOut();
    } finally {
      setTeacher(null);
    }
  }, []);

  const value = useMemo<Session>(
    () => ({ teacher, known, signedIn: setTeacher, signOut }),
    [teacher, known, signOut],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession needs a SessionProvider above it.");
  return session;
}
