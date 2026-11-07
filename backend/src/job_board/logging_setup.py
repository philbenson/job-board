"""Where the service's own log lines go.

Uvicorn configures only its own loggers, so without this the ``job_board``
loggers fall through to Python's last-resort handler, which prints warnings and
above: a refused sign-in's reason, logged at info, would reach no one.
"""

import logging
import sys

LOGGER_NAME = "job_board"
HANDLER_NAME = "job_board.stderr"
LINE_FORMAT = "%(levelname)s:     %(name)s: %(message)s"  # aligned with uvicorn's own lines


class _StandardError(logging.Handler):
    """Writes to whatever ``sys.stderr`` is when a line is written, not when built."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            sys.stderr.write(self.format(record) + "\n")
            sys.stderr.flush()
        except Exception:
            self.handleError(record)


def configure_logging() -> None:
    """Send the service's info lines and above to standard error, adding the handler once."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    if any(handler.get_name() == HANDLER_NAME for handler in logger.handlers):
        return
    handler = _StandardError()
    handler.set_name(HANDLER_NAME)
    handler.setFormatter(logging.Formatter(LINE_FORMAT))
    logger.addHandler(handler)
