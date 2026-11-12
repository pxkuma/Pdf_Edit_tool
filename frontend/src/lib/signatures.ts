import type { DocInfo, SignatureReport, SignatureValidation, SignatureVerdict } from "../api/types";

/**
 * Consent to edit a signed document is tied to the document and its number of signatures: a new
 * signature means the user has to agree again before the next edit (like Acrobat).
 */
export function signedEditKey(doc: Pick<DocInfo, "id" | "signatures"> | null): string | null {
  return doc && doc.signatures > 0 ? `${doc.id}:${doc.signatures}` : null;
}

export function needsSignedEditConsent(doc: Pick<DocInfo, "id" | "signatures"> | null, consent: string | null): boolean {
  const key = signedEditKey(doc);
  return key !== null && key !== consent;
}

export type BannerKind = "success" | "info" | "warning" | "error";

export interface Banner {
  kind: BannerKind;
  text: string;
}

const PLURAL = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** One line for the bar above the document. */
export function signatureBanner(validation: SignatureValidation | null, count: number): Banner {
  if (!validation) return { kind: "info", text: `Signed with ${PLURAL(count, "digital signature")}. Checking…` };
  const { summary } = validation;
  switch (summary.overall) {
    case "valid":
      return { kind: "success", text: summary.count === 1 ? "Signed, and the signature is valid." : "Signed, and all signatures are valid." };
    case "unknown":
      return {
        kind: "warning",
        text: `Signed. The document is unchanged since signing, but ${summary.unknown === 1 ? "one signer's identity" : `${summary.unknown} signers' identities`} could not be verified.`,
      };
    case "modified":
      return { kind: "warning", text: "Signed, but the document was changed after signing." };
    case "invalid":
      return { kind: "error", text: `${PLURAL(summary.invalid, "signature")} ${summary.invalid === 1 ? "is" : "are"} invalid: the signed content was altered.` };
    default:
      return { kind: "info", text: "No digital signatures." };
  }
}

export const VERDICT_LABEL: Record<SignatureVerdict, string> = {
  valid: "Valid",
  unknown: "Identity not verified",
  modified: "Changed after signing",
  invalid: "Invalid",
};

/** "Changes after signing" in words, for the details of one signature. */
export function changesText(report: SignatureReport): string {
  if (report.covers_whole_file) return "None: the signature covers the whole document.";
  switch (report.modification) {
    case "validation_data":
      return "Only validation data was added.";
    case "form_filling":
      return "Form filling or further signatures (allowed).";
    case "annotations":
      return "Comments or form filling (allowed).";
    case "other":
      return "Content changes that a signature does not allow.";
    default:
      return report.changes_allowed ? "Allowed changes only." : "Could not be determined.";
  }
}

export function integrityText(report: SignatureReport): string {
  if (!report.intact) return "Broken: the signed content was altered.";
  if (!report.valid) return "Broken: the signature does not match the certificate.";
  return "Intact: the signed content is unchanged.";
}

export function formatWhen(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

/** Browser time zone in minutes east of UTC, as the backend expects. */
export function utcOffsetMinutes(date = new Date()): number {
  return -date.getTimezoneOffset();
}

/** Client-side checks before the certificate and password are sent. */
export function signFormProblem(input: { certificate: File | null; timestampUrl: string; visible: boolean; hasBox: boolean }): string | null {
  if (!input.certificate) return "Choose your certificate file (.p12 or .pfx).";
  if (!/\.(p12|pfx)$/i.test(input.certificate.name)) return "The certificate must be a .p12 or .pfx file.";
  if (input.visible && !input.hasBox) return "Draw a box on the page for the visible signature, or sign invisibly.";
  const url = input.timestampUrl.trim();
  if (url && !/^https?:\/\/[^\s/]+/i.test(url)) return "The timestamp server URL must start with http:// or https://.";
  return null;
}
