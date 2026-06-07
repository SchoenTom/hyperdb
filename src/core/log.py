"""
HyperDataBank — Structured Logging
───────────────────────────────────
Consistent, timestamped logging for all pipeline steps.
Every action is logged so the pipeline is fully traceable.
"""

import logging
import sys
from pathlib import Path

from src.core.config import get_reports_dir

_configured = False


def get_logger(name: str = "hyperdb") -> logging.Logger:
    """Return a configured logger.

    Logs to both stdout (INFO) and a file (DEBUG) in the reports directory.
    """
    global _configured
    logger = logging.getLogger(name)

    if not _configured:
        logger.setLevel(logging.DEBUG)

        fmt = logging.Formatter(
            "%(asctime)s  %(levelname)-8s  %(name)-20s  %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # Console handler — INFO and above
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(logging.INFO)
        console.setFormatter(fmt)
        logger.addHandler(console)

        # File handler — DEBUG and above (full trace)
        log_file = get_reports_dir() / "hyperdb.log"
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)

        _configured = True

    return logger
