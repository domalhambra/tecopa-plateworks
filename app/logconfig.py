# app/logconfig.py
"""One place to configure logging for the app (red-team V1-11).

Before this, a failed render wrote `traceback.print_exc()` to a stdout nobody
captures, so the operator had no trace to diagnose a bad poster. Everything now logs
under the `trailprint` namespace at a configurable level, in human-readable text by
default or line-delimited JSON (TRAILPRINT_LOG_FORMAT=json) for a log collector.

Env:
  TRAILPRINT_LOG_LEVEL   default INFO
  TRAILPRINT_LOG_FORMAT  text (default) | json
"""
from __future__ import annotations
import json
import logging
import os
import sys
import time

_CONFIGURED = False


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def setup_logging() -> logging.Logger:
    """Configure the `trailprint` logger once (idempotent). Safe to call at import."""
    global _CONFIGURED
    root = logging.getLogger("trailprint")
    if _CONFIGURED:
        return root
    level = os.environ.get("TRAILPRINT_LOG_LEVEL", "INFO").upper()
    fmt = os.environ.get("TRAILPRINT_LOG_FORMAT", "text").lower()
    handler = logging.StreamHandler(sys.stderr)
    if fmt == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s", "%Y-%m-%dT%H:%M:%S"))
    root.handlers[:] = [handler]
    root.setLevel(level)
    root.propagate = False        # don't double-log through the root logger
    _CONFIGURED = True
    return root
