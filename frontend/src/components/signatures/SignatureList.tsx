import { LocateFixed } from "lucide-react";
import { useState, type ReactNode } from "react";
import type { SignatureReport } from "../../api/types";
import { VERDICT_LABEL, changesText, formatWhen, integrityText } from "../../lib/signatures";
import { useEditor } from "../../store/editor";

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </>
  );
}

function SignatureItem({ report, index }: { report: SignatureReport; index: number }) {
  const [expanded, setExpanded] = useState(index === 0);
  const scrollTo = useEditor((s) => s.scrollTo);
  const setCurrentPage = useEditor((s) => s.setCurrentPage);
  const signer = report.signer;

  const jump = () => {
    if (report.page === null) return;
    setCurrentPage(report.page);
    scrollTo(report.page, report.rect ? report.rect[1] : undefined);
  };

  return (
    <li className={`sig-item ${report.status}`}>
      <div className="sig-item-head">
        <button className="sig-item-title" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>
          <span className={`sig-badge ${report.status}`}>{VERDICT_LABEL[report.status]}</span>
          <strong>{signer?.name ?? report.field}</strong>
          <span className="sig-muted">{formatWhen(report.timestamp ?? report.signing_time)}</span>
        </button>
        {report.page !== null && (
          <button className="icon-btn small" title={report.rect ? `Show on page ${report.page + 1}` : `Invisible signature (page ${report.page + 1})`} onClick={jump}>
            <LocateFixed size={14} />
          </button>
        )}
      </div>
      <p className="sig-summary">{report.summary}</p>
      {expanded && (
        <dl className="sig-details">
          <Row label="Integrity">{integrityText(report)}</Row>
          <Row label="Changes after signing">{changesText(report)}</Row>
          <Row label="Identity">
            {report.trusted ? "Trusted" : "Not verified"}. {report.trust_note}
          </Row>
          {signer && (
            <Row label="Certificate">
              {signer.name}
              {signer.email && ` <${signer.email}>`}
              {signer.organization && `, ${signer.organization}`}. Issued by {signer.issuer}
              {signer.self_signed && " (self-signed)"}, valid {formatWhen(signer.valid_from)} to {formatWhen(signer.valid_to)}.
            </Row>
          )}
          <Row label="Signing time">
            {report.timestamp
              ? `${formatWhen(report.timestamp)} from a timestamp server${report.timestamp_valid ? "" : " (timestamp could not be verified)"}`
              : `${formatWhen(report.signing_time)} (the signer's computer clock, no timestamp)`}
          </Row>
          {report.reason && <Row label="Reason">{report.reason}</Row>}
          {report.location && <Row label="Location">{report.location}</Row>}
          <Row label="Field">
            {report.field}
            {report.rect ? "" : " (invisible)"}
            {report.certified ? ", certification signature" : ""}
          </Row>
          {report.error && <Row label="Error">{report.error}</Row>}
        </dl>
      )}
    </li>
  );
}

export function SignatureList({ reports }: { reports: SignatureReport[] }) {
  if (!reports.length) return <div className="empty">No digital signatures found.</div>;
  return (
    <ol className="sig-list">
      {reports.map((report, index) => (
        <SignatureItem key={`${report.field}-${report.revision}`} report={report} index={index} />
      ))}
      <li className="sig-footnote">Validation runs on this server without contacting revocation services (OCSP/CRL).</li>
    </ol>
  );
}
