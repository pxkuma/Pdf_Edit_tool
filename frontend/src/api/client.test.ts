import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "./client";

afterEach(() => vi.unstubAllGlobals());

describe("network failures", () => {
  it("are reported as a friendly ApiError by normal requests", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(api.info("doc")).rejects.toMatchObject({ code: "network", status: 0 });
  });

  it("are reported as a friendly ApiError by downloads too", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const failure = await api.exportPdf("doc", {}).catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(ApiError);
    expect(failure).toMatchObject({ code: "network", message: expect.stringMatching(/reach the PDF Studio server/) });
  });

  it("still return the file and its name on success", async () => {
    const response = new Response("pdf", { headers: { "Content-Disposition": "attachment; filename=\"a.pdf\"" } });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
    const file = await api.exportPdf("doc", {});
    expect(file.filename).toBe("a.pdf");
    expect(await file.blob.text()).toBe("pdf");
  });
});
