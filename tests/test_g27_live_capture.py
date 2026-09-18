"""G2.7 live ESPN capture behind PLAYCALLER_LIVE_CAPTURE (default off)."""

from __future__ import annotations

from pathlib import Path

from playcaller.live_data.espn_live_capture import capture_espn_payload, live_capture_enabled


def test_g27_flag_off_writes_nothing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PLAYCALLER_LIVE_CAPTURE", "0")
    monkeypatch.setenv("PLAYCALLER_LIVE_CAPTURE_DIR", str(tmp_path))
    assert live_capture_enabled() is False
    out = capture_espn_payload("401872931", "summary", {"ok": True})
    assert out is None
    assert list(tmp_path.rglob("*.json")) == []


def test_g27_flag_on_writes_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PLAYCALLER_LIVE_CAPTURE", "1")
    monkeypatch.setenv("PLAYCALLER_LIVE_CAPTURE_DIR", str(tmp_path))
    assert live_capture_enabled() is True
    p1 = capture_espn_payload("401872931", "summary", {"kind": "summary"})
    p2 = capture_espn_payload("401872931", "scoreboard", {"kind": "scoreboard"})
    assert p1 is not None and p1.is_file()
    assert p2 is not None and p2.is_file()
    assert p1.parent == tmp_path / "401872931"
    assert "_summary.json" in p1.name
    assert "_scoreboard.json" in p2.name


def test_g27_unwritable_dir_does_not_raise(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PLAYCALLER_LIVE_CAPTURE", "1")
    blocker = tmp_path / "blocked"
    blocker.write_text("not-a-dir", encoding="utf-8")
    monkeypatch.setenv("PLAYCALLER_LIVE_CAPTURE_DIR", str(blocker / "captures"))
    capture_espn_payload("401872931", "summary", {"ok": True})
    assert list(tmp_path.rglob("*.json")) == []
