import base64
import binascii
import re
from dataclasses import dataclass
from typing import Annotated, Self
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_pem_public_key,
)
from pydantic import PlainSerializer, SecretBytes, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy import make_url
from sqlalchemy.exc import ArgumentError

EXPECTED_FORM = "postgresql://user:password@host:port/database"
ACCEPTED_SCHEMES = frozenset({"postgresql", "postgres", "postgresql+psycopg"})
DRIVER_SCHEME = "postgresql+psycopg"

ISSUER_REFUSAL = (
    "CLERK_ISSUER must be the https address of your Clerk instance, "
    "such as https://your-app.clerk.accounts.dev, with no path"
)
KEY_REFUSAL = (
    "CLERK_JWT_KEY must be the PEM public key from your Clerk instance's API keys page, "
    "from -----BEGIN PUBLIC KEY----- to -----END PUBLIC KEY-----"
)
PARTIES_REFUSAL = (
    "CLERK_AUTHORIZED_PARTIES must be one or more comma-separated origins of the "
    "form scheme://host[:port], such as http://localhost:5173"
)
ENCRYPTION_KEY_BYTES = 32  # AES-256
ENCRYPTION_KEY_REFUSAL = (
    "MODEL_KEY_ENCRYPTION_KEY must be 32 random bytes in URL-safe base64; make one with "
    "python3 -c 'import base64, secrets; "
    "print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())'"
)

STORAGE_SETTINGS = (
    "S3_ENDPOINT_URL",
    "S3_REGION",
    "S3_BUCKET",
    "S3_ACCESS_KEY_ID",
    "S3_SECRET_ACCESS_KEY",
)
ENDPOINT_REFUSAL = (
    "S3_ENDPOINT_URL must be the https origin of an S3-compatible store, such as "
    "https://s3.us-east-1.amazonaws.com, with no path; http only to 127.0.0.1, ::1 or localhost"
)
BUCKET_REFUSAL = (
    "S3_BUCKET must be 3 to 63 lowercase letters, digits, dots and hyphens, "
    "starting and ending with a letter or digit"
)
# Plain http would send the credentials' signatures and every resume in the
# clear; on this machine it reaches only a local store, which the tests run.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
BUCKET_NAME = re.compile(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]")  # S3's rule, which R2 shares


def sqlalchemy_url(url: str) -> str:
    """The database URL as SQLAlchemy needs it, naming the psycopg driver.

    Hosts hand out ``postgresql://`` and ``postgres://`` URLs, so both are
    accepted, as is the driver's own form. Any other scheme, or a URL that
    SQLAlchemy cannot parse, is refused with a message that names
    DATABASE_URL and the form expected but never the value, which carries a
    password.
    """
    refusal = ValueError(f"DATABASE_URL must have the form {EXPECTED_FORM}")
    scheme, separator, rest = url.partition("://")
    if not separator or scheme.lower() not in ACCEPTED_SCHEMES:
        raise refusal
    converted = f"{DRIVER_SCHEME}://{rest}"
    try:
        make_url(converted)
    except ArgumentError, ValueError:
        raise refusal from None  # SQLAlchemy's own message quotes part of the URL
    return converted


DEFAULT_PORTS = {"http": 80, "https": 443}


def origin(value: str, schemes: frozenset[str]) -> str | None:
    """``scheme://host[:port]`` in lower case, as browsers and Clerk write it.

    A scheme's default port is dropped, since neither writes it. None for
    anything else: another scheme, a path beyond a trailing slash, a query, a
    fragment, a user name or a port that is not a number. Clerk writes the
    issuer and the requesting origin in this form, and the token check compares
    them as exact strings, so a value that only looks alike would refuse every
    sign-in.
    """
    try:
        parts = urlsplit(value.strip())
        port = parts.port
    except ValueError:
        return None
    if (
        parts.scheme not in schemes
        or not parts.hostname
        or parts.path not in ("", "/")
        or parts.query
        or parts.fragment
        or parts.username is not None
    ):
        return None
    if port is None or port == DEFAULT_PORTS[parts.scheme]:
        return f"{parts.scheme}://{parts.hostname}"
    return f"{parts.scheme}://{parts.hostname}:{port}"


def pem(key: RSAPublicKey) -> str:
    return key.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()


