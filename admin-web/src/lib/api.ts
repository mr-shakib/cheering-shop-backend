/* Transport for /api/v1.
 *
 * Every response is the envelope {success, data, meta} or {success: false,
 * error: {code, message, details}}. `api()` unwraps it, refreshes an expired
 * access token once, and throws ApiError for everything else.
 */
import { clearSession, getSession, reloadSession, saveSession, type SessionUser } from "./session";

export const API_BASE = "/api/v1";

export interface PageMeta {
  total: number;
  limit: number;
  offset: number;
  page: number;
  has_more: boolean;
  [extra: string]: unknown;
}

export interface Page<T> {
  items: T[];
  meta: PageMeta;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: string[];
  readonly requestId: string | null;

  constructor(status: number, code: string, message: string, details: string[] = [], requestId: string | null = null) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }
}

export type Query = Record<string, string | number | boolean | null | undefined>;

/** `undefined`/`null` are left out; an empty string is sent as `k=`, which is
 * how the queues that default to one status ask for every status. */
export function queryString(query?: Query): string {
  if (!query) return "";
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null) continue;
    params.set(k, String(v));
  }
  const s = params.toString();
  return s ? `?${s}` : "";
}

interface RequestOptions {
  body?: unknown;
  query?: Query;
  signal?: AbortSignal;
  /** Skip the Authorization header and the refresh-on-401 dance. */
  anonymous?: boolean;
}

async function send(method: string, path: string, opts: RequestOptions, token: string | null): Promise<Response> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;
  return fetch(API_BASE + path + queryString(opts.query), {
    method,
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    signal: opts.signal,
  });
}

async function toError(res: Response): Promise<ApiError> {
  const requestId = res.headers.get("X-Request-ID");
  let json: { error?: { code?: string; message?: string; details?: string[] } } | null = null;
  try {
    json = await res.json();
  } catch {
    /* not JSON: a proxy error page, most likely */
  }
  const err = json?.error;
  if (err) {
    return new ApiError(res.status, err.code ?? "ERROR", err.message ?? `HTTP ${res.status}`, err.details ?? [], requestId);
  }
  const message =
    res.status >= 500
      ? "The server had a problem. Try again in a moment."
      : res.status === 0
        ? "Could not reach the server."
        : `Request failed (HTTP ${res.status}).`;
  return new ApiError(res.status, "HTTP_ERROR", message, [], requestId);
}

interface TokenPair {
  access_token: string;
  refresh_token: string;
}

export interface AuthResult {
  tokens: TokenPair;
  user: SessionUser;
}

/* The refresh token rotates on every use, and presenting a rotated one
 * revokes the whole session family. So refreshes are serialised — across tabs
 * too, via a Web Lock, because a remembered session shares localStorage — and
 * whoever gets the lock second checks whether someone already did the work. */
async function refreshSession(staleAccessToken: string): Promise<void> {
  const run = async () => {
    const session = reloadSession();
    if (!session) throw new ApiError(401, "UNAUTHORIZED", "Your session has ended. Sign in again.");
    if (session.accessToken !== staleAccessToken) return; // already refreshed
    const res = await send("POST", "/auth/refresh", { body: { refresh_token: session.refreshToken } }, null);
    if (!res.ok) throw await toError(res);
    const data = ((await res.json()) as { data: AuthResult | TokenPair }).data;
    const tokens = "tokens" in data ? data.tokens : data;
    const user = "user" in data ? data.user : session.user;
    saveSession({ accessToken: tokens.access_token, refreshToken: tokens.refresh_token, user });
  };
  if ("locks" in navigator && navigator.locks) {
    await navigator.locks.request("crshop.admin.refresh", run);
  } else {
    await run();
  }
}

async function request(method: string, path: string, opts: RequestOptions = {}): Promise<Response> {
  if (opts.anonymous) return send(method, path, opts, null);

  const token = getSession()?.accessToken ?? null;
  let res = await send(method, path, opts, token);
  if (res.status === 401 && token) {
    try {
      await refreshSession(token);
    } catch (e) {
      clearSession();
      throw e instanceof ApiError && e.status === 401
        ? new ApiError(401, "SESSION_ENDED", "Your session has ended. Sign in again.")
        : e;
    }
    res = await send(method, path, opts, getSession()?.accessToken ?? null);
  }
  return res;
}

async function unwrap<T>(res: Response): Promise<{ data: T; meta: PageMeta | Record<string, unknown> | undefined }> {
  if (!res.ok) throw await toError(res);
  if (res.status === 204) return { data: undefined as T, meta: undefined };
  const json = (await res.json()) as { success: boolean; data: T; meta?: PageMeta };
  if (json.success === false) throw await toError(res);
  return { data: json.data, meta: json.meta };
}

export async function api<T>(method: string, path: string, opts?: RequestOptions): Promise<T> {
  return (await unwrap<T>(await request(method, path, opts))).data;
}

export async function apiPage<T>(path: string, query?: Query, signal?: AbortSignal): Promise<Page<T>> {
  const { data, meta } = await unwrap<T[]>(await request("GET", path, { query, signal }));
  return {
    items: data,
    meta: (meta as PageMeta) ?? { total: data.length, limit: data.length, offset: 0, page: 1, has_more: false },
  };
}

export const get = <T>(path: string, query?: Query, signal?: AbortSignal) => api<T>("GET", path, { query, signal });
export const post = <T>(path: string, body?: unknown) => api<T>("POST", path, { body: body ?? {} });
export const patch = <T>(path: string, body: unknown) => api<T>("PATCH", path, { body });
export const del = <T>(path: string) => api<T>("DELETE", path);

/** Download a `format=csv` export: it needs the bearer token, so it cannot be a plain link. */
export async function downloadCsv(path: string, query: Query, fallbackName: string) {
  const res = await request("GET", path, { query: { ...query, format: "csv", limit: undefined, offset: undefined } });
  if (!res.ok) throw await toError(res);
  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const name = /filename="?([^";]+)"?/.exec(disposition)?.[1] ?? fallbackName;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.code === "VALIDATION_FAILED" && e.details.length) return e.details.join("; ");
    return e.message;
  }
  if (e instanceof Error) return e.message;
  return "Something went wrong.";
}

/** An unset filter: "" in the URL, left out of the request. */
export const opt = (v: string | null | undefined): string | undefined => (v ? v : undefined);
