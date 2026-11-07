"""Settings for the tests, built in one place so a new setting is added once.

The signing key is generated for each test run and never leaves it: the tests
sign their own session tokens with it, so no test needs a Clerk instance.
"""

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.types import PublicKeyTypes

from job_board.settings import Settings

ISSUER = "https://sign-in.example.com"
ORIGIN = "http://localhost:5173"
UNUSED_DATABASE_URL = "postgresql://reader:hunter2@db.example.com:5432/jobs"  # never connected to

SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def public_pem(key: PublicKeyTypes) -> str:
    return key.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()


PUBLIC_PEM = public_pem(SIGNING_KEY.public_key())


def make_settings(
    *,
    database_url: str = UNUSED_DATABASE_URL,
    clerk_issuer: str = ISSUER,
    clerk_jwt_key: str = PUBLIC_PEM,
    clerk_authorized_parties: str = ORIGIN,
) -> Settings:
    return Settings(
        database_url=database_url,
        clerk_issuer=clerk_issuer,
        clerk_jwt_key=clerk_jwt_key,
        clerk_authorized_parties=clerk_authorized_parties,
        _env_file=None,
    )
