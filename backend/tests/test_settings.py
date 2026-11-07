import base64

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import ValidationError
from settings_for_tests import (
    ISSUER,
    MODEL_KEY_ENCRYPTION_KEY,
    ORIGIN,
    PUBLIC_PEM,
    SIGNING_KEY,
    make_settings,
    public_pem,
)

from job_board.settings import EXPECTED_FORM, DatabaseSettings, Settings, sqlalchemy_url

PLAIN = "postgresql://reader:hunter2@db.example.com:5432/jobs"
DRIVER = "postgresql+psycopg://reader:hunter2@db.example.com:5432/jobs"
CLERK_SETTINGS = ("CLERK_ISSUER", "CLERK_JWT_KEY", "CLERK_AUTHORIZED_PARTIES")
SERVICE_SETTINGS = (*CLERK_SETTINGS, "MODEL_KEY_ENCRYPTION_KEY")


@pytest.fixture
def environment(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Every setting in the environment, as the service is started."""
    monkeypatch.setenv("DATABASE_URL", PLAIN)
    monkeypatch.setenv("CLERK_ISSUER", ISSUER)
    monkeypatch.setenv("CLERK_JWT_KEY", PUBLIC_PEM)
    monkeypatch.setenv("CLERK_AUTHORIZED_PARTIES", f"{ORIGIN}, https://jobs.example.com")
    monkeypatch.setenv("MODEL_KEY_ENCRYPTION_KEY", MODEL_KEY_ENCRYPTION_KEY)
    return monkeypatch


def test_reads_every_setting_from_the_environment(environment: pytest.MonkeyPatch) -> None:
    settings = Settings(_env_file=None)
    assert settings.database_url.get_secret_value() == DRIVER
    assert settings.clerk_issuer == ISSUER
    assert settings.clerk_jwt_key.public_numbers() == SIGNING_KEY.public_key().public_numbers()
    assert settings.clerk_authorized_parties == frozenset({ORIGIN, "https://jobs.example.com"})
    assert settings.model_key_encryption_key.get_secret_value() == base64.urlsafe_b64decode(
        MODEL_KEY_ENCRYPTION_KEY
    )


@pytest.mark.parametrize("missing", SERVICE_SETTINGS)
def test_refuses_to_start_naming_a_missing_setting(
    environment: pytest.MonkeyPatch, missing: str
) -> None:
    environment.delenv(missing)
    with pytest.raises(ValidationError) as raised:
        Settings(_env_file=None)
    assert [error["loc"] for error in raised.value.errors()] == [(missing.lower(),)]
    assert missing.lower() in str(raised.value)


def test_the_migrations_need_only_the_database_url(environment: pytest.MonkeyPatch) -> None:
    for name in SERVICE_SETTINGS:
        environment.delenv(name)
    assert DatabaseSettings(_env_file=None).database_url.get_secret_value() == DRIVER


@pytest.mark.parametrize("scheme", ["postgresql", "postgres", "postgresql+psycopg", "PostgreSQL"])
def test_hands_sqlalchemy_the_psycopg_driver(scheme: str) -> None:
    assert sqlalchemy_url(f"{scheme}://reader:hunter2@db.example.com:5432/jobs") == DRIVER


@pytest.mark.parametrize(
    "url",
    [
        "mysql://reader:hunter2@db.example.com:5432/jobs",
        "postgresql+asyncpg://reader:hunter2@db.example.com:5432/jobs",
        "reader:hunter2@db.example.com:5432/jobs",
        "postgresql://reader:hunter2@db.example.com:fivefour/jobs",
    ],
)
def test_refuses_any_other_form_without_repeating_it(url: str) -> None:
    with pytest.raises(ValidationError) as raised:
        make_settings(database_url=url)
    message = str(raised.value)
    assert "DATABASE_URL" in message
    assert EXPECTED_FORM in message
    for leak in ("hunter2", "db.example.com", "reader", "fivefour", "mysql", "asyncpg"):
        assert leak not in message


def test_never_shows_the_database_url() -> None:
    settings = make_settings(database_url=PLAIN)
    for shown in (repr(settings), str(settings), settings.model_dump_json()):
        assert "hunter2" not in shown
        assert "db.example.com" not in shown


def test_the_issuer_is_kept_in_the_form_tokens_carry() -> None:
    settings = make_settings(clerk_issuer="https://Sign-In.example.com/")
    assert settings.clerk_issuer == "https://sign-in.example.com"


# Clerk and browsers leave a scheme's default port out, so one written in is dropped.
@pytest.mark.parametrize(
    ("issuer", "kept"),
    [
        ("https://sign-in.example.com:443", "https://sign-in.example.com"),
        ("https://sign-in.example.com:8443", "https://sign-in.example.com:8443"),
    ],
)
def test_the_issuer_drops_only_the_default_port(issuer: str, kept: str) -> None:
    assert make_settings(clerk_issuer=issuer).clerk_issuer == kept


@pytest.mark.parametrize(
    "issuer",
    [
        "http://sign-in.example.com",
        "sign-in.example.com",
        "https://sign-in.example.com/tenant",
        "https://sign-in.example.com?tenant=1",
        "https://sign-in.example.com:port",
        "https://",
        "",
    ],
)
def test_refuses_an_issuer_that_is_not_an_https_origin(issuer: str) -> None:
    with pytest.raises(ValidationError) as raised:
        make_settings(clerk_issuer=issuer)
    assert "CLERK_ISSUER must be" in str(raised.value)


def other_kinds_of_key() -> list[str]:
    elliptic = ec.generate_private_key(ec.SECP256R1())
    return [
        public_pem(elliptic.public_key()),  # parses, but cannot verify RS256
        PUBLIC_PEM.replace("PUBLIC KEY", "CERTIFICATE"),
        PUBLIC_PEM[: len(PUBLIC_PEM) // 2],
        "not a key",
    ]


@pytest.mark.parametrize("key", other_kinds_of_key())
def test_refuses_a_key_that_is_not_an_rsa_public_key_without_repeating_it(key: str) -> None:
    with pytest.raises(ValidationError) as raised:
        make_settings(clerk_jwt_key=key)
    message = str(raised.value)
    assert "CLERK_JWT_KEY must be" in message
    assert "not a key" not in message
    assert "MII" not in message  # every PEM body starts with these bytes


def test_refuses_a_private_key() -> None:
    private_pem = SIGNING_KEY.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    with pytest.raises(ValidationError) as raised:
        make_settings(clerk_jwt_key=private_pem)
    assert "CLERK_JWT_KEY must be" in str(raised.value)
    assert "MII" not in str(raised.value)


def test_reads_the_permitted_origins_in_the_form_browsers_send() -> None:
    settings = make_settings(
        clerk_authorized_parties=" http://localhost:5173 ,HTTPS://Jobs.example.com/"
    )
    assert settings.clerk_authorized_parties == frozenset(
        {"http://localhost:5173", "https://jobs.example.com"}
    )


@pytest.mark.parametrize(
    ("party", "kept"),
    [
        ("http://localhost:80", "http://localhost"),
        ("https://jobs.example.com:443", "https://jobs.example.com"),
        ("http://localhost:443", "http://localhost:443"),
        ("https://jobs.example.com:80", "https://jobs.example.com:80"),
        ("http://localhost:5173", "http://localhost:5173"),
    ],
)
def test_a_permitted_origin_drops_only_its_scheme_default_port(party: str, kept: str) -> None:
    assert make_settings(clerk_authorized_parties=party).clerk_authorized_parties == {kept}


@pytest.mark.parametrize(
    "parties",
    [
        "",
        " , ",
        "localhost:5173",
        "http://localhost:5173/app",
        "ftp://files.example.com",
        "http://localhost:port",
        "http://localhost:5173,jobs.example.com",
    ],
)
def test_refuses_permitted_origins_that_are_not_origins(parties: str) -> None:
    with pytest.raises(ValidationError) as raised:
        make_settings(clerk_authorized_parties=parties)
    assert "CLERK_AUTHORIZED_PARTIES must be" in str(raised.value)


def encoded(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode()


@pytest.mark.parametrize(
    "value",
    [
        "",
        encoded(b"k" * 31),  # AES-256 takes exactly 32 bytes
        encoded(b"k" * 33),
        "not base64 at all!",
        encoded(b"k" * 32).rstrip("="),  # a pasted key that lost its padding
    ],
)
def test_refuses_an_encryption_key_that_is_not_32_bytes_of_base64_without_repeating_it(
    value: str,
) -> None:
    with pytest.raises(ValidationError) as raised:
        make_settings(model_key_encryption_key=value)
    message = str(raised.value)
    assert "MODEL_KEY_ENCRYPTION_KEY must be" in message
    assert "secrets.token_bytes(32)" in message  # says how to make one
    if value:
        assert value not in message


def test_takes_the_encryption_key_with_surrounding_whitespace() -> None:
    settings = make_settings(model_key_encryption_key=f"  {MODEL_KEY_ENCRYPTION_KEY}\n")
    assert settings.model_key_encryption_key.get_secret_value() == base64.urlsafe_b64decode(
        MODEL_KEY_ENCRYPTION_KEY
    )


def test_never_shows_the_encryption_key() -> None:
    settings = make_settings()
    raw = settings.model_key_encryption_key.get_secret_value()
    for shown in (repr(settings), str(settings), settings.model_dump_json()):
        assert MODEL_KEY_ENCRYPTION_KEY not in shown
        assert repr(raw) not in shown
