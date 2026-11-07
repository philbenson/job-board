import hashlib
import hmac
import os

import pytest

from job_board.model_key.sealing import (
    SealBroken,
    SealedUnderAnotherKey,
    open_sealed,
    seal,
    sealed_with,
)

SERVICE_KEY = os.urandom(32)
KEY = "sk-ant-api03-placeholder-key-for-tests-only-abcd"
PERSON = 41
PROVIDER = "anthropic"


def test_opens_what_it_sealed() -> None:
    sealed = seal(KEY, PERSON, PROVIDER, service_key=SERVICE_KEY)
    assert open_sealed(sealed, PERSON, PROVIDER, service_key=SERVICE_KEY) == KEY


def key_id(service_key: bytes) -> bytes:
    return hmac.new(service_key, b"model-key-id", hashlib.sha256).digest()[:4]


def test_stores_a_version_byte_the_key_id_the_nonce_then_the_ciphertext_and_its_tag() -> None:
    sealed = seal(KEY, PERSON, PROVIDER, service_key=SERVICE_KEY)
    assert sealed[0] == 1
    assert sealed[1:5] == key_id(SERVICE_KEY)
    assert len(sealed) == 1 + 4 + 12 + len(KEY.encode()) + 16
    assert KEY.encode() not in sealed


def test_two_seals_of_one_key_differ() -> None:
    first = seal(KEY, PERSON, PROVIDER, service_key=SERVICE_KEY)
    second = seal(KEY, PERSON, PROVIDER, service_key=SERVICE_KEY)
    assert first[5:17] != second[5:17]  # a fresh nonce each time
    assert first != second


def test_tells_a_seal_made_under_another_service_key() -> None:
    other_key = os.urandom(32)
    sealed = seal(KEY, PERSON, PROVIDER, service_key=other_key)

    assert sealed_with(sealed, service_key=other_key)
    assert not sealed_with(sealed, service_key=SERVICE_KEY)
    with pytest.raises(SealedUnderAnotherKey):
        open_sealed(sealed, PERSON, PROVIDER, service_key=SERVICE_KEY)


def test_a_key_id_rewritten_to_this_service_keys_still_does_not_open() -> None:
    sealed = seal(KEY, PERSON, PROVIDER, service_key=os.urandom(32))
    rewritten = sealed[:1] + key_id(SERVICE_KEY) + sealed[5:]

    assert sealed_with(rewritten, service_key=SERVICE_KEY)
    with pytest.raises(SealBroken) as raised:
        open_sealed(rewritten, PERSON, PROVIDER, service_key=SERVICE_KEY)
    assert type(raised.value) is SealBroken  # tampered, not merely sealed under another key


def test_is_not_sealed_with_any_key_when_too_short_to_hold_a_key_id() -> None:
    assert not sealed_with(b"\x01ab", service_key=SERVICE_KEY)


def flipped(sealed: bytes, index: int) -> bytes:
    return sealed[:index] + bytes([sealed[index] ^ 0x01]) + sealed[index + 1 :]


SEALED = seal(KEY, PERSON, PROVIDER, service_key=SERVICE_KEY)

# Each way a sealed key can fail to be the one its reader expects.
WRONG_OPENINGS: dict[str, tuple[bytes, int, str, bytes]] = {
    "another person": (SEALED, PERSON + 1, PROVIDER, SERVICE_KEY),
    "another provider": (SEALED, PERSON, "openai", SERVICE_KEY),
    "another service key": (SEALED, PERSON, PROVIDER, os.urandom(32)),
    "an unknown version byte": (bytes([2]) + SEALED[1:], PERSON, PROVIDER, SERVICE_KEY),
    "a tampered key id": (flipped(SEALED, 1), PERSON, PROVIDER, SERVICE_KEY),
    "a tampered nonce": (flipped(SEALED, 5), PERSON, PROVIDER, SERVICE_KEY),
    "a tampered ciphertext": (flipped(SEALED, 17), PERSON, PROVIDER, SERVICE_KEY),
    "a tampered tag": (flipped(SEALED, len(SEALED) - 1), PERSON, PROVIDER, SERVICE_KEY),
    "a cut-off seal": (SEALED[:20], PERSON, PROVIDER, SERVICE_KEY),
    "nothing at all": (b"", PERSON, PROVIDER, SERVICE_KEY),
}


@pytest.mark.parametrize(
    ("sealed", "person_id", "provider", "service_key"),
    WRONG_OPENINGS.values(),
    ids=WRONG_OPENINGS.keys(),
)
def test_refuses_to_open_for_anyone_or_anything_else(
    sealed: bytes, person_id: int, provider: str, service_key: bytes
) -> None:
    with pytest.raises(SealBroken) as raised:
        open_sealed(sealed, person_id, provider, service_key=service_key)
    assert KEY not in str(raised.value)
