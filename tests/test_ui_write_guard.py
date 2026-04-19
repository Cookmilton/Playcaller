"""Tests for per-run ``ui_*`` widget key write guard."""

import pytest

from playcaller.streamlit_state.ui_write_guard import (
    assign_session_state,
    register_ui_widget_key_bound,
    reset_ui_write_guard,
)


def test_assign_before_bind_always_ok() -> None:
    reset_ui_write_guard()
    ss: dict = {}
    assign_session_state(ss, "ui_down", 2, context="test")
    assert ss["ui_down"] == 2


def test_strict_mode_blocks_after_bind(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLAYCALLER_UI_WRITE_GUARD", "strict")
    reset_ui_write_guard()
    register_ui_widget_key_bound("ui_down")
    ss: dict = {"ui_down": 1}
    with pytest.raises(RuntimeError, match="Illegal write"):
        assign_session_state(ss, "ui_down", 2, context="test_illegal")
    assert ss["ui_down"] == 1


def test_non_ui_keys_ignore_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLAYCALLER_UI_WRITE_GUARD", "strict")
    reset_ui_write_guard()
    register_ui_widget_key_bound("ui_down")
    ss: dict = {}
    assign_session_state(ss, "game_down", 3, context="test")
    assert ss["game_down"] == 3


def test_ui_auto_generate_never_registered_is_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """``ui_auto_generate`` has no Streamlit widget key — must stay assignable after other ui_ widgets."""
    monkeypatch.setenv("PLAYCALLER_UI_WRITE_GUARD", "strict")
    reset_ui_write_guard()
    register_ui_widget_key_bound("ui_down")
    ss: dict = {}
    assign_session_state(ss, "ui_auto_generate", True, context="test")
    assert ss["ui_auto_generate"] is True


def test_warn_mode_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLAYCALLER_UI_WRITE_GUARD", "warn")
    reset_ui_write_guard()
    register_ui_widget_key_bound("ui_down")
    ss: dict = {"ui_down": 1}
    assign_session_state(ss, "ui_down", 2, context="test_warn")
    assert ss["ui_down"] == 2
