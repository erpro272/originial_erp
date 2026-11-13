import base64
import os
import uuid

import pytest

from app.core.crypto import (
    DecryptionError,
    LocalKeyProvider,
    TenantCipher,
    mask_tail,
    new_data_key,
)

KEK = base64.b64encode(os.urandom(32)).decode()


def test_field_roundtrip_and_random_nonce() -> None:
    c = TenantCipher(uuid.uuid4(), new_data_key())
    a, b = c.encrypt("123456784417", "bank_account"), c.encrypt("123456784417", "bank_account")
    assert a != b  # fresh nonce every time
    assert c.decrypt(a, "bank_account") == "123456784417"
    assert b"4417" not in a


def test_ciphertext_bound_to_field() -> None:
    c = TenantCipher(uuid.uuid4(), new_data_key())
    blob = c.encrypt("secret", "bank_account")
    with pytest.raises(DecryptionError):
        c.decrypt(blob, "upi_id")


def test_ciphertext_bound_to_tenant_even_with_same_key() -> None:
    dek = new_data_key()
    blob = TenantCipher(uuid.uuid4(), dek).encrypt("secret", "f")
    with pytest.raises(DecryptionError):
        TenantCipher(uuid.uuid4(), dek).decrypt(blob, "f")


def test_tampering_detected() -> None:
    c = TenantCipher(uuid.uuid4(), new_data_key())
    blob = bytearray(c.encrypt("secret", "f"))
    blob[-1] ^= 1
    with pytest.raises(DecryptionError):
        c.decrypt(bytes(blob), "f")


def test_wrapped_key_bound_to_tenant() -> None:
    p = LocalKeyProvider(KEK)
    t1, t2 = uuid.uuid4(), uuid.uuid4()
    dek = new_data_key()
    wrapped = p.wrap(dek, t1)
    assert p.unwrap(wrapped, t1) == dek
    assert dek not in wrapped
    with pytest.raises(DecryptionError):
        p.unwrap(wrapped, t2)


def test_wrong_master_key_cannot_unwrap() -> None:
    t = uuid.uuid4()
    wrapped = LocalKeyProvider(KEK).wrap(new_data_key(), t)
    other = LocalKeyProvider(base64.b64encode(os.urandom(32)).decode())
    with pytest.raises(DecryptionError):
        other.unwrap(wrapped, t)


def test_master_key_length_checked() -> None:
    with pytest.raises(ValueError):
        LocalKeyProvider(base64.b64encode(b"short").decode())


@pytest.mark.parametrize(
    ("value", "expected"),
    [("123456784417", "XXXXXXXX4417"), ("4417", "XXXX"), ("", ""), (None, None)],
)
def test_mask_tail(value: str | None, expected: str | None) -> None:
    assert mask_tail(value) == expected
