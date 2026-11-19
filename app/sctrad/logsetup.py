"""Registro en archivo (rotativo, sin datos sensibles)."""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

_SECRET_RE = re.compile(r"(?i)(token|authorization|password|secret)[=: ]+\S+")


class _Redact(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            return True
        clean = _SECRET_RE.sub(r"\1=***", msg)
        if clean != msg:
            record.msg, record.args = clean, ()
        return True


def setup_logging(data_dir: Path, name: str = "gestor") -> Path:
    logs = Path(data_dir) / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    path = logs / f"{name}.log"
    handler = RotatingFileHandler(path, maxBytes=1024 * 1024, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(_Redact())
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        root.addHandler(handler)
    return path
