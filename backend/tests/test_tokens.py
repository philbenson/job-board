import time
from collections.abc import Callable

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from session_tokens import ABSENT, USER_ID, claims, forged, signed
from settings_for_tests import make_settings

from job_board.tokens import TOKEN_LEEWAY_SECONDS, TokenRefused, verify_session_token

SETTINGS = make_settings()
ANOTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def test_accepts_a_valid_token_and_names_its_person() -> None:
    assert verify_session_token(signed(claims()), SETTINGS) == USER_ID


def test_allows_for_a_little_clock_skew() -> None:
    expired_just_now = int(time.time()) - TOKEN_LEEWAY_SECONDS // 2
    assert verify_session_token(signed(claims(exp=expired_just_now)), SETTINGS) == USER_ID


# Clerk marks a session waiting on a further step "pending"; older tokens carry no status.
@pytest.mark.parametrize("session_status", ["active", ABSENT], ids=["active", "no status"])
def test_accepts_a_session_that_is_active_or_has_no_status(session_status: object) -> None:
    assert verify_session_token(signed(claims(sts=session_status)), SETTINGS) == USER_ID


def an_hour(sign: int) -> int:
    return int(time.time()) + sign * 3600


REFUSALS: dict[str, tuple[Callable[[], str], str]] = {
    "expired": (lambda: signed(claims(exp=an_hour(-1))), "expired"),
    "not yet valid": (lambda: signed(claims(nbf=an_hour(+1))), "not-yet-valid"),
    "issued in the future": (lambda: signed(claims(iat=an_hour(+1))), "not-yet-valid"),
    "another issuer": (lambda: signed(claims(iss="https://other.example.com")), "issuer"),
    "no issuer": (lambda: signed(claims(iss=ABSENT)), "claims"),
    "no authorized party": (lambda: signed(claims(azp=ABSENT)), "party"),
    "a party not permitted": (lambda: signed(claims(azp="https://evil.example.com")), "party"),
    "a session still pending": (lambda: signed(claims(sts="pending")), "pending"),
    "signed by another key": (lambda: signed(claims(), ANOTHER_KEY), "signature"),
    "HS256 keyed with the public key": (lambda: forged("HS256", claims()), "signature"),
    "alg none": (lambda: forged("none", claims()), "signature"),
    "no expiry": (lambda: signed(claims(exp=ABSENT)), "claims"),
    "no subject": (lambda: signed(claims(sub=ABSENT)), "claims"),
    "an empty subject": (lambda: signed(claims(sub="")), "claims"),
    "a subject that is not text": (lambda: signed(claims(sub=42)), "claims"),
    "not a token at all": (lambda: "not-a-token", "malformed"),
}


@pytest.mark.parametrize(("token", "reason"), REFUSALS.values(), ids=REFUSALS.keys())
def test_refuses_with_a_reason(token: Callable[[], str], reason: str) -> None:
    with pytest.raises(TokenRefused) as raised:
        verify_session_token(token(), SETTINGS)
    assert raised.value.reason == reason
