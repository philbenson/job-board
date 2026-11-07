"""Session tokens shaped like Clerk's, signed here so no test needs Clerk."""

import base64
import hashlib
import hmac
import json
import time
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from settings_for_tests import ISSUER, ORIGIN, PUBLIC_PEM, SIGNING_KEY

USER_ID = "user_2pTestPerson0000000000000"
ABSENT = object()  # a claim value meaning "leave this claim out"


def claims(**overrides: object) -> dict[str, Any]:
    """A valid session token's claims, with any of them replaced or left out."""
    now = int(time.time())
    values: dict[str, Any] = {
        "iss": ISSUER,
        "sub": USER_ID,
        "azp": ORIGIN,
        "sid": "sess_2pTestSession000000000000",
        "iat": now,
        "nbf": now - 10,
        "exp": now + 60,
    }
    values.update(overrides)
    return {name: value for name, value in values.items() if value is not ABSENT}


def signed(payload: dict[str, Any], key: rsa.RSAPrivateKey = SIGNING_KEY) -> str:
    return jwt.encode(payload, key, algorithm="RS256")


def _segment(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def forged(algorithm: str, payload: dict[str, Any]) -> str:
    """A token that names another algorithm, built by hand since PyJWT refuses to.

    ``HS256`` is signed with the public key's PEM as the shared secret: the
    algorithm-confusion attack, which works on a verifier that lets the token
    choose its algorithm. ``none`` carries no signature at all.
    """
    header = _segment(json.dumps({"alg": algorithm, "typ": "JWT"}).encode())
    body = _segment(json.dumps(payload).encode())
    signing_input = f"{header}.{body}".encode()
    if algorithm == "none":
        return f"{header}.{body}."
    signature = hmac.new(PUBLIC_PEM.encode(), signing_input, hashlib.sha256).digest()
    return f"{header}.{body}.{_segment(signature)}"
