"""G2.5: hydrate / ui→game tripwire raises under pytest, warns-and-skips in production."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from playcaller.streamlit_state.hydrate_tripwire import HydrateClobberError
from playcaller.streamlit_state.keys import GAME_WIDGET_HYDRATE_PENDING
from playcaller.streamlit_state.widget_backend_bridge import sync_backend_from_widgets


def test_sync_backend_tripwire_raises_under_tests() -> None:
    """Deliberate hit: pytest (conftest flag) must raise, not clobber ``game_*``."""
    ss = {
        GAME_WIDGET_HYDRATE_PENDING: True,
        "game_down": 2,
        "ui_down": 1,
    }
    with pytest.raises(HydrateClobberError, match="GAME_WIDGET_HYDRATE_PENDING"):
        sync_backend_from_widgets(ss)
    assert ss["game_down"] == 2
    assert ss["ui_down"] == 1
    assert ss[GAME_WIDGET_HYDRATE_PENDING] is True


def test_sync_backend_tripwire_warns_when_raise_disabled() -> None:
    """Production path: flag off → warn, skip copy, never raise."""
    import playcaller.streamlit_state.hydrate_tripwire as hydrate_tripwire

    ss = {
        GAME_WIDGET_HYDRATE_PENDING: True,
        "game_down": 2,
        "ui_down": 1,
    }
    hydrate_tripwire.RAISE_ON_UI_TO_GAME_WHILE_HYDRATE_PENDING = False
    try:
        with patch("playcaller.streamlit_state.widget_backend_bridge.logger.warning") as warn:
            sync_backend_from_widgets(ss)
        assert ss["game_down"] == 2
        warn.assert_called()
        assert "GAME_WIDGET_HYDRATE_PENDING" in warn.call_args[0][0]
    finally:
        hydrate_tripwire.RAISE_ON_UI_TO_GAME_WHILE_HYDRATE_PENDING = True
