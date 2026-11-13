"""Throw-away certificates for the digital-signature tests (generated, never stored)."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from asn1crypto import keys as asn1_keys
from asn1crypto import x509 as asn1_x509
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

PASSWORD = "correct horse"


@dataclass(frozen=True)
class Credential:
    key: object
    cert: x509.Certificate

    def p12(self, password: str = PASSWORD, chain: tuple[x509.Certificate, ...] = ()) -> bytes:
        encryption = serialization.BestAvailableEncryption(password.encode()) if password else serialization.NoEncryption()
        return pkcs12.serialize_key_and_certificates(b"signer", self.key, self.cert, list(chain) or None, encryption)

    def asn1_cert(self) -> asn1_x509.Certificate:
        return asn1_x509.Certificate.load(self.cert.public_bytes(serialization.Encoding.DER))

    def asn1_key(self) -> asn1_keys.PrivateKeyInfo:
        der = self.key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        return asn1_keys.PrivateKeyInfo.load(der)


def _name(common_name: str, email: str | None = None) -> x509.Name:
    attrs = [x509.NameAttribute(NameOID.COMMON_NAME, common_name), x509.NameAttribute(NameOID.ORGANIZATION_NAME, "PDF Studio Tests")]
    if email:
        attrs.append(x509.NameAttribute(NameOID.EMAIL_ADDRESS, email))
    return x509.Name(attrs)


def make_credential(
    common_name: str = "Test Signer",
    email: str | None = "signer@example.com",
    issuer: Credential | None = None,
    ca: bool = False,
    days_valid: tuple[int, int] = (-1, 30),
    signing_usage: bool = True,
    timestamping: bool = False,
    elliptic: bool = False,
) -> Credential:
    key = ec.generate_private_key(ec.SECP256R1()) if elliptic else rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = dt.datetime.now(dt.timezone.utc)
    subject = _name(common_name, email)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer.cert.subject if issuer else subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now + dt.timedelta(days=days_valid[0]))
        .not_valid_after(now + dt.timedelta(days=days_valid[1]))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=signing_usage or ca or timestamping, content_commitment=signing_usage and not ca,
                key_encipherment=not signing_usage, data_encipherment=False, key_agreement=False,
                key_cert_sign=ca, crl_sign=ca, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
    )
    if email:
        builder = builder.add_extension(x509.SubjectAlternativeName([x509.RFC822Name(email)]), critical=False)
    if timestamping:
        builder = builder.add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.TIME_STAMPING]), critical=True)
    signing_key = issuer.key if issuer else key
    cert = builder.sign(signing_key, hashes.SHA256())
    return Credential(key=key, cert=cert)