class DatabaseSettings(BaseSettings):
    """The settings the migrations need: the database URL alone.

    Read from the environment, then from a .env file in the working directory.
    The database URL carries a password, so it is a secret: its repr, str and
    serialized forms are masked, only ``get_secret_value()`` reveals it, and a
    validation error never repeats it.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    database_url: SecretStr

    @field_validator("database_url")
    @classmethod
    def _name_the_driver(cls, value: SecretStr) -> SecretStr:
        return SecretStr(sqlalchemy_url(value.get_secret_value()))


class Settings(DatabaseSettings):
    """Everything the service needs to start; it refuses to start without any of it.

    The Clerk settings say whose session tokens to accept: the instance that
    issues them, the public key that signs them, and the origins of the pages
    allowed to send them. The model key encryption key seals each person's
    model key in the database; losing it means everyone enters their key again.
    """

    model_config = SettingsConfigDict(arbitrary_types_allowed=True)

    clerk_issuer: str
    clerk_jwt_key: Annotated[RSAPublicKey, NoDecode, PlainSerializer(pem, return_type=str)]
    clerk_authorized_parties: Annotated[frozenset[str], NoDecode]
    model_key_encryption_key: SecretBytes

    @field_validator("clerk_issuer")
    @classmethod
    def _issuer_origin(cls, value: str) -> str:
        issuer = origin(value, frozenset({"https"}))
        if issuer is None:
            raise ValueError(ISSUER_REFUSAL)
        return issuer

    @field_validator("clerk_jwt_key", mode="before")
    @classmethod
    def _parse_the_key_once(cls, value: object) -> RSAPublicKey:
        # Parsed here, at start, so a bad key stops the service instead of
        # refusing every request; the refusal never repeats the value.
        try:
            key = load_pem_public_key(str(value).strip().encode())
        except ValueError:
            raise ValueError(KEY_REFUSAL) from None
        if not isinstance(key, RSAPublicKey):  # Clerk signs with RS256, which needs RSA
            raise ValueError(KEY_REFUSAL)
        return key

    @field_validator("clerk_authorized_parties", mode="before")
    @classmethod
    def _split_the_origins(cls, value: object) -> frozenset[str]:
        items = [item for item in str(value).split(",") if item.strip()]
        origins = [origin(item, frozenset({"http", "https"})) for item in items]
        if not origins or None in origins:
            raise ValueError(PARTIES_REFUSAL)
        return frozenset(item for item in origins if item is not None)

    @field_validator("model_key_encryption_key", mode="before")
    @classmethod
    def _decode_the_encryption_key(cls, value: object) -> bytes:
        # Strict decoding, so a mistyped character is refused rather than
        # silently dropped; the refusal never repeats the value.
        try:
            key = base64.b64decode(str(value).strip(), altchars=b"-_", validate=True)
        except binascii.Error:
            raise ValueError(ENCRYPTION_KEY_REFUSAL) from None
        if len(key) != ENCRYPTION_KEY_BYTES:
            raise ValueError(ENCRYPTION_KEY_REFUSAL)
        return key

    # Resume storage: an S3-compatible bucket, optional as a whole. All five
    # settings or none; without them the service starts and the resume routes
    # answer that storage is not set up.
    s3_endpoint_url: str | None = None
    s3_region: str | None = None
    s3_bucket: str | None = None
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None

    @field_validator(
        "s3_endpoint_url",
        "s3_region",
        "s3_bucket",
        "s3_access_key_id",
        "s3_secret_access_key",
        mode="before",
    )
    @classmethod
    def _blank_is_not_given(cls, value: object) -> object:
        # An .env file may list a setting with nothing after the equals sign.
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("s3_endpoint_url")
    @classmethod
    def _endpoint_origin(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = urlsplit(value)
        if origin(value, frozenset({"http", "https"})) is None or (
            parts.scheme == "http" and parts.hostname not in LOOPBACK_HOSTS
        ):
            raise ValueError(ENDPOINT_REFUSAL)
        # Kept as given rather than as origin() writes it, which drops the
        # brackets around an IPv6 address.
        return value.rstrip("/")

    @field_validator("s3_bucket")
    @classmethod
    def _bucket_name(cls, value: str | None) -> str | None:
        if value is not None and BUCKET_NAME.fullmatch(value) is None:
            raise ValueError(BUCKET_REFUSAL)
        return value

    @model_validator(mode="after")
    def _all_storage_settings_or_none(self) -> Self:
        given = {name: getattr(self, name.lower()) is not None for name in STORAGE_SETTINGS}
        if any(given.values()) and not all(given.values()):
            missing = ", ".join(name for name, present in given.items() if not present)
            raise ValueError(
                f"Resume storage needs all five S3 settings or none of them; missing {missing}"
            )
        return self

    def resume_storage(self) -> StorageSettings | None:
        """The store's settings, or None when resume storage is not set up."""
        if (
            self.s3_endpoint_url is None
            or self.s3_region is None
            or self.s3_bucket is None
            or self.s3_access_key_id is None
            or self.s3_secret_access_key is None
        ):
            return None
        return StorageSettings(
            endpoint_url=self.s3_endpoint_url,
            region=self.s3_region,
            bucket=self.s3_bucket,
            access_key_id=self.s3_access_key_id,
            secret_access_key=self.s3_secret_access_key,
        )


@dataclass(frozen=True)
class StorageSettings:
    """Where resumes are kept: one bucket in an S3-compatible store."""

    endpoint_url: str
    region: str
    bucket: str
    access_key_id: SecretStr
    secret_access_key: SecretStr
