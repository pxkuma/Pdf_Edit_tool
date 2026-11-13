import { describe, expect, it } from "vitest";
import type { SignatureReport, SignatureValidation } from "../api/types";
import { changesText, needsSignedEditConsent, signatureBanner, signedEditKey, signFormProblem, utcOffsetMinutes } from "./signatures";

const doc = (signatures: number) => ({ id: "abc", signatures });

function report(patch: Partial<SignatureReport>): SignatureReport {
  return {
    field: "Signature1", page: 0, rect: null, revision: 1, signer: null, signing_time: null, timestamp: null,
    timestamp_valid: null, reason: "", location: "", certified: false, intact: true, valid: true, trusted: false,
    trust_note: "", covers_whole_file: true, modification: "none", changes_allowed: true, status: "unknown",
    summary: "", error: null, ...patch,
  };
}

function validation(overall: SignatureValidation["summary"]["overall"], counts: Partial<SignatureValidation["summary"]> = {}): SignatureValidation {
  return { version: "v1", signatures: [], summary: { count: 1, overall, valid: 0, unknown: 0, modified: 0, invalid: 0, ...counts } };
}

describe("consent to edit a signed document", () => {
  it("is not needed for unsigned documents", () => {
    expect(signedEditKey(doc(0))).toBeNull();
    expect(needsSignedEditConsent(doc(0), null)).toBe(false);
    expect(needsSignedEditConsent(null, null)).toBe(false);
  });

  it("is needed once per document and signature count", () => {
    expect(needsSignedEditConsent(doc(1), null)).toBe(true);
    const key = signedEditKey(doc(1));
    expect(needsSignedEditConsent(doc(1), key)).toBe(false);
    expect(needsSignedEditConsent(doc(2), key)).toBe(true); // a new signature asks again
    expect(needsSignedEditConsent({ id: "other", signatures: 1 }, key)).toBe(true);
  });
});

describe("signature banner", () => {
  it("says it is checking until validation arrives", () => {
    expect(signatureBanner(null, 2)).toEqual({ kind: "info", text: expect.stringContaining("2 digital signatures") });
  });

  it("maps the overall verdict to a tone", () => {
    expect(signatureBanner(validation("valid", { valid: 1 }), 1).kind).toBe("success");
    expect(signatureBanner(validation("unknown", { unknown: 1 }), 1)).toMatchObject({ kind: "warning", text: expect.stringContaining("identity") });
    expect(signatureBanner(validation("modified", { modified: 1 }), 1).text).toContain("changed after signing");
    expect(signatureBanner(validation("invalid", { invalid: 2, count: 2 }), 2)).toMatchObject({ kind: "error", text: expect.stringMatching(/^2 signatures are invalid/) });
  });
});

describe("changes after signing", () => {
  it("explains each modification level", () => {
    expect(changesText(report({}))).toMatch(/covers the whole document/);
    expect(changesText(report({ covers_whole_file: false, modification: "form_filling" }))).toMatch(/allowed/);
    expect(changesText(report({ covers_whole_file: false, modification: "other", changes_allowed: false }))).toMatch(/does not allow/);
  });
});

describe("sign form checks", () => {
  const p12 = new File(["x"], "me.p12");
  it("requires a .p12/.pfx certificate", () => {
    expect(signFormProblem({ certificate: null, timestampUrl: "", visible: false, hasBox: false })).toMatch(/certificate/);
    expect(signFormProblem({ certificate: new File(["x"], "me.pem"), timestampUrl: "", visible: false, hasBox: false })).toMatch(/\.p12/);
    expect(signFormProblem({ certificate: new File(["x"], "ME.PFX"), timestampUrl: "", visible: false, hasBox: false })).toBeNull();
  });

  it("requires a box for visible signatures and an http(s) timestamp URL", () => {
    expect(signFormProblem({ certificate: p12, timestampUrl: "", visible: true, hasBox: false })).toMatch(/Draw a box/);
    expect(signFormProblem({ certificate: p12, timestampUrl: "ftp://tsa", visible: false, hasBox: false })).toMatch(/http/);
    expect(signFormProblem({ certificate: p12, timestampUrl: " https://tsa.example.com ", visible: true, hasBox: true })).toBeNull();
  });
});

it("reports the time zone as minutes east of UTC", () => {
  const date = { getTimezoneOffset: () => -120 } as Date;
  expect(utcOffsetMinutes(date)).toBe(120);
});
