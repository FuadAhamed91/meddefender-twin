// Minimal fetch client. The session lives in an HttpOnly cookie the browser sends
// automatically; the CSRF token is echoed in a header on every state-changing request.

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;
  readonly correlationId: string | null;

  constructor(status: number, code: string, message: string, details: unknown, correlationId: string | null) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
    this.correlationId = correlationId;
  }
}

const CSRF_COOKIE = "md_csrf";
let csrfToken: string | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

function csrfFromCookie(): string | null {
  const match = document.cookie.split("; ").find((c) => c.startsWith(`${CSRF_COOKIE}=`));
  return match ? decodeURIComponent(match.slice(CSRF_COOKIE.length + 1)) : null;
}

type Method = "GET" | "POST" | "PATCH";

async function request<T>(method: Method, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") {
    const token = csrfToken ?? csrfFromCookie();
    if (token) headers["X-CSRF-Token"] = token;
  }
  const response = await fetch(path, {
    method,
    headers,
    credentials: "same-origin",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  const data = text ? JSON.parse(text) : undefined;
  if (!response.ok) {
    const err = data?.error ?? {};
    throw new ApiError(
      response.status,
      err.code ?? `HTTP_${response.status}`,
      err.message ?? response.statusText,
      err.details,
      err.correlation_id ?? response.headers.get("X-Correlation-ID"),
    );
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
};

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.correlationId ? `${error.message} (ref ${error.correlationId.slice(0, 8)})` : error.message;
  }
  return error instanceof Error ? error.message : "Something went wrong.";
}
