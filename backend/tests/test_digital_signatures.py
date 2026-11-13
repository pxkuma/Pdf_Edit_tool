"""PKI digital signatures: signing with a PKCS#12 certificate, validation and tamper detection."""

from __future__ import annotations

import datetime as dt
import io

import pymupdf as fitz
import pytest
from pyhanko.pdf_utils import generic
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign.timestamps.dummy_client import DummyTimeStamper
from sigkit import PASSWORD, make_credential

from app.pdf.sigcert import CertificateError, load_identity
from app.pdf.sigfields import signature_fields, signed_count
from app.pdf.signing import Placement, SignatureError, SignOptions, apply_signature, prepare
from app.pdf.sigvalidate import summarize, validate_signatures

NOW = dt.datetime.now(dt.timezone.utc)


@pytest.fixture(scope="module")
def signer():
    return make_credential()


@pytest.fixture(scope="module")
def identity(signer):
    return load_identity(signer.p12(), PASSWORD)


def plain_pdf(pages: int = 2, rotation: int = 0) -> bytes:
    doc = fitz.open()
    for index in range(pages):
        page = doc.new_page()
        page.insert_text((72, 100), f"Contract page {index + 1}", fontsize=14)
        page.set_rotation(rotation)
    return doc.tobytes(garbage=1, deflate=True)


def sign(payload: bytes, identity, options: SignOptions = SignOptions(), timestamper=None) -> bytes:
    doc = fitz.open("pdf", payload)
    try:
        plan = prepare(doc, identity, options, NOW)
    finally:
        doc.close()
    return apply_signature(payload, identity, plan, options, timestamper)


def validate(payload: bytes, roots=()):
    doc = fitz.open("pdf", payload)
    located = {field.name: field for field in signature_fields(doc)}
    doc.close()
    return validate_signatures(payload, located, roots)


# ------------------------------------------------------------------ certificates
def test_wrong_password_is_reported_without_echoing_it(signer):
    with pytest.raises(CertificateError, match="password is incorrect") as info:
        load_identity(signer.p12(), "not the password")
    assert "not the password" not in str(info.value)


def test_files_that_are_not_pkcs12_are_rejected():
    with pytest.raises(CertificateError, match="not a PKCS#12"):
        load_identity(b"-----BEGIN CERTIFICATE-----\nnope\n", PASSWORD)


def test_expired_and_non_signing_certificates_are_refused():
    expired = make_credential(days_valid=(-30, -1))
    with pytest.raises(CertificateError, match="expired"):
        load_identity(expired.p12(), PASSWORD)
    encrypt_only = make_credential(signing_usage=False)
    with pytest.raises(CertificateError, match="not allowed to sign"):
        load_identity(encrypt_only.p12(), PASSWORD)


def test_identity_details_come_from_the_certificate(identity):
    assert identity.name == "Test Signer"
    assert identity.email == "signer@example.com"
    assert identity.organization == "PDF Studio Tests"


# ------------------------------------------------------------------ sign -> validate
def test_invisible_signature_round_trip(identity):
    signed = sign(plain_pdf(), identity, SignOptions(reason="I approve", location="Berlin"))
    reports = validate(signed)
    assert len(reports) == 1
    report = reports[0]
    assert report.intact and report.valid
    assert report.covers_whole_file and report.modification == "none" and report.changes_allowed
    assert not report.trusted and report.signer.self_signed
    assert report.status == "unknown"  # intact, but nobody vouches for a self-signed identity
    assert "self-signed" in report.trust_note
    assert report.signer.name == "Test Signer"
    assert report.reason == "I approve" and report.location == "Berlin"
    assert report.rect is None and report.page == 0
    assert abs(dt.datetime.fromisoformat(report.signing_time) - NOW) < dt.timedelta(minutes=5)
    assert summarize(reports)["overall"] == "unknown"


def test_visible_signature_sits_where_it_was_drawn(identity):
    box = (100.0, 600.0, 300.0, 670.0)
    signed = sign(plain_pdf(), identity, SignOptions(placement=Placement(page=1, rect=box), reason="Checked"))
    doc = fitz.open("pdf", signed)
    (field,) = signature_fields(doc)
    assert field.signed and field.page == 1
    assert field.rect == pytest.approx(box, abs=0.01)
    pix = doc[1].get_pixmap(clip=fitz.Rect(box), dpi=72)
    assert len(set(pix.samples)) > 1, "the box must show the signature details"
    assert validate(signed)[0].intact


