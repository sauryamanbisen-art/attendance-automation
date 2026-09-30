"""Structured application logging with automated sensitive data redaction."""

import logging
import sys

from app.security.redaction import redact_string


class RedactingFormatter(logging.Formatter):
    """Log formatter that automatically masks sensitive patterns in log messages."""

    def format(self, record: logging.LogRecord) -> str:
        original = super().format(record)
        return redact_string(original)


def setup_logging(log_level: str = "INFO") -> None:
    """Configure root logger with the redacting formatter."""
    level = getattr(logging, log_level.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Avoid duplicate handlers if setup_logging is called multiple times
    if not root_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)
        formatter = RedactingFormatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
    else:
        for handler in root_logger.handlers:
            handler.setLevel(level)
            formatter = RedactingFormatter(
                fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            handler.setFormatter(formatter)


def get_logger(name: str) -> logging.Logger:
    """Get a named logger with redacting support."""
    return logging.getLogger(name)
