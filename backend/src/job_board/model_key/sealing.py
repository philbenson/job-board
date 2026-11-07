"""Sealing a person's model key so that only this service can open it.

Invariant: a sealed key opens only with the service's key, for the person and
provider it was sealed for. The person's id and the provider are bound into
the seal as associated data, so a sealed key copied onto another person's row,
or read as another provider's, fails to open rather than opening as theirs.

A sealed key is one version byte, then the nonce, then the ciphertext with its
tag: AES-256-GCM, with a fresh random nonce for every seal.
"""

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

VERSION = 1  # the first byte of every sealed key, so the format can change without guessing
NONCE_BYTES = 12  # the nonce length AES-GCM is designed for
TAG_BYTES = 16  # AES-GCM's full-length tag, which the library appends to the ciphertext
ASSOCIATED_DATA_PREFIX = b"model-key:v1:"


class SealBroken(Exception):
    """A sealed key that will not open for this person, provider and service key.

    Raised for every cause alike, and carries none of the sealed bytes or the key.
    """

    def __init__(self) -> None:
        super().__init__("the sealed model key could not be opened")


def _associated_data(person_id: int, provider: str) -> bytes:
    return ASSOCIATED_DATA_PREFIX + f"{person_id}:{provider}".encode()


def seal(plaintext: str, person_id: int, provider: str, *, service_key: bytes) -> bytes:
    """The key sealed for this person and provider under the service's key."""
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(service_key).encrypt(
        nonce, plaintext.encode(), _associated_data(person_id, provider)
    )
    return bytes([VERSION]) + nonce + ciphertext


def open_sealed(sealed: bytes, person_id: int, provider: str, *, service_key: bytes) -> str:
    """The key a seal holds, or SealBroken; it never returns text it cannot vouch for."""
    if len(sealed) < 1 + NONCE_BYTES + TAG_BYTES or sealed[0] != VERSION:
        raise SealBroken
    nonce, ciphertext = sealed[1 : 1 + NONCE_BYTES], sealed[1 + NONCE_BYTES :]
    try:
        plaintext = AESGCM(service_key).decrypt(
            nonce, ciphertext, _associated_data(person_id, provider)
        )
    except InvalidTag:
        raise SealBroken from None
    return plaintext.decode()
