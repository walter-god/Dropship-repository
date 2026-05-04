"""
Centralized logging — rotating file handler + coloured console output.
Import get_logger() from anywhere in the project.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config import LOG_LEVEL, LOG_DIR

_COLOURS = {
    "DEBUG": "\033[94m",
    "INFO": "\033[92m",
    "WARNING": "\033[93m",
    "ERROR": "\033[91m",
    "CRITICAL": "\033[95m",
    "RESET": "\033[0m",
}


class _ColourFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        colour = _COLOURS.get(record.levelname, _COLOURS["RESET"])
        reset = _COLOURS["RESET"]
        record.levelname = f"{colour}{record.levelname}{reset}"
        return super().format(record)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

    fmt = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    date_fmt = "%Y-%m-%d %H:%M:%S"

    # Console handler (coloured)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(_ColourFormatter(fmt, datefmt=date_fmt))
    logger.addHandler(ch)

    # Rotating file handler (plain text, 10 MB × 5 backups)
    log_file = LOG_DIR / "trader.log"
    fh = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
    fh.setFormatter(logging.Formatter(fmt, datefmt=date_fmt))
    logger.addHandler(fh)

    logger.propagate = False
    return logger
