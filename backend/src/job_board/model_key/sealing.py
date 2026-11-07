"""Sealing a person's model key so that only this service can open it.

Invariant: a sealed key opens only with the service's key, for the person and
provider it was sealed for. The person's id and the provider are bound into
the seal as associated data, so a sealed key copied onto another person's row,
or read as another provider's, fails to open rather than opening as theirs.

A sealed key is one version byte, then a four-byte key id, then the nonce, then
the ciphertext with its tag: AES-256-GCM, with a fresh random nonce for every
seal. The key id names the service key that made the seal without revealing it,
so a seal made under an earlier service key is told apart from a damaged one,
and the person can be asked to enter their key again. The key id is bound into
the associated data too. No deployment held a sealed key when the key id was
added, so version 1 took it on without a new version byte.
"""

import hashlib
import hmac
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

VERSION = 1  # the first byte of every sealed key, so the format can change without guessing
KEY_ID_BYTES = 4  # enough to tell service keys apart; it is not a secret
KEY_ID_LABEL = b"model-key-id"
NONCE_BYTES = 12  # the nonce length AES-GCM is designed for
TAG_BYTES = 16  # AES-GCM's full-length tag, which the library appends to the ciphertext
ASSOCIATED_DATA_PREFIX = b"model-key:v1:"


class SealBroken(Exception):
    """A sealed key that will not open for this person, provider and service key.

    Raised for every cause alike, and carries none of the sealed bytes or the key.
    """

    def __init__(self) -> None:
        super().__init__("the sealed model key could not be opened")


class SealedUnderAnotherKey(SealBroken):
    """A sealed key whose key id names a service key other than this one."""


def key_id(service_key: bytes) -> bytes:
    return hmac.new(service_key, KEY_ID_LABEL, hashlib.sha256).digest()[:KEY_ID_BYTES]


def _associated_data(key_id: bytes, person_id: int, provider: str) -> bytes:
    return ASSOCIATED_DATA_PREFIX + key_id + f"{person_id}:{provider}".encode()


def seal(plaintext: str, person_id: int, provider: str, *, service_key: bytes) -> bytes:
    """The key sealed for this person and provider under the service's key."""
    named = key_id(service_key)
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(service_key).encrypt(
        nonce, plaintext.encode(), _associated_data(named, person_id, provider)
    )
    return bytes([VERSION]) + named + nonce + ciphertext


def sealed_with(sealed: bytes, *, service_key: bytes) -> bool:
    """Whether the seal names this service key, read without opening it."""
    return (
        len(sealed) >= 1 + KEY_ID_BYTES
        and sealed[0] == VERSION
        and hmac.compare_digest(sealed[1 : 1 + KEY_ID_BYTES], key_id(service_key))
    )


def open_sealed(sealed: bytes, person_id: int, provider: str, *, service_key: bytes) -> str:
    """The key a seal holds, or SealBroken; it never returns text it cannot vouch for.

    A well-formed seal that names another service key raises SealedUnderAnotherKey.
    """
    if len(sealed) < 1 + KEY_ID_BYTES + NONCE_BYTES + TAG_BYTES or sealed[0] != VERSION:
        raise SealBroken
    if not sealed_with(sealed, service_key=service_key):
        raise SealedUnderAnotherKey
    named = sealed[1 : 1 + KEY_ID_BYTES]
    nonce = sealed[1 + KEY_ID_BYTES : 1 + KEY_ID_BYTES + NONCE_BYTES]
    ciphertext = sealed[1 + KEY_ID_BYTES + NONCE_BYTES :]
    try:
        plaintext = AESGCM(service_key).decrypt(
            nonce, ciphertext, _associated_data(named, person_id, provider)
        )
    except InvalidTag:
        raise SealBroken from None
    return plaintext.decode()
