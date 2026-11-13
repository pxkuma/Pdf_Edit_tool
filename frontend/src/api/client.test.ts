import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, signForm } from "./client";

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

describe("sign request", () => {
  const base = {
    certificate: new File(["p12"], "me.p12"),
    password: "secret",
    reason: " Approved ",
    location: "",
    contact: "",
    timestampUrl: "",
    showDetails: true,
    image: null,
    utcOffset: 60,
  };

  it("sends a visible signature's page and box", () => {
    const form = signForm({ ...base, placement: { page: 2, rect: [10, 20.456, 110, 70] } });
    expect(form.get("page")).toBe("2");
    expect(form.get("rect")).toBe("10.00,20.46,110.00,70.00");
    expect(form.get("reason")).toBe("Approved");
    expect(form.get("utc_offset")).toBe("60");
    expect((form.get("certificate") as File).name).toBe("me.p12");
    expect(form.has("image")).toBe(false);
  });

  it("leaves page and box out of an invisible signature", () => {
    const form = signForm({ ...base, placement: null, image: new Blob(["png"]) });
    expect(form.has("page")).toBe(false);
    expect(form.has("rect")).toBe(false);
    expect(form.has("image")).toBe(true);
  });
});
