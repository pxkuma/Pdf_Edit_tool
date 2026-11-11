"""Certificate-based digital signatures: sign with a PKCS#12 file, and validate existing signatures.

The certificate and its password only live in memory for the duration of the request. They are never
written to the document storage, logged, or echoed back in an error.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import math
import socket
from urllib.parse import urlsplit

import pymupdf as fitz
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pyhanko.pdf_utils.misc import PdfError
from pyhanko.sign.timestamps import HTTPTimeStamper
from starlette.concurrency import run_in_threadpool

from .. import deps
from ..pdf import images
from ..pdf.sigcert import MAX_CERT_BYTES, MAX_PASSWORD_CHARS, load_identity
from ..pdf.sigfields import signature_fields
from ..pdf.signing import FieldPlan, Placement, SignOptions, TimestampError, apply_signature, prepare
from ..pdf.sigtrust import trust_roots
from ..pdf.sigvalidate import summarize, validate_signatures
from ..storage import PDF_LOCK
from .common import doc_info, ok, read_upload

router = APIRouter(prefix="/api/documents/{doc_id}")

TIMESTAMP_TIMEOUT = 10
MAX_URL = 500
MAX_TEXT = 200


def parse_rect(value: str) -> tuple[float, float, float, float]:
    parts = value.split(",")
    try:
        numbers = tuple(float(p) for p in parts)
    except ValueError:
        numbers = ()
    if len(numbers) != 4 or not all(math.isfinite(n) and abs(n) < 1e5 for n in numbers):
        raise HTTPException(status_code=400, detail="The signature box must be four numbers: x0,y0,x1,y1.")
    x0, y0, x1, y1 = numbers
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def _blocked_address(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%")[0])
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified


def check_timestamp_url(url: str, allow_private: bool) -> str:
    """Accept only plain http(s) URLs of public hosts, so the server cannot be used to probe a network."""
    url = url.strip()
    if len(url) > MAX_URL:
        raise HTTPException(status_code=400, detail="The timestamp server URL is too long.")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise HTTPException(status_code=400, detail="The timestamp server URL must start with http:// or https://.")
    if parts.username or parts.password:
        raise HTTPException(status_code=400, detail="The timestamp server URL must not contain a user name or password.")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="The timestamp server URL has an invalid port.") from exc
    if allow_private:
        return url
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parts.hostname, port, proto=socket.IPPROTO_TCP)}
    except (socket.gaierror, UnicodeError) as exc:
        raise HTTPException(status_code=400, detail="The timestamp server's host name could not be found.") from exc
    if any(_blocked_address(address) for address in addresses):
        raise HTTPException(status_code=400, detail="The timestamp server must be a public address, not a local or private network one.")
    return url


def _placement(page: int | None, rect: str | None) -> Placement | None:
    if page is None and not rect:
        return None
    if page is None or not rect:
        raise HTTPException(status_code=400, detail="A visible signature needs both a page and a box.")
    return Placement(page=page, rect=parse_rect(rect))


def _fontfile() -> str | None:
    face = deps.default_face()
    if face and face.path.lower().endswith((".ttf", ".otf")):
        return face.path
    return None


def _plan(doc_id: str, identity, options: SignOptions, when: dt.datetime) -> tuple[str, bytes, FieldPlan]:
    store = deps.store()
    with PDF_LOCK:
        state = store.get(doc_id)
        payload = store.version_path(state).read_bytes()
        scratch = fitz.open("pdf", payload)  # prepare() may touch page rotation; never the stored file
        try:
            plan = prepare(scratch, identity, options, when)
        finally:
            scratch.close()
    return state.current.file, payload, plan


@router.post("/sign")
async def sign(
    doc_id: str,
    certificate: UploadFile = File(...),
    password: str = Form("", max_length=MAX_PASSWORD_CHARS),
    page: int | None = Form(None, ge=0),
    rect: str | None = Form(None, max_length=120),
    reason: str = Form("", max_length=MAX_TEXT),
    location: str = Form("", max_length=MAX_TEXT),
    contact: str = Form("", max_length=MAX_TEXT),
    timestamp_url: str = Form("", max_length=MAX_URL),
    show_details: bool = Form(True),
    utc_offset: int = Form(0, ge=-840, le=840),
    image: UploadFile | None = File(None),
) -> dict:
    deps.store().get(doc_id)  # 404 before reading uploads for a missing document
    try:
        cert_data = await read_upload(certificate, MAX_CERT_BYTES, "certificate")
        image_data = await read_upload(image, images.MAX_IMAGE_BYTES, "image") if image is not None else None
    finally:
        await certificate.close()  # drop the spooled upload right away
        if image is not None:
            await image.close()
    options = SignOptions(
        placement=_placement(page, rect),
        reason=reason, location=location, contact=contact,
        show_details=show_details, image=image_data, utc_offset_minutes=utc_offset,
        fontfile=_fontfile(),
    )
    timestamper = None
    if timestamp_url.strip():
        url = check_timestamp_url(timestamp_url, deps.settings().allow_private_tsa)
        timestamper = HTTPTimeStamper(url, timeout=TIMESTAMP_TIMEOUT)

    def run() -> dict:
        identity = load_identity(cert_data, password)
        expected, payload, plan = _plan(doc_id, identity, options, dt.datetime.now(dt.timezone.utc))
        try:
            signed = apply_signature(payload, identity, plan, options, timestamper)
        except TimestampError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        state = deps.store().replace_if_current(doc_id, expected, f"Digitally signed by {identity.name}", signed)
        result = {"field": plan.name, "signer": identity.name, "visible": plan.box is not None,
                  "timestamped": timestamper is not None}
        return ok({"document": doc_info(state), "result": result})

    return await run_in_threadpool(run)


@router.get("/signatures")
def signatures(doc_id: str) -> dict:
    store = deps.store()
    with PDF_LOCK:
        state, doc = store.open_current(doc_id)
        located = {field.name: field for field in signature_fields(doc)}
        payload = store.version_path(state).read_bytes()
    try:
        reports = validate_signatures(payload, located, trust_roots(deps.settings().trust_roots_file))
    except PdfError as exc:
        raise HTTPException(status_code=400, detail="The signatures in this PDF could not be read.") from exc
    return ok({
        "version": state.current.file,
        "summary": summarize(reports),
        "signatures": [report.to_json() for report in reports],
    })
