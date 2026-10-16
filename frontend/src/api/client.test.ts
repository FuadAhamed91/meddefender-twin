import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, errorMessage, setCsrfToken } from "./client";

const fetchMock = vi.fn<typeof fetch>();

function json(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
}

function sentHeaders(call = 0): Record<string, string> {
  return (fetchMock.mock.calls[call][1]?.headers ?? {}) as Record<string, string>;
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  setCsrfToken(null);
  document.cookie = "md_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
});

afterEach(() => {
  fetchMock.mockReset();
  vi.unstubAllGlobals();
});

describe("api client", () => {
  it("sends the CSRF token on state-changing requests only", async () => {
    setCsrfToken("token-123");
    fetchMock.mockImplementation(async () => json(200, { ok: true }));
    await api.get("/api/v1/assets");
    await api.post("/api/v1/incidents/1/notes", { note: "checked" });
    expect(sentHeaders(0)["X-CSRF-Token"]).toBeUndefined();
    expect(sentHeaders(1)["X-CSRF-Token"]).toBe("token-123");
    expect(fetchMock.mock.calls[1][1]?.credentials).toBe("same-origin");
  });

  it("falls back to the CSRF cookie after a page reload", async () => {
    document.cookie = "md_csrf=from-cookie";
    fetchMock.mockImplementation(async () => json(200, {}));
    await api.post("/api/v1/simulation/generator", { enabled: false });
    expect(sentHeaders()["X-CSRF-Token"]).toBe("from-cookie");
  });

  it("turns error envelopes into ApiError with the correlation id", async () => {
    fetchMock.mockResolvedValue(
      json(403, { error: { code: "FORBIDDEN", message: "Requires SECURITY_ADMIN.", details: null, correlation_id: "abcdef12-3456" } }),
    );
    const error = await api.post("/api/v1/containment/plans/1/apply", {}).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 403, code: "FORBIDDEN", correlationId: "abcdef12-3456" });
    expect(errorMessage(error)).toBe("Requires SECURITY_ADMIN. (ref abcdef12)");
  });

  it("returns undefined for empty 204 responses", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await expect(api.post("/api/v1/auth/logout")).resolves.toBeUndefined();
  });
});
