"""Settings for the tests, built in one place so a new setting is added once.

The signing key and the model key encryption key are generated for each test
run and never leave it: the tests sign their own session tokens with the one,
so no test needs a Clerk instance, and seal model keys with the other.
"""

import base64
import secrets

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

MODEL_KEY_ENCRYPTION_KEY = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


def make_settings(
    *,
    database_url: str = UNUSED_DATABASE_URL,
    clerk_issuer: str = ISSUER,
    clerk_jwt_key: str = PUBLIC_PEM,
    clerk_authorized_parties: str = ORIGIN,
    model_key_encryption_key: str = MODEL_KEY_ENCRYPTION_KEY,
    # Passed even when None, so a storage setting in the shell never reaches a test.
    s3_endpoint_url: str | None = None,
    s3_region: str | None = None,
    s3_bucket: str | None = None,
    s3_access_key_id: str | None = None,
    s3_secret_access_key: str | None = None,
) -> Settings:
    return Settings(
        database_url=database_url,
        clerk_issuer=clerk_issuer,
        clerk_jwt_key=clerk_jwt_key,
        clerk_authorized_parties=clerk_authorized_parties,
        model_key_encryption_key=model_key_encryption_key,
        s3_endpoint_url=s3_endpoint_url,
        s3_region=s3_region,
        s3_bucket=s3_bucket,
        s3_access_key_id=s3_access_key_id,
        s3_secret_access_key=s3_secret_access_key,
        _env_file=None,
    )
