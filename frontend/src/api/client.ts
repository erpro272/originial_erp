/**
 * Typed API client generated from the backend's OpenAPI schema (no hand-written API types).
 * Access token lives in memory only; the refresh token is an httpOnly cookie the browser
 * sends to /api/auth/refresh. A 401 triggers one silent refresh, then the request retries.
 */
import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
export type Me = Schemas["MeResponse"];
export type Company = Schemas["CompanyOut"];
export type Permission = Schemas["Permission"];

let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;
const listeners = new Set<() => void>();

export function setAccessToken(token: string | null) {
  accessToken = token;
}
export function getAccessToken() {
  return accessToken;
}
/** Called when the session can no longer be refreshed (signed out elsewhere, expired). */
export function onSessionExpired(fn: () => void) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export async function refreshSession(): Promise<boolean> {
  refreshing ??= (async () => {
    try {
      const res = await fetch(`${location.origin}/api/auth/refresh`, {
        method: "POST",
        credentials: "same-origin",
      });
      if (!res.ok) return false;
      setAccessToken(((await res.json()) as Schemas["TokenResponse"]).access_token);
      return true;
    } catch {
      return false;
    } finally {
      queueMicrotask(() => (refreshing = null));
    }
  })();
  return refreshing;
}

function withAuth(req: Request): Request {
  const r = new Request(req);
  if (accessToken) r.headers.set("Authorization", `Bearer ${accessToken}`);
  return r;
}

/** Calls whose 401 means "bad credentials", not "access token expired". */
const NO_RETRY = new Set(["/api/auth/login", "/api/auth/refresh", "/api/auth/logout"]);

async function authFetch(input: Request): Promise<Response> {
  const retry = input.clone();
  const res = await fetch(withAuth(input));
  const path = new URL(input.url, location.origin).pathname;
  if (res.status !== 401 || NO_RETRY.has(path)) return res;
  if (await refreshSession()) return fetch(withAuth(retry));
  setAccessToken(null);
  listeners.forEach((fn) => fn());
  return res;
}

export const api = createClient<paths>({
  baseUrl: typeof location === "undefined" ? "http://localhost" : location.origin,
  fetch: authFetch,
  credentials: "same-origin",
});

/** Error shape returned by every API error: `{ error: { code, message, details } }`. */
export interface ApiErrorBody {
  error: { code: string; message: string; details?: Record<string, unknown> };
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

/** Unwraps an openapi-fetch result: returns data, or throws ApiError with the server message. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error !== undefined || result.data === undefined) {
    const body = result.error as Partial<ApiErrorBody> | undefined;
    throw new ApiError(
      result.response.status,
      body?.error?.code ?? "unknown",
      body?.error?.message ?? `Request failed (${result.response.status})`,
      body?.error?.details ?? {},
    );
  }
  return result.data;
}
