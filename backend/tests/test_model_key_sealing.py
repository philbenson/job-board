import os

import pytest

from job_board.model_key.sealing import SealBroken, open_sealed, seal

SERVICE_KEY = os.urandom(32)
KEY = "sk-ant-api03-placeholder-key-for-tests-only-abcd"
PERSON = 41
PROVIDER = "anthropic"


def test_opens_what_it_sealed() -> None:
    sealed = seal(KEY, PERSON, PROVIDER, service_key=SERVICE_KEY)
    assert open_sealed(sealed, PERSON, PROVIDER, service_key=SERVICE_KEY) == KEY


def test_stores_a_version_byte_then_the_nonce_then_the_ciphertext_and_its_tag() -> None:
    sealed = seal(KEY, PERSON, PROVIDER, service_key=SERVICE_KEY)
    assert sealed[0] == 1
    assert len(sealed) == 1 + 12 + len(KEY.encode()) + 16
    assert KEY.encode() not in sealed


def test_two_seals_of_one_key_differ() -> None:
    first = seal(KEY, PERSON, PROVIDER, service_key=SERVICE_KEY)
    second = seal(KEY, PERSON, PROVIDER, service_key=SERVICE_KEY)
    assert first[1:13] != second[1:13]  # a fresh nonce each time
    assert first != second


def flipped(sealed: bytes, index: int) -> bytes:
    return sealed[:index] + bytes([sealed[index] ^ 0x01]) + sealed[index + 1 :]


SEALED = seal(KEY, PERSON, PROVIDER, service_key=SERVICE_KEY)

# Each way a sealed key can fail to be the one its reader expects.
WRONG_OPENINGS: dict[str, tuple[bytes, int, str, bytes]] = {
    "another person": (SEALED, PERSON + 1, PROVIDER, SERVICE_KEY),
    "another provider": (SEALED, PERSON, "openai", SERVICE_KEY),
    "another service key": (SEALED, PERSON, PROVIDER, os.urandom(32)),
    "an unknown version byte": (bytes([2]) + SEALED[1:], PERSON, PROVIDER, SERVICE_KEY),
    "a tampered nonce": (flipped(SEALED, 1), PERSON, PROVIDER, SERVICE_KEY),
    "a tampered ciphertext": (flipped(SEALED, 13), PERSON, PROVIDER, SERVICE_KEY),
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
