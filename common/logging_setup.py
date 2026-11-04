"""Logging configuration shared by the CLI tools, tests and the Streamlit app."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from common.paths import LOG_DIR, ensure_dirs

LOG_FILE = LOG_DIR / "routeresq.log"
_configured = False


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure the ``routeresq`` logger once (file + stderr)."""
    global _configured
    logger = logging.getLogger("routeresq")
    if _configured:
        return logger
    ensure_dirs()
    logger.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    fh = RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    sh.setLevel(logging.WARNING)
    logger.addHandler(sh)
    _configured = True
    return logger


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(f"routeresq.{name}")
