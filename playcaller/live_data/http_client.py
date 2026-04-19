"""
Shared HTTPS GET for ESPN and other live data.

Uses ``requests`` (already required by Streamlit). Default ``verify=True``; on SSL
failure, retries with ``verify=False`` only when :func:`ssl_insecure_fallback_permitted`
returns True (non-production / not explicitly disabled).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

logger = logging.getLogger(__name__)

_DEFAULT_HEADERS: Mapping[str, str] = {
    "User-Agent": "playcaller/1.0 (+https://github.com)",
}


def _env_truthy(name: str) -> bool:
    v = str(os.environ.get(name) or "").strip().lower()
    return v in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class JsonFetchResult:
    """JSON object response from :func:`fetch_json_http`."""

    data: dict[str, Any]
    used_insecure_ssl_fallback: bool = False


def ssl_insecure_fallback_permitted() -> bool:
    """
    Whether an automatic ``verify=False`` retry is allowed after TLS verification fails.

    Secure production: set ``PLAYCALLER_ENV=production`` (or ``prod``) or
    ``PLAYCALLER_PRODUCTION=1`` to disable the fallback. Optionally set
    ``PLAYCALLER_DISABLE_INSECURE_SSL_FALLBACK=1`` in any environment.
    """
    if _env_truthy("PLAYCALLER_PRODUCTION"):
        return False
    env = str(os.environ.get("PLAYCALLER_ENV") or "").strip().lower()
    if env in ("production", "prod"):
        return False
    if _env_truthy("PLAYCALLER_DISABLE_INSECURE_SSL_FALLBACK"):
        return False
    return True


def _force_insecure_from_env() -> bool:
    """Legacy / explicit: always skip verification when these env vars are set."""
    return _env_truthy("PLAYCALLER_HTTP_INSECURE_SSL") or _env_truthy("PLAYCALLER_ESPN_INSECURE_SSL")


def _is_ssl_error(exc: BaseException) -> bool:
    try:
        import requests
    except ImportError:
        return False
    if isinstance(exc, requests.exceptions.SSLError):
        return True
    # Chained cert errors (urllib3 / ssl)
    cur: Optional[BaseException] = exc
    seen = 0
    while cur is not None and seen < 8:
        seen += 1
        if cur.__class__.__name__ in ("SSLCertVerificationError", "SSLError"):
            return True
        msg = str(cur).lower()
        if "certificate_verify_failed" in msg or ("ssl" in msg and "cert" in msg):
            return True
        cur = cur.__cause__ or cur.__context__
    return False


def fetch_json_http(
    url: str,
    *,
    timeout: float = 25.0,
    session: Optional[Any] = None,
    get: Optional[Callable[..., Any]] = None,
) -> JsonFetchResult:
    """
    GET JSON with verification on by default.

    ``session`` / ``get`` are injectable for tests (defaults to ``requests.get``).
    """
    import requests

    getter = get if get is not None else (session.get if session is not None else requests.get)

    def _request(verify: bool) -> Any:
        return getter(
            url,
            headers=dict(_DEFAULT_HEADERS),
            timeout=timeout,
            verify=verify,
        )

    if _force_insecure_from_env():
        try:
            import urllib3

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            pass
        resp = _request(False)
        resp.raise_for_status()
        return JsonFetchResult(
            data=_parse_json_object(url, resp.text),
            used_insecure_ssl_fallback=True,
        )

    try:
        resp = _request(True)
        resp.raise_for_status()
    except Exception as e:
        if _is_ssl_error(e) and ssl_insecure_fallback_permitted():
            logger.warning(
                "HTTPS certificate verification failed for %s; retrying with verify=False (local dev fallback).",
                url,
            )
            try:
                import urllib3

                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            except Exception:
                pass
            try:
                resp = _request(False)
                resp.raise_for_status()
            except Exception as e2:
                raise RuntimeError(
                    "SSL certificate verification failed and the insecure retry also failed: "
                    f"{e2}"
                ) from e2
            return JsonFetchResult(
                data=_parse_json_object(url, resp.text),
                used_insecure_ssl_fallback=True,
            )
        if _is_ssl_error(e) and not ssl_insecure_fallback_permitted():
            raise RuntimeError(
                "SSL certificate verification failed (HTTPS verify=True). "
                "This deployment treats insecure fallback as disabled "
                "(e.g. PLAYCALLER_ENV=production). Fix trust store / certificates on the host."
            ) from e
        raise

    return JsonFetchResult(data=_parse_json_object(url, resp.text), used_insecure_ssl_fallback=False)


def _parse_json_object(url: str, text: str) -> dict[str, Any]:
    try:
        out = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid JSON from {url}: {e}") from e
    if not isinstance(out, dict):
        raise RuntimeError("Expected JSON object at root")
    return out
