from __future__ import annotations

import os
from typing import Any, Dict

from .http_client import JsonFetchResult, fetch_json_http, ssl_insecure_fallback_permitted


def _env_flag(name: str) -> bool:
    v = str(os.environ.get(name) or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def http_insecure_ssl_enabled() -> bool:
    """
    When True, HTTPS requests skip certificate verification from the first attempt.

    Set ``PLAYCALLER_HTTP_INSECURE_SSL`` or ``PLAYCALLER_ESPN_INSECURE_SSL`` to
    ``1`` / ``true`` / ``yes`` / ``on``. Prefer leaving these unset: local runs
    retry with ``verify=False`` automatically when verification fails (unless
    production mode disables fallback — see :func:`ssl_insecure_fallback_permitted`).
    """
    return _env_flag("PLAYCALLER_HTTP_INSECURE_SSL") or _env_flag("PLAYCALLER_ESPN_INSECURE_SSL")


def fetch_json(url: str, *, timeout: float = 25.0) -> JsonFetchResult:
    """
    GET JSON with a browser-like User-Agent.

    Uses verified TLS by default; on SSL failure in non-production environments,
    retries without verification (see ``playcaller.live_data.http_client``).
    """
    return fetch_json_http(url, timeout=timeout)


__all__ = [
    "JsonFetchResult",
    "fetch_json",
    "http_insecure_ssl_enabled",
    "ssl_insecure_fallback_permitted",
]
