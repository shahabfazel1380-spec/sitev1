from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from .config import LOG_FILE

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s | %(message)s"


def setup_logging() -> None:
    """Configure application logging with a 5-minute rotating file handler."""

    root = logging.getLogger()
    # Avoid duplicating handlers when called multiple times
    for handler in root.handlers:
        if isinstance(handler, TimedRotatingFileHandler):
            return

    root.setLevel(logging.INFO)
    formatter = logging.Formatter(LOG_FORMAT)

    log_path = Path(LOG_FILE)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    file_handler = TimedRotatingFileHandler(
        log_path,
        when="M",
        interval=5,
        backupCount=12,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)
