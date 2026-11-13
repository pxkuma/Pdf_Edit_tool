"""Trust anchors for signature validation.

pyHanko's default trust store goes through ``oscrypto``, whose OpenSSL version detection fails on
current OpenSSL 3 releases. So the roots are read here directly: the system CA bundle (TLS roots,
which few document-signing CAs are part of), plus an optional PEM bundle the operator configures
(``PDF_STUDIO_TRUST_ROOTS``), e.g. the Adobe AATL or EU trusted-list roots their signers use.
"""

from __future__ import annotations

import logging
import ssl
import sys
from functools import lru_cache
from pathlib import Path

from asn1crypto import pem, x509

log = logging.getLogger(__name__)

SYSTEM_BUNDLES = (
    "/etc/ssl/certs/ca-certificates.crt",  # Debian/Ubuntu
    "/etc/pki/tls/certs/ca-bundle.crt",  # Fedora/RHEL
    "/etc/ssl/cert.pem",  # Alpine/macOS
)


def _read_bundle(path: Path) -> list[x509.Certificate]:
    try:
        data = path.read_bytes()
    except OSError:
        return []
    certs: list[x509.Certificate] = []
    if pem.detect(data):
        for _type, _headers, der in pem.unarmor(data, multiple=True):
            try:
                certs.append(x509.Certificate.load(der))
            except ValueError:
                continue
    else:
        try:
            certs.append(x509.Certificate.load(data))
        except ValueError:
            pass
    return certs


def _windows_roots() -> list[x509.Certificate]:
    """Trusted root certificates from the Windows certificate store (there is no CA bundle file there)."""
    if sys.platform != "win32":
        return []
    certs: list[x509.Certificate] = []
    try:
        for der, encoding, _trust in ssl.enum_certificates("ROOT"):
            if encoding != "x509_asn":
                continue
            try:
                certs.append(x509.Certificate.load(der))
            except ValueError:
                continue
    except OSError:
        log.warning("The Windows certificate store could not be read", exc_info=True)
    return certs


def _system_bundle() -> Path | None:
    candidates = [ssl.get_default_verify_paths().cafile, *SYSTEM_BUNDLES]
    try:
        import certifi  # optional, present as a dependency of the HTTP stack

        candidates.append(certifi.where())
    except ImportError:
        pass
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


@lru_cache(maxsize=4)
def trust_roots(extra_bundle: str | None = None) -> tuple[x509.Certificate, ...]:
    roots: list[x509.Certificate] = _windows_roots()
    bundle = _system_bundle()
    if bundle:
        roots.extend(_read_bundle(bundle))
    if extra_bundle:
        extra = _read_bundle(Path(extra_bundle))
        if not extra:
            log.warning("No certificates could be read from the configured trust roots file")
        roots.extend(extra)
    return tuple(roots)
