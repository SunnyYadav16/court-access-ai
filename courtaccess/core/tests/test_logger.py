"""
Unit tests for courtaccess/core/logger.py

Function under test:
  get_logger — returns a named, configured logging.Logger

Design notes:
  - No mocking required; get_logger() is a pure factory with no external deps.
  - Each test uses a unique logger name to prevent cross-test handler
    accumulation (Python's logging registry is global and persists within a
    process). Unique names mean each call sees an unconfigured logger.
  - The idempotency test explicitly calls get_logger() twice on the same name
    and asserts handler count stays at 1.
"""

import logging
import sys

from courtaccess.core.logger import get_logger

# ─────────────────────────────────────────────────────────────────────────────
# get_logger — return type and naming
# ─────────────────────────────────────────────────────────────────────────────

class TestGetLoggerReturnType:

    def test_returns_logging_logger_instance(self):
        logger = get_logger("test.return_type.a")
        assert isinstance(logger, logging.Logger)

    def test_logger_name_matches_argument(self):
        logger = get_logger("test.name.my.module")
        assert logger.name == "test.name.my.module"

    def test_different_names_return_different_loggers(self):
        a = get_logger("test.name.alpha")
        b = get_logger("test.name.beta")
        assert a is not b
        assert a.name != b.name

    def test_same_name_returns_same_logger_object(self):
        # Python's logging registry is a global singleton keyed by name
        a = get_logger("test.name.same")
        b = get_logger("test.name.same")
        assert a is b


# ─────────────────────────────────────────────────────────────────────────────
# get_logger — handler configuration
# ─────────────────────────────────────────────────────────────────────────────

class TestGetLoggerHandlers:

    def test_handler_is_added_on_first_call(self):
        logger = get_logger("test.handlers.first")
        assert len(logger.handlers) >= 1

    def test_handler_is_stream_handler(self):
        logger = get_logger("test.handlers.stream")
        assert any(isinstance(h, logging.StreamHandler) for h in logger.handlers)

    def test_handler_streams_to_stdout(self):
        logger = get_logger("test.handlers.stdout")
        stream_handlers = [h for h in logger.handlers if isinstance(h, logging.StreamHandler)]
        assert any(h.stream is sys.stdout for h in stream_handlers)

    def test_idempotent_no_duplicate_handlers(self):
        # Calling get_logger() twice on the same name must not add a second handler
        name = "test.handlers.idempotent"
        get_logger(name)
        get_logger(name)
        logger = logging.getLogger(name)
        # Each call checks `if not logger.handlers` — second call is a no-op
        assert len(logger.handlers) == 1


# ─────────────────────────────────────────────────────────────────────────────
# get_logger — log level and propagation
# ─────────────────────────────────────────────────────────────────────────────

class TestGetLoggerLevel:

    def test_log_level_is_info(self):
        logger = get_logger("test.level.info")
        assert logger.level == logging.INFO

    def test_propagation_is_disabled(self):
        # GCP Cloud Logging handler must capture all records; propagation to
        # root logger would cause duplicate lines in production
        logger = get_logger("test.level.propagate")
        assert logger.propagate is False


# ─────────────────────────────────────────────────────────────────────────────
# get_logger — formatter
# ─────────────────────────────────────────────────────────────────────────────

class TestGetLoggerFormatter:

    def test_handler_has_formatter(self):
        logger = get_logger("test.fmt.has_formatter")
        stream_handlers = [h for h in logger.handlers if isinstance(h, logging.StreamHandler)]
        assert all(h.formatter is not None for h in stream_handlers)

    def test_formatter_includes_levelname(self):
        logger = get_logger("test.fmt.levelname")
        h = next(h for h in logger.handlers if isinstance(h, logging.StreamHandler))
        assert "%(levelname)s" in h.formatter._fmt

    def test_formatter_includes_logger_name(self):
        logger = get_logger("test.fmt.name_field")
        h = next(h for h in logger.handlers if isinstance(h, logging.StreamHandler))
        assert "%(name)s" in h.formatter._fmt

    def test_formatter_includes_message(self):
        logger = get_logger("test.fmt.message")
        h = next(h for h in logger.handlers if isinstance(h, logging.StreamHandler))
        assert "%(message)s" in h.formatter._fmt

    def test_formatter_datefmt_is_iso8601(self):
        # Timestamp format must be parseable by Cloud Logging
        logger = get_logger("test.fmt.datefmt")
        h = next(h for h in logger.handlers if isinstance(h, logging.StreamHandler))
        assert h.formatter.datefmt == "%Y-%m-%dT%H:%M:%SZ"
