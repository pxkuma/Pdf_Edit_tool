import { ChevronDown, ChevronUp, RefreshCw, ShieldAlert, ShieldCheck, ShieldQuestion, ShieldX } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { api } from "../../api/client";
import type { SignatureValidation } from "../../api/types";
import { signatureBanner, type BannerKind } from "../../lib/signatures";
import { errorMessage, useEditor } from "../../store/editor";
import { SignatureList } from "./SignatureList";

const ICONS: Record<BannerKind, ReactNode> = {
  success: <ShieldCheck size={16} />,
  info: <ShieldQuestion size={16} />,
  warning: <ShieldAlert size={16} />,
  error: <ShieldX size={16} />,
};

/**
 * Acrobat-style bar above a signed document, with the signature panel folding out underneath.
 * Validation is fetched again whenever the document version changes.
 */
export function SignatureBar() {
  const doc = useEditor((s) => s.doc);
  const open = useEditor((s) => s.signaturePanelOpen);
  const setOpen = useEditor((s) => s.setSignaturePanel);
  const [validation, setValidation] = useState<SignatureValidation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const docId = doc?.id;
  const version = doc?.version;
  const signed = (doc?.signatures ?? 0) > 0;

  const load = useCallback(async (id: string, cancelled: () => boolean) => {
    setError(null);
    try {
      const result = await api.signatures(id);
      if (!cancelled()) setValidation(result);
    } catch (err) {
      if (!cancelled()) setError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    setValidation(null);
    if (!docId || !signed) return;
    let stale = false;
    void load(docId, () => stale);
    return () => {
      stale = true;
    };
  }, [docId, version, signed, load]);

  if (!doc || !signed) return null;
  const banner = error ? { kind: "error" as const, text: `Signatures could not be checked: ${error}` } : signatureBanner(validation, doc.signatures);

  return (
    <section className={`sig-bar ${banner.kind}`} aria-label="Digital signatures">
      <div className="sig-bar-head">
        {ICONS[banner.kind]}
        <span className="sig-bar-text">{banner.text}</span>
        <button className="btn small ghost" title="Check again" onClick={() => void load(doc.id, () => false)}>
          <RefreshCw size={13} />
        </button>
        <button className="btn small" onClick={() => setOpen(!open)} aria-expanded={open}>
          Signature panel {open ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
        </button>
      </div>
      {open && validation && <SignatureList reports={validation.signatures} />}
    </section>
  );
}
