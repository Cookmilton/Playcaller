"""
Local development: inspect whether ``FOOTBALL_WAREHOUSE_DATABASE_URL`` is visible to the process.

Does not print or write to Streamlit — callers decide how to surface results.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse, urlunparse

from football_history_warehouse.config.database import (
    normalize_warehouse_database_url,
    resolve_warehouse_database_url,
)

_ENV = "FOOTBALL_WAREHOUSE_DATABASE_URL"


def mask_database_url(url: str) -> str:
    """Mask passwords in URLs; leave typical SQLite URLs unchanged."""
    u = (url or "").strip()
    if not u:
        return ""
    parsed = urlparse(u)
    sch = (parsed.scheme or "").lower()
    if "sqlite" in sch:
        return u
    if parsed.password is None and parsed.username is None:
        return u
    username = parsed.username or ""
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    userpart = f"{username}:***" if parsed.password else username
    if not host:
        return u
    netloc = f"{userpart}@{host}{port}"
    return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))


def _scheme_kind(url: str) -> Optional[str]:
    p = urlparse(url.strip())
    if not p.scheme:
        return None
    base = p.scheme.split("+")[0].lower()
    if "sqlite" in base:
        return "sqlite"
    if base in ("postgres", "postgresql"):
        return "postgresql"
    return base or None


def check_warehouse_env(*, repo_root: Optional[Path] = None) -> Dict[str, Any]:
    """Return a dict describing warehouse env var state (masked; safe to log at INFO).

    Returns:
        {
            "present": bool,
            "source": "env" | "dotenv" | "missing",
            "masked_value": str | None,
            "scheme": str | None,
            "sqlite_resolved_path": str | None,  # absolute file path for SQLite; else None
        }

    ``source`` is ``dotenv`` when the value matches a non-empty entry in ``<repo_root>/.env``
    (file read via ``dotenv_values``, no mutation of ``os.environ``). Otherwise ``env`` if
    present (e.g. exported in the shell). ``dev_fallback`` when the explicit env var is unset
    but :func:`~football_history_warehouse.config.database.resolve_warehouse_database_url`
    supplies the dev-mode SQLite URL. ``missing`` if unset in ``os.environ`` and no fallback.
    """
    raw = str(os.environ.get(_ENV) or "").strip()
    root = repo_root
    resolved_url, used_dev_fallback = resolve_warehouse_database_url()

    if not raw:
        if used_dev_fallback and resolved_url:
            masked = mask_database_url(resolved_url)
            scheme = _scheme_kind(resolved_url)
            _, sqlite_abs = normalize_warehouse_database_url(resolved_url)
            sqlite_resolved_path = str(sqlite_abs) if sqlite_abs is not None else None
            return {
                "present": True,
                "source": "dev_fallback",
                "masked_value": masked,
                "scheme": scheme,
                "sqlite_resolved_path": sqlite_resolved_path,
            }
        return {
            "present": False,
            "source": "missing",
            "masked_value": None,
            "scheme": None,
            "sqlite_resolved_path": None,
        }

    masked = mask_database_url(raw)
    scheme = _scheme_kind(raw)
    _, sqlite_abs = normalize_warehouse_database_url(raw)
    sqlite_resolved_path = str(sqlite_abs) if sqlite_abs is not None else None

    source: str = "env"
    if root is not None:
        dotenv_path = root / ".env"
        if dotenv_path.is_file():
            try:
                from dotenv import dotenv_values

                vals = dotenv_values(dotenv_path)
                file_val = str(vals.get(_ENV) or "").strip()
                if file_val and file_val == raw:
                    source = "dotenv"
            except ImportError:
                source = "env"

    return {
        "present": True,
        "source": source,
        "masked_value": masked,
        "scheme": scheme,
        "sqlite_resolved_path": sqlite_resolved_path,
    }
