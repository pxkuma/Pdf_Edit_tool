import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PageModel } from "../api/types";

const pageModel = vi.fn();
vi.mock("../api/client", () => ({ api: { pageModel: (...args: unknown[]) => pageModel(...args) } }));

import { invalidatePageModels, loadPageModel } from "./pageModel";

const modelFor = (token: string) => ({ token }) as unknown as PageModel;

describe("loadPageModel", () => {
  beforeEach(() => {
    pageModel.mockReset();
    invalidatePageModels();
  });

  it("asks the server for the revision it needs and caches the answer", async () => {
    pageModel.mockResolvedValue(modelFor("t1"));
    const first = await loadPageModel("doc", 0, "t1");
    await loadPageModel("doc", 0, "t1");
    expect(first.token).toBe("t1");
    expect(pageModel).toHaveBeenCalledTimes(1);
    expect(pageModel).toHaveBeenCalledWith("doc", 0, "t1");
  });

  it("refuses a model of another revision and does not cache it", async () => {
    pageModel.mockResolvedValueOnce(modelFor("newer"));
    await expect(loadPageModel("doc", 0, "t1")).rejects.toThrow(/changed/);
    pageModel.mockResolvedValueOnce(modelFor("t1"));
    await expect(loadPageModel("doc", 0, "t1")).resolves.toMatchObject({ token: "t1" });
    expect(pageModel).toHaveBeenCalledTimes(2);
  });

  it("does not cache failures", async () => {
    pageModel.mockRejectedValueOnce(new Error("offline"));
    await expect(loadPageModel("doc", 1, "t1")).rejects.toThrow("offline");
    pageModel.mockResolvedValueOnce(modelFor("t1"));
    await expect(loadPageModel("doc", 1, "t1")).resolves.toBeTruthy();
  });
});
