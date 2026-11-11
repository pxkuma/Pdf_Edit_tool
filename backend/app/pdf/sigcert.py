"""Load a signing identity from a PKCS#12 (.p12/.pfx) archive held in memory.

The archive and its password are never written anywhere: callers pass bytes in and drop them after
signing. Error messages never include the password.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from asn1crypto import pkcs12 as asn1_pkcs12
from cryptography import x509
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtensionOID, NameOID
from pyhanko.sign import signers

MAX_CERT_BYTES = 256 * 1024
MAX_PASSWORD_CHARS = 256


class CertificateError(ValueError):
    """The certificate file or its password cannot be used for signing."""


@dataclass(frozen=True)
class SigningIdentity:
    signer: signers.SimpleSigner
    name: str
    email: str
    organization: str
    issuer: str
    not_after: dt.datetime


def _attr(name: x509.Name, oid: x509.ObjectIdentifier) -> str:
    values = name.get_attributes_for_oid(oid)
    return str(values[0].value) if values else ""


def describe_name(name: x509.Name) -> str:
    return _attr(name, NameOID.COMMON_NAME) or _attr(name, NameOID.ORGANIZATION_NAME) or name.rfc4514_string()


def cert_email(cert: x509.Certificate) -> str:
    try:
        san = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
        emails = san.get_values_for_type(x509.RFC822Name)
        if emails:
            return emails[0]
    except x509.ExtensionNotFound:
        pass
    return _attr(cert.subject, NameOID.EMAIL_ADDRESS)


def _is_pkcs12(data: bytes) -> bool:
    try:
        asn1_pkcs12.Pfx.load(data)["auth_safe"].native  # noqa: B018 - forces a full parse
        return True
    except Exception:  # noqa: BLE001 - any parse failure means "not a PKCS#12 file"
        return False


def _check_usable(cert: x509.Certificate, now: dt.datetime) -> None:
    if now < cert.not_valid_before_utc:
        raise CertificateError(f"This certificate is not valid until {cert.not_valid_before_utc:%Y-%m-%d}.")
    if now > cert.not_valid_after_utc:
        raise CertificateError(f"This certificate expired on {cert.not_valid_after_utc:%Y-%m-%d}.")
    try:
        usage = cert.extensions.get_extension_for_oid(ExtensionOID.KEY_USAGE).value
    except x509.ExtensionNotFound:
        return
    if not (usage.digital_signature or usage.content_commitment):
        raise CertificateError("This certificate is not allowed to sign documents (its key usage excludes signing).")


def load_identity(data: bytes, password: str, now: dt.datetime | None = None) -> SigningIdentity:
    """Open a PKCS#12 archive and check that its certificate can sign today."""
    if not data:
        raise CertificateError("The certificate file is empty.")
    if len(data) > MAX_CERT_BYTES:
        raise CertificateError("The certificate file is too large to be a .p12/.pfx certificate.")
    if len(password) > MAX_PASSWORD_CHARS:
        raise CertificateError("The certificate password is too long.")
    if not _is_pkcs12(data):
        raise CertificateError("This file is not a PKCS#12 certificate. Choose a .p12 or .pfx file.")
    passphrase = password.encode("utf-8") if password else None
    try:
        key, cert, _extra = pkcs12.load_key_and_certificates(data, passphrase)
    except ValueError as exc:
        raise CertificateError("The certificate password is incorrect.") from exc
    except Exception as exc:  # noqa: BLE001 - unsupported algorithms surface as various errors
        raise CertificateError("This certificate uses a format or algorithm that is not supported.") from exc
    if key is None:
        raise CertificateError("The certificate file has no private key, so it cannot sign.")
    if cert is None:
        raise CertificateError("The certificate file has no certificate for its private key.")
    _check_usable(cert, now or dt.datetime.now(dt.timezone.utc))
    try:
        signer = signers.SimpleSigner.load_pkcs12_data(data, other_certs=[], passphrase=passphrase)
    except ValueError as exc:
        raise CertificateError("The certificate could not be loaded for signing.") from exc
    return SigningIdentity(
        signer=signer,
        name=describe_name(cert.subject),
        email=cert_email(cert),
        organization=_attr(cert.subject, NameOID.ORGANIZATION_NAME),
        issuer=describe_name(cert.issuer),
        not_after=cert.not_valid_after_utc,
    )
