"""Environment-backed history repository settings and generate-time corpus resolution."""

from __future__ import annotations

import pytest

from playcaller.history import build_historical_influence_config, load_history_repository_settings
from playcaller.history.records import HistoryCorpus
from playcaller.services.game_controller import resolve_historical_plays_for_generate
from playcaller.streamlit_state.keys import HV_SESSION_CORPUS_KEY, UI_HISTORICAL_NUDGE_ENABLED


def test_load_history_repository_settings_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLAYCALLER_HISTORY_DIR", "/data/history")
    monkeypatch.setenv("PLAYCALLER_HISTORY_NUDGE_DEFAULT", "1")
    monkeypatch.setenv("PLAYCALLER_HISTORY_MIN_OVERALL_MATCHES", "12")
    monkeypatch.setenv("PLAYCALLER_HISTORY_QUERY_MIN_MATCHES", "6")
    monkeypatch.setenv("PLAYCALLER_HISTORY_MAX_JSON_FILES", "100")
    s = load_history_repository_settings()
    assert s.default_directory == "/data/history"
    assert s.nudge_default_on is True
    assert s.history_force_off is False
    assert s.min_overall_matches == 12
    assert s.query_min_matches == 6
    assert s.max_json_files == 100


def test_query_min_clamped_to_overall(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLAYCALLER_HISTORY_MIN_OVERALL_MATCHES", "5")
    monkeypatch.setenv("PLAYCALLER_HISTORY_QUERY_MIN_MATCHES", "99")
    s = load_history_repository_settings()
    assert s.min_overall_matches == 5
    assert s.query_min_matches == 5


def test_history_force_off_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLAYCALLER_HISTORY_FORCE_OFF", "true")
    s = load_history_repository_settings()
    assert s.history_force_off is True


def test_build_historical_influence_config_matches_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLAYCALLER_HISTORY_MIN_OVERALL_MATCHES", "20")
    s = load_history_repository_settings()
    cfg = build_historical_influence_config(s)
    assert cfg.min_overall_matches == 20
    assert cfg.enabled is False


def test_resolve_historical_plays_respects_force_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLAYCALLER_HISTORY_FORCE_OFF", "1")

    class _C:
        plays = [1, 2, 3]

    ss = {UI_HISTORICAL_NUDGE_ENABLED: True, HV_SESSION_CORPUS_KEY: _C()}
    assert resolve_historical_plays_for_generate(ss) is None


def test_resolve_historical_plays_none_when_toggle_off() -> None:
    class _C:
        plays = [1]

    ss = {UI_HISTORICAL_NUDGE_ENABLED: False, HV_SESSION_CORPUS_KEY: _C()}
    assert resolve_historical_plays_for_generate(ss) is None


def test_resolve_historical_plays_empty_corpus() -> None:
    ss = {UI_HISTORICAL_NUDGE_ENABLED: True, HV_SESSION_CORPUS_KEY: HistoryCorpus(plays=[])}
    assert resolve_historical_plays_for_generate(ss) is None


def test_session_nudge_default_on_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLAYCALLER_HISTORY_NUDGE_DEFAULT", "1")
    from playcaller.streamlit_state.session import ensure_play_caller_session_defaults

    ss: dict = {}
    ensure_play_caller_session_defaults(ss)
    assert ss[UI_HISTORICAL_NUDGE_ENABLED] is True


def test_session_predictor_syncs_history_thresholds_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PLAYCALLER_HISTORY_MIN_OVERALL_MATCHES", "33")
    monkeypatch.setenv("PLAYCALLER_HISTORY_QUERY_MIN_MATCHES", "7")
    from playcaller.streamlit_state.session import ensure_play_caller_session_defaults

    ss: dict = {}
    ensure_play_caller_session_defaults(ss)
    hi = ss["predictor"].historical_influence
    assert hi is not None
    assert hi.min_overall_matches == 33
    assert hi.query_min_matches == 7