def test_visible_signature_on_a_rotated_page_with_an_image(identity):
    image = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 20), 0)
    image.set_rect(image.irect, (20, 40, 160))
    box = (400.0, 300.0, 560.0, 360.0)  # display space of a landscape (rotated) page
    options = SignOptions(placement=Placement(page=0, rect=box), image=image.tobytes("png"))
    signed = sign(plain_pdf(pages=1, rotation=90), identity, options)
    doc = fitz.open("pdf", signed)
    (field,) = signature_fields(doc)
    assert field.rect == pytest.approx(box, abs=0.01)
    pix = doc[0].get_pixmap(dpi=72)  # rendered as displayed (rotated)
    left = pix.pixel(int(box[0]) + 10, int((box[1] + box[3]) / 2))
    assert left[2] > left[0] + 60, "the signature image is drawn upright in the left part of the box"
    assert validate(signed)[0].intact


def test_a_box_outside_the_page_is_refused(identity):
    with pytest.raises(SignatureError, match="too small or outside"):
        sign(plain_pdf(), identity, SignOptions(placement=Placement(page=0, rect=(900, 900, 1000, 950))))


def test_multiple_signatures_each_stay_valid(identity):
    second_identity = load_identity(make_credential("Second Signer", elliptic=True).p12(), PASSWORD)
    once = sign(plain_pdf(), identity, SignOptions(placement=Placement(0, (72, 700, 250, 760))))
    twice = sign(once, second_identity, SignOptions(placement=Placement(1, (72, 700, 250, 760))))
    doc = fitz.open("pdf", twice)
    assert signed_count(doc) == 2
    assert [f.name for f in signature_fields(doc)] == ["Signature1", "Signature2"]
    first, second = validate(twice)
    assert first.intact and second.intact
    assert not first.covers_whole_file and first.modification == "form_filling" and first.changes_allowed
    assert first.status == "unknown"
    assert second.covers_whole_file and second.signer.name == "Second Signer"


def test_trusted_chain_is_reported_as_valid():
    ca = make_credential("Test Root CA", email=None, ca=True, days_valid=(-10, 365))
    leaf = make_credential("Chained Signer", issuer=ca)
    identity = load_identity(leaf.p12(chain=(ca.cert,)), PASSWORD)
    signed = sign(plain_pdf(), identity)
    trusted = validate(signed, roots=[ca.asn1_cert()])[0]
    assert trusted.trusted and trusted.status == "valid"
    assert trusted.signer.issuer == "Test Root CA" and not trusted.signer.self_signed
    untrusted = validate(signed)[0]
    assert not untrusted.trusted and untrusted.status == "unknown"
    assert "does not chain" in untrusted.trust_note


def test_timestamp_is_embedded_and_reported(identity):
    tsa = make_credential("Test TSA", email=None, signing_usage=False, timestamping=True)
    stamper = DummyTimeStamper(tsa_cert=tsa.asn1_cert(), tsa_key=tsa.asn1_key())
    signed = sign(plain_pdf(), identity, timestamper=stamper)
    report = validate(signed)[0]
    assert report.timestamp is not None and report.timestamp_valid is True
    assert report.intact


# ------------------------------------------------------------------ tamper detection
def test_changing_signed_bytes_breaks_the_signature(identity):
    signed = sign(plain_pdf(), identity)
    rewritten = fitz.open("pdf", signed).tobytes(garbage=1, deflate=True)  # a full rewrite moves the signed bytes
    report = validate(rewritten)[0]
    assert not report.intact and report.status == "invalid"
    patched = bytearray(signed)
    at = patched.find(b"Contract page 1")
    if at < 0:  # the text is compressed; flip a byte inside the first signed range instead
        at = 200
    patched[at] ^= 0x01
    assert validate(bytes(patched))[0].status == "invalid"


def test_an_appended_edit_is_reported_as_a_change_after_signing(identity):
    signed = sign(plain_pdf(), identity)
    writer = IncrementalPdfFileWriter(io.BytesIO(signed))
    page = writer.root["/Pages"]["/Kids"][0].get_object()
    page["/Rotate"] = generic.NumberObject(90)  # a change no signature permits
    writer.update_container(page)
    out = io.BytesIO()
    writer.write(out)
    report = validate(out.getvalue())[0]
    assert report.intact, "the signed revision itself is untouched"
    assert not report.covers_whole_file
    assert report.modification == "other" and not report.changes_allowed
    assert report.status == "modified"


def test_unreachable_timestamp_server_is_a_timestamp_error(identity):
    from pyhanko.sign.timestamps import HTTPTimeStamper

    from app.pdf.signing import TimestampError

    with pytest.raises(TimestampError):
        sign(plain_pdf(), identity, timestamper=HTTPTimeStamper("http://127.0.0.1:9/tsa", timeout=2))
