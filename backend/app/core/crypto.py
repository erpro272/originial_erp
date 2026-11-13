"""Layer 2: per-tenant AES-256-GCM field encryption (envelope encryption).

* Each tenant has its own 256-bit data-encryption key (DEK).
* The DEK is stored only in wrapped form (encrypted with the key-encryption key, KEK,
  via AES-256-GCM, with the tenant id as associated data so a wrapped key cannot be
  moved to another tenant).
* The KEK comes from a ``KeyProvider``. ``LocalKeyProvider`` reads it from settings;
  a KMS-backed provider can replace it without touching callers.
* Ciphertext format: ``b"v1" + nonce(12) + ciphertext+tag``. Associated data binds
  each value to its tenant and field, so ciphertext copied between rows/fields fails.
"""

import base64
import os
import uuid
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

_VERSION = b"v1"
_NONCE_LEN = 12


class DecryptionError(Exception):
    """Raised when ciphertext is tampered with, or used with the wrong tenant/field."""


class KeyProvider(Protocol):
    def wrap(self, dek: bytes, tenant_id: uuid.UUID) -> bytes: ...
    def unwrap(self, wrapped: bytes, tenant_id: uuid.UUID) -> bytes: ...


class LocalKeyProvider:
    """KEK held in process memory, loaded from ``ERP_MASTER_KEY`` (base64, 32 bytes)."""

    def __init__(self, master_key_b64: str) -> None:
        kek = base64.b64decode(master_key_b64)
        if len(kek) != 32:
            raise ValueError("ERP_MASTER_KEY must be 32 bytes, base64-encoded")
        self._aes = AESGCM(kek)

    def wrap(self, dek: bytes, tenant_id: uuid.UUID) -> bytes:
        nonce = os.urandom(_NONCE_LEN)
        return _VERSION + nonce + self._aes.encrypt(nonce, dek, b"dek:" + tenant_id.bytes)

    def unwrap(self, wrapped: bytes, tenant_id: uuid.UUID) -> bytes:
        try:
            return _open(self._aes, wrapped, b"dek:" + tenant_id.bytes)
        except InvalidTag as exc:
            raise DecryptionError("cannot unwrap tenant key") from exc


def _open(aes: AESGCM, blob: bytes, aad: bytes) -> bytes:
    if blob[:2] != _VERSION:
        raise DecryptionError("unknown ciphertext version")
    nonce, ct = blob[2 : 2 + _NONCE_LEN], blob[2 + _NONCE_LEN :]
    return aes.decrypt(nonce, ct, aad)


def get_key_provider() -> KeyProvider:
    return LocalKeyProvider(get_settings().master_key.get_secret_value())


def new_data_key() -> bytes:
    return AESGCM.generate_key(bit_length=256)


class TenantCipher:
    """Encrypts/decrypts field values for ONE tenant using its unwrapped DEK."""

    def __init__(self, tenant_id: uuid.UUID, dek: bytes) -> None:
        self.tenant_id = tenant_id
        self._aes = AESGCM(dek)

    def _aad(self, field: str) -> bytes:
        return self.tenant_id.bytes + b"|" + field.encode()

    def encrypt(self, plaintext: str, field: str) -> bytes:
        nonce = os.urandom(_NONCE_LEN)
        return _VERSION + nonce + self._aes.encrypt(nonce, plaintext.encode(), self._aad(field))

    def encrypt_bytes(self, data: bytes, context: str) -> bytes:
        """For stored files: the object key is the context, so files can't be swapped."""
        nonce = os.urandom(_NONCE_LEN)
        return _VERSION + nonce + self._aes.encrypt(nonce, data, self._aad("file:" + context))

    def decrypt_bytes(self, blob: bytes, context: str) -> bytes:
        try:
            return _open(self._aes, blob, self._aad("file:" + context))
        except InvalidTag as exc:
            raise DecryptionError("cannot decrypt file") from exc

    def decrypt(self, blob: bytes, field: str) -> str:
        try:
            return _open(self._aes, blob, self._aad(field)).decode()
        except InvalidTag as exc:
            raise DecryptionError(f"cannot decrypt field {field!r}") from exc


def mask_tail(value: str | None, visible: int = 4, mask_char: str = "X") -> str | None:
    """``"123456784417"`` -> ``"XXXXXXXX4417"``. Short values are fully masked."""
    if value is None:
        return None
    if len(value) <= visible:
        return mask_char * len(value)
    return mask_char * (len(value) - visible) + value[-visible:]
