import { FileKey, PenLine, ShieldCheck, SquareDashedMousePointer, Upload } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { SignRequest } from "../../api/types";
import { flushEdit } from "../../lib/editSession";
import { pickFile } from "../../lib/files";
import { signFormProblem, utcOffsetMinutes } from "../../lib/signatures";
import { useEditor } from "../../store/editor";
import { Modal } from "../common/Modal";
import { loadSaved } from "./SignatureDialog";

/**
 * What the dialog remembers while the user draws the signature box on the page. Kept in memory only,
 * and never the password: that has to be typed again after redrawing.
 */
interface Draft {
  certificate: File | null;
  visible: boolean;
  reason: string;
  location: string;
  contact: string;
  timestampUrl: string;
  showDetails: boolean;
  image: string | null; // "data:" URL of a saved signature, or an object URL of an uploaded image
}

let draft: Draft = {
  certificate: null,
  visible: true,
  reason: "",
  location: "",
  contact: "",
  timestampUrl: "",
  showDetails: true,
  image: null,
};

async function imageBlob(url: string | null): Promise<Blob | null> {
  return url ? (await fetch(url)).blob() : null;
}

export function DigitalSignDialog() {
  const { doc, openDialog, run, setTool, toast, signTarget, setSignTarget, setSignaturePanel } = useEditor();
  const [form, setForm] = useState<Draft>(() => ({ ...draft, visible: draft.visible || signTarget !== null }));
  const [password, setPassword] = useState("");
  const [saved] = useState(loadSaved);
  const [signing, setSigning] = useState(false);

  useEffect(() => {
    draft = { ...form }; // survives closing the dialog to draw the box
  }, [form]);

  if (!doc) return null;
  const patch = (values: Partial<Draft>) => setForm((current) => ({ ...current, ...values }));
  const close = () => openDialog(null);

  const chooseCertificate = async () => {
    const file = await pickFile(".p12,.pfx,application/x-pkcs12");
    if (file) patch({ certificate: file });
  };

  const uploadImage = async () => {
    const file = await pickFile("image/png,image/jpeg");
    if (file) patch({ image: URL.createObjectURL(file) });
  };

  const drawBox = () => {
    close();
    setTool("signField");
    toast("Drag a box on the page where the signature should appear.", "info");
  };

  const problem = signFormProblem({
    certificate: form.certificate,
    timestampUrl: form.timestampUrl,
    visible: form.visible,
    hasBox: signTarget !== null,
  });

  const sign = async () => {
    if (problem || !form.certificate) {
      toast(problem ?? "Choose your certificate file.", "warning");
      return;
    }
    setSigning(true);
    try {
      await flushEdit();
      const request: SignRequest = {
        certificate: form.certificate,
        password,
        placement: form.visible && signTarget ? signTarget : null,
        reason: form.reason,
        location: form.location,
        contact: form.contact,
        timestampUrl: form.timestampUrl,
        showDetails: form.showDetails,
        image: form.visible ? await imageBlob(form.image) : null,
        utcOffset: utcOffsetMinutes(),
      };
      const result = await run(() => api.sign(doc.id, request), undefined, { allowSigned: true });
      if (result) {
        toast(`Signed by ${result.signer}${result.timestamped ? " (timestamped)" : ""}.`, "success");
        setSignTarget(null);
        setSignaturePanel(true);
        close();
      }
    } finally {
      setSigning(false);
    }
  };

  const text = (label: string, key: "reason" | "location" | "contact", placeholder: string) => (
    <label className="field">
      <span>{label}</span>
      <input className="input" maxLength={200} placeholder={placeholder} value={form[key]} onChange={(e) => patch({ [key]: e.target.value })} />
    </label>
  );

  return (
    <Modal
      title="Sign with a certificate"
      icon={<ShieldCheck size={18} />}
      onClose={close}
      wide
      footer={
        <>
          <button className="btn" onClick={close}>Cancel</button>
          <button className="btn primary" disabled={signing || problem !== null} title={problem ?? undefined} onClick={() => void sign()}>
            <PenLine size={15} /> {signing ? "Signing…" : "Sign document"}
          </button>
        </>
      }
    >
      <div className="grid-2">
        <div className="sign-col">
          <strong>Digital ID</strong>
          <div className="row">
            <button className="btn" onClick={() => void chooseCertificate()}>
              <FileKey size={15} /> {form.certificate ? "Change…" : "Choose .p12 / .pfx…"}
            </button>
            <span className="sign-file" title={form.certificate?.name}>{form.certificate?.name ?? "No certificate chosen"}</span>
          </div>
          <label className="field">
            <span>Certificate password</span>
            <input className="input" type="password" autoComplete="off" value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          {text("Reason (optional)", "reason", "I approve this document")}
          {text("Location (optional)", "location", "City, country")}
          {text("Contact (optional)", "contact", "E-mail or phone")}
          <label className="field">
            <span>Timestamp server (optional)</span>
            <input
              className="input"
              type="url"
              maxLength={500}
              placeholder="https://timestamp.example.com"
              value={form.timestampUrl}
              onChange={(e) => patch({ timestampUrl: e.target.value })}
            />
          </label>
        </div>
        <div className="sign-col">
          <strong>Placement</strong>
          <div className="segmented">
            <button className={form.visible ? "on" : ""} onClick={() => patch({ visible: true })}>Visible</button>
            <button className={!form.visible ? "on" : ""} onClick={() => patch({ visible: false })}>Invisible</button>
          </div>
          {form.visible ? (
            <>
              <div className="row">
                <button className="btn small" onClick={drawBox}>
                  <SquareDashedMousePointer size={14} /> {signTarget ? "Redraw box" : "Draw box on page"}
                </button>
                <span className="sign-file">
                  {signTarget
                    ? `Page ${signTarget.page + 1}, ${Math.round(signTarget.rect[2] - signTarget.rect[0])} × ${Math.round(signTarget.rect[3] - signTarget.rect[1])} pt`
                    : "No box yet"}
                </span>
              </div>
              <label className="check">
                <input type="checkbox" checked={form.showDetails} onChange={(e) => patch({ showDetails: e.target.checked })} /> Show name, date, reason and
                location
              </label>
              <span className="field-label">Signature image (optional)</span>
              <div className="sig-saved sign-images">
                <button className={form.image === null ? "on" : ""} onClick={() => patch({ image: null })}>None</button>
                {saved.map((url) => (
                  <button key={url} className={form.image === url ? "on" : ""} onClick={() => patch({ image: url })} title="Use this signature">
                    <img src={url} alt="Saved signature" />
                  </button>
                ))}
                {form.image && !saved.includes(form.image) && (
                  <button className="on" title="Uploaded image">
                    <img src={form.image} alt="Uploaded signature" />
                  </button>
                )}
                <button onClick={() => void uploadImage()} title="Upload an image">
                  <Upload size={14} /> Upload
                </button>
              </div>
            </>
          ) : (
            <div className="note">An invisible signature protects the whole document without adding anything to the page. It is listed in the signature panel.</div>
          )}
          <div className="note">
            Your certificate and password are sent to this PDF Studio server for this signature only. They are not stored or logged.
          </div>
          {doc.signatures > 0 && (
            <div className="note">This document already has {doc.signatures} signature(s). They stay valid: the new signature is added as a new revision.</div>
          )}
        </div>
      </div>
    </Modal>
  );
}
