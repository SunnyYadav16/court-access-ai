"""
courtaccess/core/logger.py

Structured logger factory → GCP Cloud Logging handler in production.
Named logger.py (not logging.py) to avoid shadowing the stdlib.

Usage:
    from courtaccess.core.logger import get_logger
    logger = get_logger(__name__)
"""

import logging
import sys


def get_logger(name: str) -> logging.Logger:
    """
    Return a named logger with a consistent format.
    In production containers, the log output is picked up by the
    GCP Cloud Logging agent (JSON logs on stdout → Cloud Logging).
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%SZ",
            )
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False

    return logger
