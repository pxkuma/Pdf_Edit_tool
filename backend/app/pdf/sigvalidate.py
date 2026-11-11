"""Validate the digital signatures in a PDF with pyHanko.

Validation is offline: no revocation (OCSP/CRL) or certificate fetching. Each signature gets four
separate answers, because they mean different things to a reader:

* integrity: do the signed bytes still match the signature (``intact`` and ``valid``)?
* changes after signing: what later revisions changed, and whether that was allowed;
* trust: does the signer's certificate chain to a root this server trusts?
* time: the signer's own clock, and a timestamp authority's time when there is one.
"""

from __future__ import annotations

import datetime as dt
import io
import logging
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass

from asn1crypto import x509
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign.diff_analysis import ModificationLevel
from pyhanko.sign.validation.errors import SignatureValidationError
from pyhanko.sign.validation import validate_pdf_signature
from pyhanko.sign.validation.status import PdfSignatureStatus, SignatureCoverageLevel
from pyhanko_certvalidator import ValidationContext

from .sigfields import SigField

# pyHanko logs a full traceback for every certificate it cannot chain to a root. That is the
# expected outcome for self-signed certificates and is reported to the user instead.
logging.getLogger("pyhanko.sign.validation").setLevel(logging.ERROR)
logging.getLogger("pyhanko_certvalidator").setLevel(logging.ERROR)

_MODIFICATIONS = {
    ModificationLevel.NONE: "none",
    ModificationLevel.LTA_UPDATES: "validation_data",
    ModificationLevel.FORM_FILLING: "form_filling",
    ModificationLevel.ANNOTATIONS: "annotations",
    ModificationLevel.OTHER: "other",
}


@dataclass(frozen=True)
class SignerInfo:
    name: str
    email: str
    organization: str
    issuer: str
    serial: str
    valid_from: str
    valid_to: str
    self_signed: bool


@dataclass(frozen=True)
class SignatureReport:
    field: str
    page: int | None
    rect: tuple[float, float, float, float] | None
    revision: int
    signer: SignerInfo | None
    signing_time: str | None  # the signer's computer clock (not proof)
    timestamp: str | None  # time attested by a timestamp authority
    timestamp_valid: bool | None
    reason: str
    location: str
    certified: bool  # certification (DocMDP) signature rather than an approval signature
    intact: bool
    valid: bool
    trusted: bool
    trust_note: str
    covers_whole_file: bool
    modification: str  # none | validation_data | form_filling | annotations | other | unknown
    changes_allowed: bool
    status: str  # valid | unknown | modified | invalid
    summary: str
    error: str | None = None

    def to_json(self) -> dict:
        return asdict(self)


def _iso(value: dt.datetime | None) -> str | None:
    return value.astimezone(dt.timezone.utc).isoformat() if value else None


def _name_part(name: x509.Name, key: str) -> str:
    value = name.native.get(key, "")
    return ", ".join(value) if isinstance(value, list) else str(value or "")


def signer_info(cert: x509.Certificate) -> SignerInfo:
    subject, issuer = cert.subject, cert.issuer
    email = _name_part(subject, "email_address")
    if not email and cert.subject_alt_name_value is not None:
        email = next((n.native for n in cert.subject_alt_name_value if n.name == "rfc822_name"), "")
    return SignerInfo(
        name=_name_part(subject, "common_name") or _name_part(subject, "organization_name") or subject.human_friendly,
        email=email,
        organization=_name_part(subject, "organization_name"),
        issuer=_name_part(issuer, "common_name") or _name_part(issuer, "organization_name") or issuer.human_friendly,
        serial=format(cert.serial_number, "x"),
        valid_from=_iso(cert.not_valid_before) or "",
        valid_to=_iso(cert.not_valid_after) or "",
        self_signed=cert.self_signed in ("yes", "maybe"),
    )


def _trust_note(status: PdfSignatureStatus, signer: SignerInfo | None) -> str:
    if status.trusted:
        return "The certificate chains to a trusted root. Revocation was not checked (offline validation)."
    if signer and signer.self_signed:
        return "The certificate is self-signed, so no authority vouches for the signer's identity."
    return ("The certificate does not chain to a root this server trusts. Its identity cannot be confirmed "
            "(the administrator can add trusted roots with PDF_STUDIO_TRUST_ROOTS).")


