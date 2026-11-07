from itertools import combinations

import pytest
from botocore.exceptions import InvalidRegionError
from botocore.utils import validate_region_name
from pydantic import ValidationError
from settings_for_tests import (
    ISSUER,
    MODEL_KEY_ENCRYPTION_KEY,
    ORIGIN,
    PUBLIC_PEM,
    UNUSED_DATABASE_URL,
    make_settings,
)

from job_board.settings import BUCKET_REFUSAL, ENDPOINT_REFUSAL, REGION_REFUSAL, Settings

STORAGE = {
    "s3_endpoint_url": "https://account.r2.example.com",
    "s3_region": "auto",
    "s3_bucket": "resumes",
    "s3_access_key_id": "access-key-id-0123",
    "s3_secret_access_key": "secret-access-key-4567",
}
SETTING_NAMES = {name: name.upper() for name in STORAGE}


def partial_sets() -> list[tuple[str, ...]]:
    """Every set of the five settings with at least one given and one missing."""
    return [given for size in range(1, 5) for given in combinations(STORAGE, size)]


def test_all_five_settings_set_up_resume_storage() -> None:
    storage = make_settings(**STORAGE).resume_storage()

    assert storage is not None
    assert storage.endpoint_url == "https://account.r2.example.com"
    assert storage.region == "auto"
    assert storage.bucket == "resumes"
    assert storage.access_key_id.get_secret_value() == STORAGE["s3_access_key_id"]
    assert storage.secret_access_key.get_secret_value() == STORAGE["s3_secret_access_key"]


def test_none_of_them_leaves_resume_storage_not_set_up() -> None:
    assert make_settings().resume_storage() is None


def test_blank_settings_count_as_not_given() -> None:
    blank = {name: "  " for name in STORAGE}
    assert make_settings(**blank).resume_storage() is None


@pytest.mark.parametrize("given", partial_sets())
def test_a_partial_set_refuses_to_start_naming_what_is_missing(given: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError) as raised:
        make_settings(**{name: STORAGE[name] for name in given})

    missing = [SETTING_NAMES[name] for name in STORAGE if name not in given]
    message = str(raised.value)
    assert f"missing {', '.join(missing)}" in message
    for name in given:
        assert STORAGE[name] not in message


@pytest.mark.parametrize(
    ("endpoint", "kept"),
    [
        ("https://account.r2.example.com/", "https://account.r2.example.com"),
        ("  https://s3.us-east-1.example.com:8443  ", "https://s3.us-east-1.example.com:8443"),
        ("http://127.0.0.1:9000", "http://127.0.0.1:9000"),
        ("http://localhost:9000/", "http://localhost:9000"),
        ("http://[::1]:9000", "http://[::1]:9000"),
    ],
)
def test_takes_an_https_origin_or_http_to_this_machine(endpoint: str, kept: str) -> None:
    storage = make_settings(**{**STORAGE, "s3_endpoint_url": endpoint}).resume_storage()
    assert storage is not None
    assert storage.endpoint_url == kept


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://account.r2.example.com",
        "http://10.0.0.5:9000",
        "https://account.r2.example.com/resumes",
        "https://account.r2.example.com?bucket=resumes",
        "https://keyholder@account.r2.example.com",
        "ftp://account.r2.example.com",
        "account.r2.example.com",
    ],
)
def test_refuses_an_endpoint_that_is_not_an_origin_without_repeating_it(endpoint: str) -> None:
    with pytest.raises(ValidationError) as raised:
        make_settings(**{**STORAGE, "s3_endpoint_url": endpoint})
    message = str(raised.value)
    assert ENDPOINT_REFUSAL in message
    assert "account.r2" not in message
    assert "10.0.0.5" not in message


@pytest.mark.parametrize("bucket", ["re-sumes", "a.b", "0" * 63])
def test_takes_a_bucket_name_s3_accepts(bucket: str) -> None:
    storage = make_settings(**{**STORAGE, "s3_bucket": bucket}).resume_storage()
    assert storage is not None
    assert storage.bucket == bucket


@pytest.mark.parametrize(
    "bucket",
    ["rz", "r" * 64, "Resumes", "resu_mes", "-resumes", "resumes.", "resu mes"],
)
def test_refuses_a_bucket_name_s3_refuses_without_repeating_it(bucket: str) -> None:
    with pytest.raises(ValidationError) as raised:
        make_settings(**{**STORAGE, "s3_bucket": bucket})
    message = str(raised.value)
    assert BUCKET_REFUSAL in message
    assert bucket not in message.replace(BUCKET_REFUSAL, "")


REGIONS_TAKEN = ["auto", "us-east-1", "eu-central-2", "WNAM", "r" * 63, "1a"]
REGIONS_REFUSED = ["us east 1", "-us-east-1", "us-east-1-", "12345", "r" * 64, "us_east_1", "a/b"]


@pytest.mark.parametrize("region", REGIONS_TAKEN)
def test_takes_a_region_botocore_takes(region: str) -> None:
    validate_region_name(region)  # the rule the settings copy, so a drift shows here
    storage = make_settings(**{**STORAGE, "s3_region": region}).resume_storage()
    assert storage is not None
    assert storage.region == region


@pytest.mark.parametrize("region", REGIONS_REFUSED)
def test_refuses_a_region_botocore_refuses_without_repeating_it(region: str) -> None:
    with pytest.raises(InvalidRegionError):
        validate_region_name(region)
    with pytest.raises(ValidationError) as raised:
        make_settings(**{**STORAGE, "s3_region": region})
    message = str(raised.value)
    assert REGION_REFUSAL in message
    assert region not in message.replace(REGION_REFUSAL, "")


def test_never_shows_the_credentials() -> None:
    settings = make_settings(**STORAGE)
    storage = settings.resume_storage()
    for shown in (repr(settings), str(settings), repr(storage), str(storage)):
        assert STORAGE["s3_access_key_id"] not in shown
        assert STORAGE["s3_secret_access_key"] not in shown


def test_storage_settings_in_the_shell_never_reach_the_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in STORAGE.items():
        monkeypatch.setenv(SETTING_NAMES[name], value)
    assert make_settings().resume_storage() is None


def test_the_service_reads_the_storage_settings_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", UNUSED_DATABASE_URL)
    monkeypatch.setenv("CLERK_ISSUER", ISSUER)
    monkeypatch.setenv("CLERK_JWT_KEY", PUBLIC_PEM)
    monkeypatch.setenv("CLERK_AUTHORIZED_PARTIES", ORIGIN)
    monkeypatch.setenv("MODEL_KEY_ENCRYPTION_KEY", MODEL_KEY_ENCRYPTION_KEY)
    for name, value in STORAGE.items():
        monkeypatch.setenv(SETTING_NAMES[name], value)

    storage = Settings(_env_file=None).resume_storage()

    assert storage is not None
    assert storage.bucket == STORAGE["s3_bucket"]
    assert storage.secret_access_key.get_secret_value() == STORAGE["s3_secret_access_key"]
