#!/usr/bin/env python3
"""Structured JSON logging with automatic secret masking. Replaces ad-hoc print()
in the trading paths. Logs go to /dev/shm (indexed by Loki) and a persistent file.

Usage:
    from safety.logging_setup import get_logger
    log = get_logger("execution")
    log.info("order_submitted", extra={"symbol": "NVDA", "qty": 10})
"""
from __future__ import annotations
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGDIR = Path("/dev/shm")
PERSIST = ROOT / "reports" / "logs"

# Patterns that must never reach a log line.
_SECRET_PATTERNS = [
    # any NAME containing key/secret/token/password followed by = or : value
    re.compile(r"([A-Za-z0-9_]*(?:SECRET|KEY|TOKEN|PASSWORD|PASSWD)[A-Za-z0-9_]*)\s*[=:]\s*\S+", re.I),
    re.compile(r"\b(sk-[A-Za-z0-9]{8,}|whsec_[A-Za-z0-9]{8,}|pk_[A-Za-z0-9]{8,})\b"),
]


def _mask(text: str) -> str:
    for pat in _SECRET_PATTERNS:
        text = pat.sub(lambda m: (m.group(1) + "=****") if m.groups() else "****", text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for k, v in getattr(record, "__dict__", {}).items():
            if k in ("args", "msg", "levelname", "levelno", "pathname", "filename",
                     "module", "exc_info", "exc_text", "stack_info", "lineno",
                     "funcName", "created", "msecs", "relativeCreated", "thread",
                     "threadName", "processName", "process", "name", "taskName"):
                continue
            base[k] = v
        return _mask(json.dumps(base, default=str))


def get_logger(name: str, level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger(f"tradingbrain.{name}")
    if logger.handlers:
        return logger
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    fmt = JsonFormatter()
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    try:
        LOGDIR.mkdir(exist_ok=True)
        fh = logging.FileHandler(LOGDIR / f"tb-{name}.log")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
        PERSIST.mkdir(parents=True, exist_ok=True)
        pfh = logging.FileHandler(PERSIST / f"{name}.log")
        pfh.setFormatter(fmt)
        logger.addHandler(pfh)
    except Exception:
        pass
    logger.propagate = False
    return logger


if __name__ == "__main__":
    log = get_logger("demo")
    log.info("secret_masking_test", extra={"note": "APCA_API_KEY_ID=ABCD1234SECRET should be masked"})
    log.warning("order_rejected", extra={"symbol": "NVDA", "reason": "kill switch"})