def _verdict(intact: bool, valid: bool, changes_allowed: bool, trusted: bool, modification: str) -> tuple[str, str]:
    if not intact:
        return "invalid", "The document was altered after this signature was applied. The signature is broken."
    if not valid:
        return "invalid", "The signature does not match the signer's certificate."
    if not changes_allowed:
        return "modified", "The signed version is intact, but the document was changed afterwards in ways a signature does not allow."
    changed = {
        "form_filling": " Later changes: form filling or further signatures, which are allowed.",
        "annotations": " Later changes: comments or form filling, which are allowed.",
        "validation_data": " Later changes: validation data only.",
    }.get(modification, "")
    if trusted:
        return "valid", f"The signature is valid and the signer's identity is trusted.{changed}"
    return "unknown", f"The document has not been modified since it was signed, but the signer's identity is not verified.{changed}"


def _report(embedded, status: PdfSignatureStatus, located: SigField | None) -> SignatureReport:
    signer = signer_info(status.signing_cert) if status.signing_cert is not None else None
    level = status.modification_level
    modification = _MODIFICATIONS.get(level, "unknown") if level is not None else "unknown"
    changes_allowed = bool(status.docmdp_ok) and level != ModificationLevel.OTHER
    covers_whole = status.coverage == SignatureCoverageLevel.ENTIRE_FILE
    verdict, summary = _verdict(bool(status.intact), bool(status.valid), changes_allowed, bool(status.trusted), modification)
    ts = status.timestamp_validity
    sig = embedded.sig_object
    return SignatureReport(
        field=embedded.field_name,
        page=located.page if located else None,
        rect=located.rect if located else None,
        revision=embedded.signed_revision,
        signer=signer,
        signing_time=_iso(status.signer_reported_dt),
        timestamp=_iso(ts.timestamp) if ts else None,
        timestamp_valid=bool(ts.intact and ts.valid) if ts else None,
        reason=str(sig.get("/Reason", "") or ""),
        location=str(sig.get("/Location", "") or ""),
        certified=embedded.docmdp_level is not None,
        intact=bool(status.intact),
        valid=bool(status.valid),
        trusted=bool(status.trusted),
        trust_note=_trust_note(status, signer),
        covers_whole_file=covers_whole,
        modification="none" if covers_whole else modification,
        changes_allowed=changes_allowed,
        status=verdict,
        summary=summary,
    )


def _failed(embedded, located: SigField | None, message: str) -> SignatureReport:
    return SignatureReport(
        field=getattr(embedded, "field_name", "") or "", page=located.page if located else None,
        rect=located.rect if located else None, revision=getattr(embedded, "signed_revision", -1),
        signer=None, signing_time=None, timestamp=None, timestamp_valid=None, reason="", location="",
        certified=False, intact=False, valid=False, trusted=False,
        trust_note="The signature could not be checked.", covers_whole_file=False, modification="unknown",
        changes_allowed=False, status="invalid", summary="The signature is damaged and could not be validated.",
        error=message,
    )


def validate_signatures(payload: bytes, located: Mapping[str, SigField],
                        trust_roots: Iterable[x509.Certificate] = ()) -> list[SignatureReport]:
    """Validate every signature in ``payload``; ``located`` maps field names to their place on the page."""
    reader = PdfFileReader(io.BytesIO(payload), strict=False)
    roots = list(trust_roots)
    reports: list[SignatureReport] = []
    for embedded in reader.embedded_signatures:
        where = located.get(embedded.field_name)
        context = ValidationContext(trust_roots=roots, allow_fetching=False, revocation_mode="soft-fail")
        try:
            status = validate_pdf_signature(embedded, context, skip_diff=False)
        except (SignatureValidationError, ValueError, KeyError, TypeError) as exc:
            reports.append(_failed(embedded, where, type(exc).__name__))
            continue
        reports.append(_report(embedded, status, where))
    return reports


def summarize(reports: list[SignatureReport]) -> dict:
    counts = {key: sum(1 for r in reports if r.status == key) for key in ("valid", "unknown", "modified", "invalid")}
    if not reports:
        overall = "none"
    elif counts["invalid"]:
        overall = "invalid"
    elif counts["modified"]:
        overall = "modified"
    elif counts["unknown"]:
        overall = "unknown"
    else:
        overall = "valid"
    return {"count": len(reports), "overall": overall, **counts}
