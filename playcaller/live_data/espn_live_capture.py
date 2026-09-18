"""Optional raw ESPN payload capture for live sync (Sunday debugging). Default OFF."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

logger = logging.getLogger(__name__)

CAPTURE_FLAG_NAME = "PLAYCALLER_LIVE_CAPTURE"
CAPTURE_DIR_ENV = "PLAYCALLER_LIVE_CAPTURE_DIR"

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off", ""}


def _coerce_flag(raw: Any) -> Optional[bool]:
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if s in _TRUTHY:
        return True
    if s in _FALSY:
        return False
    return None


def live_capture_enabled() -> bool:
    """Env wins; otherwise Streamlit secrets (Cloud). Default OFF."""
    env = _coerce_flag(os.environ.get(CAPTURE_FLAG_NAME))
    if env is not None:
        return env
    try:
        import streamlit as st

        secrets = getattr(st, "secrets", None)
        if secrets is None:
            return False
        if CAPTURE_FLAG_NAME in secrets:
            flag = _coerce_flag(secrets[CAPTURE_FLAG_NAME])
            return bool(flag)
        nested = secrets.get("playcaller") if hasattr(secrets, "get") else None
        if isinstance(nested, Mapping) and CAPTURE_FLAG_NAME in nested:
            return bool(_coerce_flag(nested.get(CAPTURE_FLAG_NAME)))
    except Exception:
        return False
    return False


def capture_root() -> Path:
    override = str(os.environ.get(CAPTURE_DIR_ENV) or "").strip()
    if override:
        return Path(override)
    repo = Path(__file__).resolve().parents[2]
    return repo / "data" / "captures"


def _safe_event_id(event_id: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", str(event_id or "").strip()) or "unknown"
    return s[:80]


def capture_espn_payload(event_id: str, kind: str, payload: Any) -> Optional[Path]:
    """
    Write one JSON file under ``data/captures/<event_id>/`` when the flag is on.

    Never raises: a write failure logs a warning and returns ``None``.
    """
    if not live_capture_enabled():
        return None
    if not isinstance(payload, dict):
        return None
    try:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        kind_s = re.sub(r"[^A-Za-z0-9._-]+", "_", str(kind or "payload")) or "payload"
        dest_dir = capture_root() / _safe_event_id(event_id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        path = dest_dir / f"{stamp}_{kind_s}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
    except Exception as exc:
        logger.warning("playcaller: live ESPN capture failed (%s %s): %s", event_id, kind, exc)
        return None
