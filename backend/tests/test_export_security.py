"""Exported permissions (no copy / print / modify) must hold for people who only know the open password."""

from __future__ import annotations

import pymupdf as fitz

from app.pdf import doctools
from app.pdf.doctools import ExportOptions

# authenticate() returns a bit field: 1 = no password needed, 2 = user password, 4 = owner password
USER_ACCESS, OWNER_ACCESS = 2, 4


def _export(sample_pdf: bytes, **options) -> bytes:
    return doctools.export_pdf(sample_pdf, ExportOptions(**options))


def test_user_password_alone_does_not_grant_owner_rights(sample_pdf):
    locked = fitz.open(stream=_export(sample_pdf, user_password="open-me", allow_copy=False, allow_print=False))
    access = locked.authenticate("open-me")
    assert access & USER_ACCESS
    assert not access & OWNER_ACCESS, "the user password must not also be the owner password"
    assert not locked.permissions & fitz.PDF_PERM_COPY
    assert not locked.permissions & fitz.PDF_PERM_PRINT


def test_the_generated_owner_password_is_not_guessable(sample_pdf):
    locked = fitz.open(stream=_export(sample_pdf, user_password="open-me", allow_copy=False))
    for guess in ("", "open-me", "owner", "password"):
        assert not locked.authenticate(guess) & OWNER_ACCESS, guess


def test_an_explicit_owner_password_is_honoured(sample_pdf):
    locked = fitz.open(stream=_export(sample_pdf, user_password="open-me", owner_password="boss", allow_copy=False))
    assert locked.authenticate("open-me") & USER_ACCESS
    assert not locked.permissions & fitz.PDF_PERM_COPY
    unlocked = fitz.open(stream=_export(sample_pdf, user_password="open-me", owner_password="boss", allow_copy=False))
    assert unlocked.authenticate("boss") & OWNER_ACCESS


def test_owner_password_alone_encrypts_without_asking_to_open(sample_pdf):
    locked = fitz.open(stream=_export(sample_pdf, owner_password="boss", allow_copy=False))
    assert not locked.needs_pass or locked.authenticate("")
    assert not locked.permissions & fitz.PDF_PERM_COPY


def test_export_endpoint_keeps_restrictions_for_the_user_password(client, doc):
    response = client.post(f"/api/documents/{doc['id']}/export", json={"user_password": "pw", "allow_copy": False})
    assert response.status_code == 200
    locked = fitz.open(stream=response.content)
    assert locked.authenticate("pw") & USER_ACCESS and not locked.authenticate("pw") & OWNER_ACCESS
    assert not locked.permissions & fitz.PDF_PERM_COPY


def test_too_long_passwords_are_a_validation_error_not_a_crash(client, doc):
    response = client.post(f"/api/documents/{doc['id']}/export", json={"user_password": "x" * 41})
    assert response.status_code == 422
    assert "user_password" in response.json()["error"]


def test_no_passwords_means_no_encryption(sample_pdf):
    assert not fitz.open(stream=_export(sample_pdf)).is_encrypted
