import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "./client";

interface Call {
  url: string;
  method: string;
  body: unknown;
}

const calls: Call[] = [];
let storage: Record<string, string> = {};

function reply(data: unknown = null, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify({ ok: true, data }), { headers: { "Content-Type": "application/json", ...headers } });
}

beforeEach(() => {
  calls.length = 0;
  storage = {};
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => storage[key] ?? null,
    setItem: (key: string, value: string) => {
      storage[key] = value;
    },
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const raw = init.body;
      calls.push({ url, method: init.method ?? "GET", body: typeof raw === "string" ? JSON.parse(raw) : raw });
      return reply({ comments: [], authors: [], count: 0 });
    }),
  );
});

afterEach(() => vi.unstubAllGlobals());

describe("comment requests", () => {
  it("read the list", async () => {
    await api.comments("d1");
    expect(calls).toEqual([{ url: "/api/documents/d1/comments", method: "GET", body: undefined }]);
  });

  it("create, edit and delete a comment", async () => {
    await api.addComment("d1", { page: 2, kind: "note", point: [36, 36], text: "Hi", author: "Ann" });
    await api.editComment("d1", 2, 17, { text: "Changed" });
    await api.deleteComment("d1", 2, 17);
    expect(calls).toEqual([
      { url: "/api/documents/d1/comments", method: "POST", body: { page: 2, kind: "note", point: [36, 36], text: "Hi", author: "Ann" } },
      { url: "/api/documents/d1/comments/2/17", method: "PATCH", body: { text: "Changed" } },
      { url: "/api/documents/d1/comments/2/17", method: "DELETE", body: undefined },
    ]);
  });

  it("reply and set a status or a checkmark, naming who did it", async () => {
    await api.replyToComment("d1", 0, 5, "Agreed", "Bob");
    await api.setCommentStatus("d1", 0, 5, { status: "accepted", author: "Bob" });
    await api.setCommentStatus("d1", 0, 5, { checked: true, author: "Bob" });
    expect(calls.map((c) => [c.method, c.url, c.body])).toEqual([
      ["POST", "/api/documents/d1/comments/0/5/replies", { text: "Agreed", author: "Bob" }],
      ["PUT", "/api/documents/d1/comments/0/5/status", { status: "accepted", author: "Bob" }],
      ["PUT", "/api/documents/d1/comments/0/5/status", { checked: true, author: "Bob" }],
    ]);
  });

  it("upload an XFDF file as a form", async () => {
    const file = new File(["<xfdf/>"], "c.xfdf", { type: "application/vnd.adobe.xfdf" });
    await api.importXfdf("d1", file);
    expect(calls[0].url).toBe("/api/documents/d1/comments/xfdf");
    expect(calls[0].method).toBe("POST");
    expect(calls[0].body).toBeInstanceOf(FormData);
    expect((calls[0].body as FormData).get("file")).toBeInstanceOf(File);
  });

  it("download the XFDF export with the server's file name", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("<xfdf/>", { headers: { "Content-Disposition": 'attachment; filename="report.xfdf"' } })),
    );
    const file = await api.exportXfdf("d1");
    expect(file.filename).toBe("report.xfdf");
    expect(await file.blob.text()).toBe("<xfdf/>");
  });
});

describe("signing new annotations", () => {
  const style = { color: "#ffd400", fill: null, opacity: 1, width: 1, dashed: false, contents: "", author: "" };

  it("uses the remembered name when the caller gave none", async () => {
    storage["pdfstudio.commentAuthor"] = "Carol";
    await api.addAnnotation("d1", { page: 0, kind: "rect", style });
    expect((calls[0].body as { style: { author: string } }).style.author).toBe("Carol");
  });

  it("keeps a name the caller set, and stays unsigned when there is none", async () => {
    storage["pdfstudio.commentAuthor"] = "Carol";
    await api.addAnnotation("d1", { page: 0, kind: "rect", style: { ...style, author: "Dan" } });
    expect((calls[0].body as { style: { author: string } }).style.author).toBe("Dan");
    storage = {};
    await api.addAnnotation("d1", { page: 0, kind: "rect", style });
    expect((calls[1].body as { style: { author: string } }).style.author).toBe("");
  });
});
