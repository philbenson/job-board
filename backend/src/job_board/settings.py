from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import make_url
from sqlalchemy.exc import ArgumentError

EXPECTED_FORM = "postgresql://user:password@host:port/database"
ACCEPTED_SCHEMES = frozenset({"postgresql", "postgres", "postgresql+psycopg"})
DRIVER_SCHEME = "postgresql+psycopg"


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


class Settings(BaseSettings):
    """Configuration from the environment, then from a .env file in the working directory.

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
