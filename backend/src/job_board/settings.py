from typing import Annotated
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_pem_public_key,
)
from pydantic import PlainSerializer, SecretStr, field_validator
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


def origin(value: str, schemes: frozenset[str]) -> str | None:
    """``scheme://host[:port]`` in lower case, as browsers and Clerk write it.

    None for anything else: another scheme, a path beyond a trailing slash, a
    query, a fragment, a user name or a port that is not a number. Clerk
    compares the issuer and the requesting origin as exact strings, so a value
    that only looks alike would refuse every sign-in.
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
    return f"{parts.scheme}://{parts.hostname}" + (f":{port}" if port is not None else "")


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
    allowed to send them.
    """

    model_config = SettingsConfigDict(arbitrary_types_allowed=True)

    clerk_issuer: str
    clerk_jwt_key: Annotated[RSAPublicKey, NoDecode, PlainSerializer(pem, return_type=str)]
    clerk_authorized_parties: Annotated[frozenset[str], NoDecode]

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
