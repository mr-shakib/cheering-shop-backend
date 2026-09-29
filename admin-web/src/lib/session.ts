/* The signed-in administrator's tokens and profile.
 *
 * "Remember me" decides the storage: localStorage survives the browser being
 * closed, sessionStorage lives as long as the tab. Either way the refresh
 * token rotates on every use, so exactly one place may hold it — see
 * refreshSession() in api.ts for how concurrent refreshes are serialised.
 */
import { useSyncExternalStore } from "react";

export interface SessionUser {
  id: string;
  role: string;
  email: string | null;
  phone: string | null;
  full_name: string | null;
  avatar_url: string | null;
}

export interface Session {
  accessToken: string;
  refreshToken: string;
  user: SessionUser;
}

const KEY = "crshop.admin.session";

type Listener = () => void;
const listeners = new Set<Listener>();

function stores(): Storage[] {
  const out: Storage[] = [];
  try {
    out.push(window.localStorage);
  } catch {
    /* storage disabled */
  }
  try {
    out.push(window.sessionStorage);
  } catch {
    /* storage disabled */
  }
  return out;
}

function read(): { session: Session; storage: Storage } | null {
  for (const storage of stores()) {
    try {
      const raw = storage.getItem(KEY);
      if (raw) return { session: JSON.parse(raw) as Session, storage };
    } catch {
      /* unreadable entry: treat as signed out */
    }
  }
  return null;
}

let current: Session | null = read()?.session ?? null;

function emit() {
  for (const l of listeners) l();
}

export function getSession(): Session | null {
  return current;
}

/** Re-read storage. Another tab (same localStorage) may have rotated the tokens. */
export function reloadSession(): Session | null {
  current = read()?.session ?? null;
  return current;
}

export function saveSession(session: Session, remember?: boolean) {
  const existing = read();
  // A refresh keeps the storage the session already lives in; only a fresh
  // sign-in chooses one.
  const target =
    remember === undefined && existing
      ? existing.storage
      : remember
        ? window.localStorage
        : window.sessionStorage;
  for (const s of stores()) {
    if (s !== target) s.removeItem(KEY);
  }
  target.setItem(KEY, JSON.stringify(session));
  current = session;
  emit();
}

export function updateSessionUser(user: SessionUser) {
  if (!current) return;
  saveSession({ ...current, user });
}

export function clearSession() {
  for (const s of stores()) s.removeItem(KEY);
  current = null;
  emit();
}

function subscribe(listener: Listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

// A sign-out in another tab signs this one out too.
window.addEventListener("storage", (e) => {
  if (e.key === KEY || e.key === null) {
    current = read()?.session ?? null;
    emit();
  }
});

export function useSession(): Session | null {
  return useSyncExternalStore(subscribe, getSession);
}
