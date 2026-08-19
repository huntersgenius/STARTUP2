from __future__ import annotations

import pytest

from app.core.crypto import DecryptionError, decrypt_blob, encrypt_blob


def test_roundtrip_preserves_unicode():
    payload = {"full_name": "Aziza Yusupova", "address": "Chinoz tumani, Navro'z MFY"}
    assert decrypt_blob(encrypt_blob(payload)) == payload


def test_ciphertext_contains_no_plaintext():
    blob = encrypt_blob({"full_name": "Aziza Yusupova", "passport": "AA1234567"})
    assert b"Aziza" not in blob
    assert b"AA1234567" not in blob


def test_nonce_is_random_so_equal_payloads_differ():
    payload = {"full_name": "Aziza Yusupova"}
    assert encrypt_blob(payload) != encrypt_blob(payload)


def test_tampering_is_detected():
    blob = bytearray(encrypt_blob({"full_name": "Aziza"}))
    blob[-1] ^= 0x01
    with pytest.raises(DecryptionError):
        decrypt_blob(bytes(blob))


def test_aad_binds_blob_to_its_row():
    blob = encrypt_blob({"full_name": "Aziza"}, aad=b"patient-1")
    with pytest.raises(DecryptionError):
        decrypt_blob(blob, aad=b"patient-2")


def test_unknown_version_rejected():
    with pytest.raises(DecryptionError):
        decrypt_blob(b"\x99" + b"0" * 40)
