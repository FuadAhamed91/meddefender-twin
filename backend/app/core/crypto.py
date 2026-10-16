"""Cryptographic primitives for simulated device identities and user sessions.

Device keys are derived from a master secret held only in the backend environment
(standing in for a KMS/HSM). The database stores key versions and fingerprints, never keys.
HMAC-SHA-256 provides integrity and authenticity under the shared-secret model. It does not
encrypt payloads and cannot detect a party that holds a valid device key.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets

KEY_DERIVATION_LABEL = b"meddefender-device-key|v1|"
SIGNATURE_SCHEME = "hmac-sha256"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def derive_device_key(master_secret: bytes, device_id: str, key_version: int) -> bytes:
    """Derive the per-device, per-version HMAC key (an HKDF-like PRF expansion)."""
    if key_version < 1:
        raise ValueError("key_version must be >= 1")
    info = KEY_DERIVATION_LABEL + device_id.encode("utf-8") + b"|" + str(key_version).encode()
    return hmac.new(master_secret, info, hashlib.sha256).digest()


def key_fingerprint(key: bytes) -> str:
    """Non-reversible identifier for a key (first 16 hex chars of SHA-256)."""
    return hashlib.sha256(key).hexdigest()[:16]


def sign(key: bytes, raw: bytes) -> str:
    return hmac.new(key, raw, hashlib.sha256).hexdigest()


def format_signature_header(signature_hex: str) -> str:
    return f"{SIGNATURE_SCHEME}={signature_hex}"


def parse_signature_header(value: str | None) -> str | None:
    """Return the lowercase hex MAC from ``hmac-sha256=<hex>``, or None if malformed."""
    if not value or len(value) > 200:
        return None
    scheme, sep, mac = value.strip().partition("=")
    if not sep or scheme.strip().lower() != SIGNATURE_SCHEME:
        return None
    mac = mac.strip().lower()
    return mac if _HEX64.match(mac) else None


def verify(key: bytes, raw: bytes, presented_hex: str) -> bool:
    """Constant-time comparison of the expected and presented MACs."""
    if not _HEX64.match(presented_hex):
        return False
    expected = hmac.new(key, raw, hashlib.sha256).digest()
    return hmac.compare_digest(expected, bytes.fromhex(presented_hex))


def message_digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """Session and CSRF tokens are stored only as SHA-256 hashes."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
