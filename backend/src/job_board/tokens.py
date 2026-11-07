"""Checking Clerk session tokens, without a call to Clerk.

Invariant: a token names a person only when it is signed with RS256 by the
configured key, was issued by the configured Clerk instance, is inside its
validity window (give or take TOKEN_LEEWAY_SECONDS), was requested by a page
whose origin is permitted, and carries a non-empty subject. Anything else is
refused with a short reason code, which is safe to log: it never carries the
token or any of its claims.
"""

from typing import Any, Literal

import jwt

from job_board.settings import Settings

TOKEN_LEEWAY_SECONDS = 5  # clock difference tolerated between Clerk and this server
ALGORITHMS = ["RS256"]  # Clerk's only algorithm; the token's own header never chooses
REQUIRED_CLAIMS = ["exp", "iss", "sub"]

Reason = Literal[
    "missing", "malformed", "expired", "not-yet-valid", "issuer", "party", "signature", "claims"
]


class TokenRefused(Exception):
    def __init__(self, reason: Reason) -> None:
        super().__init__(reason)
        self.reason: Reason = reason


def bearer_token(authorization: str | None) -> str:
    """The token in an ``Authorization: Bearer <token>`` header's value."""
    if not authorization:
        raise TokenRefused("missing")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token or " " in token:
        raise TokenRefused("malformed")
    return token


def verify_session_token(token: str, settings: Settings) -> str:
    """The Clerk user id a valid session token names; TokenRefused otherwise."""
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.clerk_jwt_key,
            algorithms=ALGORITHMS,
            issuer=settings.clerk_issuer,
            leeway=TOKEN_LEEWAY_SECONDS,
            options={"require": REQUIRED_CLAIMS},
        )
    except jwt.ExpiredSignatureError:
        raise TokenRefused("expired") from None
    except jwt.ImmatureSignatureError:
        raise TokenRefused("not-yet-valid") from None
    except jwt.InvalidIssuerError:
        raise TokenRefused("issuer") from None
    # A signature that does not verify, or an algorithm other than RS256.
    except jwt.InvalidSignatureError, jwt.InvalidAlgorithmError:
        raise TokenRefused("signature") from None
    except jwt.DecodeError:  # after InvalidSignatureError, which is one
        raise TokenRefused("malformed") from None
    except jwt.InvalidTokenError:
        raise TokenRefused("claims") from None

    # The authorized party is the origin of the page that asked Clerk for the
    # token, so a token lifted from another site's page is refused here.
    party = payload.get("azp")
    if not isinstance(party, str) or party not in settings.clerk_authorized_parties:
        raise TokenRefused("party")
    subject = payload["sub"]  # PyJWT has checked that it is present and a string
    if not subject:
        raise TokenRefused("claims")
    return str(subject)
