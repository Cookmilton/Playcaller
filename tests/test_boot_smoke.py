"""Smoke test that catches boot-time import errors before they reach a running Streamlit process.

This test was added after a circular import shipped to main with a passing pytest suite:
``streamlit run streamlit_app.py`` failed immediately while ``pytest tests/`` reported all
passing — pytest never imported the app's top-level module in boot order.

Imports modules that participate in the Streamlit boot import graph and asserts each
resolves cleanly.
"""

from __future__ import annotations

import importlib

import pytest

# Project modules on the path from streamlit_app → game_controller → UI chain (Stage 4 cut).
BOOT_MODULES = [
    "streamlit_app",
    "playcaller.services.game_controller",
    "playcaller.services.predictor_with_history",
    "playcaller.ui.main_console",
    "playcaller.ui.recommendations",
    "playcaller.ui.historical_signal",
    "warehouse.recommender",
]


@pytest.mark.parametrize("module_name", BOOT_MODULES)
def test_module_imports_cleanly(module_name: str) -> None:
    importlib.import_module(module_name)
