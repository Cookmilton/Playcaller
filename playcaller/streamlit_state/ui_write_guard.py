"""
Per-key guard for Streamlit ``ui_*`` session keys bound to widgets.

Streamlit forbids assigning ``st.session_state[key]`` after a widget with ``key=key`` has been
constructed **earlier in the same script run**. This is *per key*, not “after any widget”.

We record each ``ui_*`` key the moment its widget is instantiated (see sidebar). Any later
assignment to that key in the same run triggers a warning or error (see``PLAYCALLER_UI_WRITE_GUARD``).

**Allowed without registration:** keys that are never used as ``key=`` on a Streamlit widget
(e.g. ``ui_auto_generate``) never enter the frozen set.

Pre-widget paths (``pending.py``, ``reconcile`` → ``sync_widgets_from_backend``, session
defaults) run before sidebar registration, so they do not trip the guard.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Literal, MutableMapping

logger = logging.getLogger(__name__)

_bound_ui_widget_keys: set[str] = set()

GuardMode = Literal["off", "warn", "strict"]


def _guard_mode() -> GuardMode:
    raw = (os.environ.get("PLAYCALLER_UI_WRITE_GUARD") or "warn").strip().lower()
    if raw in ("0", "off", "false", "no"):
        return "off"
    if raw in ("strict", "error", "1", "true", "yes"):
        return "strict"
    return "warn"


def reset_ui_write_guard() -> None:
    """Call once at the start of each Streamlit script run (main app + multipage entrypoints)."""
    _bound_ui_widget_keys.clear()


def register_ui_widget_key_bound(key: str) -> None:
    """
    Mark ``key`` as bound by a Streamlit widget in the current run.

    Call immediately **after** each sidebar widget that uses ``key=`` with a ``ui_*`` value.
    """
    if key.startswith("ui_"):
        _bound_ui_widget_keys.add(key)


def assign_session_state(
    ss: MutableMapping[str, Any],
    key: str,
    value: Any,
    *,
    context: str = "",
) -> None:
    """
    Assign ``ss[key] = value`` with optional enforcement for frozen ``ui_*`` widget keys.

    Prefer this for controller code (presets, callbacks) so violations are visible in dev.
    """
    if isinstance(key, str) and key.startswith("ui_") and key in _bound_ui_widget_keys:
        msg = (
            f"Illegal write to widget-bound session key {key!r} after that widget was "
            f"instantiated this run. Use ``game_*`` + ``request_widget_hydrate_from_backend`` "
            f"or queue via ``pending`` buffers. Context: {context or '(none)'}"
        )
        mode = _guard_mode()
        if mode == "strict":
            raise RuntimeError(msg)
        if mode == "warn":
            logger.warning(msg)
    ss[key] = value


def bound_ui_keys_snapshot() -> frozenset[str]:
    """Test hook: frozen ``ui_*`` keys registered so far this run."""
    return frozenset(_bound_ui_widget_keys)
