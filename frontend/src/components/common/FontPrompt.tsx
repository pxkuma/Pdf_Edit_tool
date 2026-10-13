import { Download, Loader2, Type, Upload } from "lucide-react";
import { pickFile } from "../../lib/files";
import { downloadPromptedFont, uploadPromptedFont, useFontPrompt } from "../../lib/fontPrompt";

/** Asks whether to install the font the PDF uses (see lib/fontPrompt.ts). */
export function FontPrompt() {
  const lookup = useFontPrompt((s) => s.lookup);
  const busy = useFontPrompt((s) => s.busy);
  const close = useFontPrompt((s) => s.close);
  if (!lookup) return null;

  const upload = async () => {
    const file = await pickFile(".ttf,.otf,font/ttf,font/otf");
    if (file) await uploadPromptedFont(file);
  };
  const meanwhile = lookup.substitute ? ` Until then, characters the PDF doesn't already contain are drawn in ${lookup.substitute}.` : "";

  const message = {
    downloadable: (
      <>
        This text uses <strong>{lookup.name}</strong>, which isn't installed.{meanwhile} Download{" "}
        <strong>{lookup.family}</strong> (free, Google Fonts) so your edits stay in the same font?
      </>
    ),
    commercial: (
      <>
        <strong>{lookup.name}</strong> is a commercial font, so it can't be downloaded. Edits use{" "}
        <strong>{lookup.substitute ?? "a similar font"}</strong> for characters the PDF doesn't contain. If you have the font file,
        upload it to keep the exact look.
      </>
    ),
    unknown: (
      <>
        <strong>{lookup.name}</strong> isn't installed and isn't in the free font library.{meanwhile} Upload the font file to keep
        the exact look.
      </>
    ),
    offline: (
      <>
        <strong>{lookup.name}</strong> isn't installed and the font library can't be reached right now.{meanwhile}
      </>
    ),
    installed: null,
  }[lookup.status];

  return (
    <div className="font-prompt" role="dialog" aria-label="Font not installed">
      <div className="font-prompt-head">
        <Type size={16} />
        <span>Font not installed</span>
      </div>
      <p>{message}</p>
      <div className="font-prompt-actions">
        {lookup.status === "downloadable" && (
          <button className="btn small primary" disabled={busy} onClick={() => void downloadPromptedFont()}>
            {busy ? <Loader2 size={14} className="spin" /> : <Download size={14} />} Download & use {lookup.family}
          </button>
        )}
        {lookup.status === "offline" && (
          <button className="btn small primary" disabled={busy} onClick={() => void downloadPromptedFont()}>
            {busy ? <Loader2 size={14} className="spin" /> : <Download size={14} />} Try again
          </button>
        )}
        <button className="btn small" disabled={busy} onClick={() => void upload()}>
          <Upload size={14} /> Upload font file…
        </button>
        <button className="btn small ghost" disabled={busy} onClick={() => close("session")}>
          {lookup.status === "commercial" || lookup.status === "unknown" ? `Use ${lookup.substitute ?? "closest match"}` : "Not now"}
        </button>
      </div>
      <button className="link-btn" disabled={busy} onClick={() => close("never")}>
        Don't ask again for this font
      </button>
    </div>
  );
}
