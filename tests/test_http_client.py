"""Tests for ``playcaller.live_data.http_client`` (injectable GET, SSL fallback)."""

from __future__ import annotations

import pytest

from playcaller.live_data.http_client import JsonFetchResult, fetch_json_http, ssl_insecure_fallback_permitted


class _FakeResp:
    __slots__ = ("text",)

    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return


def test_fetch_json_http_ssl_error_retries_with_insecure_when_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PLAYCALLER_ENV", raising=False)
    monkeypatch.delenv("PLAYCALLER_PRODUCTION", raising=False)
    monkeypatch.delenv("PLAYCALLER_DISABLE_INSECURE_SSL_FALLBACK", raising=False)
    monkeypatch.delenv("PLAYCALLER_HTTP_INSECURE_SSL", raising=False)
    monkeypatch.delenv("PLAYCALLER_ESPN_INSECURE_SSL", raising=False)
    assert ssl_insecure_fallback_permitted() is True

    import requests

    verifies: list[bool] = []

    def fake_get(url: str, **kwargs: object) -> _FakeResp:
        verifies.append(bool(kwargs.get("verify")))
        if kwargs.get("verify") is True:
            raise requests.exceptions.SSLError("CERTIFICATE_VERIFY_FAILED")
        return _FakeResp('{"a": 1}')

    out = fetch_json_http("https://example.invalid/espn.json", get=fake_get, timeout=1.0)
    assert verifies == [True, False]
    assert out == JsonFetchResult(data={"a": 1}, used_insecure_ssl_fallback=True)


def test_fetch_json_http_ssl_error_no_fallback_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLAYCALLER_ENV", "production")
    assert ssl_insecure_fallback_permitted() is False

    import requests

    def fake_get(url: str, **kwargs: object) -> _FakeResp:
        raise requests.exceptions.SSLError("CERTIFICATE_VERIFY_FAILED")

    with pytest.raises(RuntimeError, match="PLAYCALLER_ENV=production"):
        fetch_json_http("https://example.invalid/x", get=fake_get, timeout=1.0)
