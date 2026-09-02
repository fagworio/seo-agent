import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";

afterEach(() => vi.unstubAllGlobals());

describe("api client", () => {
  it("builds the /api/v1 path and sends credentials", async () => {
    const spy = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true }) });
    vi.stubGlobal("fetch", spy);
    await api.get("/dashboard/today");
    expect(spy).toHaveBeenCalledWith(
      "/api/v1/dashboard/today",
      expect.objectContaining({ method: "GET", credentials: "include" }),
    );
  });

  it("throws ApiError with the stable code on non-ok", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 403,
        json: async () => ({ error: { code: "PERMISSION_DENIED", message: "x", request_id: "r1" } }),
      }),
    );
    await expect(api.get("/agents")).rejects.toMatchObject({
      code: "PERMISSION_DENIED",
      status: 403,
      requestId: "r1",
    });
  });

  it("sends the CSRF header on mutation when provided", async () => {
    const spy = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true }) });
    vi.stubGlobal("fetch", spy);
    await api.post("/actions/fp/execute", {}, "csrf-token");
    expect(spy).toHaveBeenCalledWith(
      "/api/v1/actions/fp/execute",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "X-CSRF-Token": "csrf-token" }),
      }),
    );
  });
});
