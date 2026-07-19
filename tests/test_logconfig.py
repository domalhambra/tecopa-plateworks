# tests/test_logconfig.py
# Structured logging (red-team V1-11): the JSON formatter must emit valid, parseable
# records, and setup_logging must be idempotent (safe to call at every import).
import json
import logging

from app import logconfig


def test_json_formatter_emits_valid_json():
    rec = logging.LogRecord("tecopa.test", logging.INFO, __file__, 1,
                            "event=render.final region=lassen_ca ms=42", None, None)
    out = logconfig._JsonFormatter().format(rec)
    d = json.loads(out)
    assert d["level"] == "INFO"
    assert d["logger"] == "tecopa.test"
    assert d["msg"] == "event=render.final region=lassen_ca ms=42"
    assert "ts" in d


def test_json_formatter_includes_exception():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        rec = logging.LogRecord("tecopa.test", logging.ERROR, __file__, 1,
                                "event=job.error", None, sys.exc_info())
    d = json.loads(logconfig._JsonFormatter().format(rec))
    assert "exc" in d and "ValueError: boom" in d["exc"]


def test_setup_logging_is_idempotent():
    a = logconfig.setup_logging()
    before = len(a.handlers)
    b = logconfig.setup_logging()
    assert a is b and a.name == "tecopa"
    # a repeat call must ADD nothing (the property setup_logging guarantees). Assert no
    # growth rather than an absolute count of 1: under pytest, the log-capture plugin
    # may also attach a handler to this non-propagating logger during a run, and that
    # is orthogonal to setup_logging's own idempotency.
    assert len(b.handlers) == before
