"""The web service refuses to start while a setting could carry a person's text out."""

import logging

import pytest
from settings_for_tests import make_settings

from job_board.app import create_app
from job_board.environment_refusal import RefusedEnvironment
from job_board.logging_setup import LOGGER_NAME

# Each setting with a value the refusal reads as on, spelled so that a message
# repeating the value would show it.
REFUSED = [
    ("LANGSMITH_TRACING_V2", "TRUE"),
    ("LANGCHAIN_TRACING_V2", "Yes"),
    ("LANGSMITH_TRACING", " True "),
    ("LANGCHAIN_TRACING", "YES"),
    ("ANTHROPIC_CUSTOM_HEADERS", "x-sentinel: someone-elses-credential"),
    ("ANTHROPIC_LOG", "debug-sentinel"),
]


@pytest.mark.parametrize(("name", "value"), REFUSED)
def test_the_service_refuses_to_start_naming_the_setting_and_not_its_value(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    # Building the service would set its own loggers to info, dropping their debug lines unread.
    monkeypatch.setattr("job_board.app.configure_logging", lambda: None)
    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
    with pytest.raises(RefusedEnvironment) as refused:
        create_app(make_settings())
    assert name in str(refused.value)
    assert [line for line in caplog.messages if name in line] != []
    assert value.strip() not in caplog.text
    assert value.strip() not in str(refused.value)


def test_the_service_names_every_setting_it_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in REFUSED:
        monkeypatch.setenv(name, value)
    with pytest.raises(RefusedEnvironment) as refused:
        create_app(make_settings())
    # Tracing is named once, by the variable LangSmith reads first.
    assert refused.value.names == [
        "LANGSMITH_TRACING_V2",
        "ANTHROPIC_CUSTOM_HEADERS",
        "ANTHROPIC_LOG",
    ]


def test_the_service_starts_under_settings_that_turn_nothing_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("ANTHROPIC_LOG", "")
    create_app(make_settings())
