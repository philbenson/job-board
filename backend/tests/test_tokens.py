import time
from collections.abc import Callable

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from session_tokens import ABSENT, USER_ID, claims, forged, signed
from settings_for_tests import make_settings

from job_board.tokens import TOKEN_LEEWAY_SECONDS, TokenRefused, bearer_token, verify_session_token

SETTINGS = make_settings()
ANOTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def test_accepts_a_valid_token_and_names_its_person() -> None:
    assert verify_session_token(signed(claims()), SETTINGS) == USER_ID


def test_allows_for_a_little_clock_skew() -> None:
    expired_just_now = int(time.time()) - TOKEN_LEEWAY_SECONDS // 2
    assert verify_session_token(signed(claims(exp=expired_just_now)), SETTINGS) == USER_ID


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


@pytest.mark.parametrize("scheme", ["Bearer", "bearer", "BEARER"])
def test_takes_the_token_from_a_bearer_header(scheme: str) -> None:
    assert bearer_token(f"{scheme} abc.def.ghi") == "abc.def.ghi"


@pytest.mark.parametrize(
    ("header", "reason"),
    [
        (None, "missing"),
        ("", "missing"),
        ("abc.def.ghi", "malformed"),
        ("Basic dXNlcjpwYXNz", "malformed"),
        ("Bearer", "malformed"),
        ("Bearer ", "malformed"),
        ("Bearer abc def", "malformed"),
    ],
)
def test_refuses_a_header_without_one_bearer_token(header: str | None, reason: str) -> None:
    with pytest.raises(TokenRefused) as raised:
        bearer_token(header)
    assert raised.value.reason == reason
