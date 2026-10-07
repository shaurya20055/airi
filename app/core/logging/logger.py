from __future__ import annotations

import logging
import sys
from typing import Any
import structlog
from structlog.typing import EventDict

def _filter_secrets(logger: logging.Logger, name: str, event_dict: EventDict) -> EventDict:
    """Filter out sensitive information from logs."""
    secrets = ['api_key', 'password', 'secret', 'token']
    for key, value in event_dict.items():
        if any(secret in key.lower() for secret in secrets):
            event_dict[key] = "***REDACTED***"
    return event_dict

def setup_logging(log_level: str = "INFO", pretty_console: bool = True) -> None:
    """Set up structured logging for the application."""
    level = getattr(logging, log_level.upper(), logging.INFO)
    
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        _filter_secrets,
    ]

    if pretty_console:
        processors.append(structlog.dev.ConsoleRenderer())
    else:
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

def get_logger(name: str) -> structlog.BoundLogger:
    """Get a structured logger for the given module name."""
    return structlog.get_logger(name)
