"""
Environment-backed defaults for the historical JSON repository and influence gates.

Streamlit and CLI can call ``load_history_repository_settings()`` with no args (uses ``os.environ``).
Tests may pass a mapping instead.

Variables (all optional):

- ``PLAYCALLER_HISTORY_DIR`` — default folder path pre-filled on the History library page.
- ``PLAYCALLER_HISTORY_NUDGE_DEFAULT`` — ``1`` / ``true`` / ``yes`` / ``on`` turns the sidebar nudge **on** by default for new sessions.
- ``PLAYCALLER_HISTORY_FORCE_OFF`` — ``1`` / ``true`` / ``yes`` / ``on`` disables passing any corpus to the recommender (toggle ignored).
- ``PLAYCALLER_HISTORY_MIN_OVERALL_MATCHES`` — override for ``HistoricalInfluenceConfig.min_overall_matches`` (clamped 3–200).
- ``PLAYCALLER_HISTORY_QUERY_MIN_MATCHES`` — override for ``HistoricalInfluenceConfig.query_min_matches`` (clamped 1–100).
- ``PLAYCALLER_HISTORY_MAX_JSON_FILES`` — max ``*.json`` files to read per directory load (0 = unlimited).
- ``PLAYCALLER_HISTORY_REPO`` — absolute path to the persistent history repository root (defaults to ``~/.playcaller/history_repository``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional

from .influence import HistoricalInfluenceConfig


def _env_truthy(raw: Optional[str]) -> bool:
    if raw is None:
        return False
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _env_int(raw: Optional[str], *, default: int, min_v: int, max_v: int) -> int:
    if raw is None or not str(raw).strip():
        return default
    try:
        v = int(str(raw).strip())
    except ValueError:
        return default
    return max(min_v, min(max_v, v))


def _env_optional_int(raw: Optional[str], *, min_v: int, max_v: int) -> Optional[int]:
    if raw is None or not str(raw).strip():
        return None
    try:
        v = int(str(raw).strip())
    except ValueError:
        return None
    if v <= 0:
        return None
    return max(min_v, min(max_v, v))


@dataclass(frozen=True)
class HistoryRepositorySettings:
    """First-pass configuration; keep small and explicit."""

    default_directory: str
    repository_directory: str
    nudge_default_on: bool
    history_force_off: bool
    min_overall_matches: int
    query_min_matches: int
    max_json_files: Optional[int]


def load_history_repository_settings(
    environ: Optional[Mapping[str, str]] = None,
) -> HistoryRepositorySettings:
    env = dict(os.environ) if environ is None else dict(environ)
    default_dir = str(env.get("PLAYCALLER_HISTORY_DIR") or "").strip()
    repo_dir = str(env.get("PLAYCALLER_HISTORY_REPO") or "").strip()

    min_overall = _env_int(
        env.get("PLAYCALLER_HISTORY_MIN_OVERALL_MATCHES"),
        default=8,
        min_v=3,
        max_v=200,
    )
    query_min = _env_int(
        env.get("PLAYCALLER_HISTORY_QUERY_MIN_MATCHES"),
        default=5,
        min_v=1,
        max_v=100,
    )
    if query_min > min_overall:
        query_min = max(1, min_overall)

    return HistoryRepositorySettings(
        default_directory=default_dir,
        repository_directory=repo_dir,
        nudge_default_on=_env_truthy(env.get("PLAYCALLER_HISTORY_NUDGE_DEFAULT")),
        history_force_off=_env_truthy(env.get("PLAYCALLER_HISTORY_FORCE_OFF")),
        min_overall_matches=min_overall,
        query_min_matches=query_min,
        max_json_files=_env_optional_int(
            env.get("PLAYCALLER_HISTORY_MAX_JSON_FILES"),
            min_v=1,
            max_v=50_000,
        ),
    )


def build_historical_influence_config(settings: HistoryRepositorySettings) -> HistoricalInfluenceConfig:
    """
    Influence knobs for the recommender (corpus still comes from the caller / session).

    ``enabled`` stays False so only explicit ``historical_plays=`` or future wired corpora apply.
    """
    return HistoricalInfluenceConfig(
        enabled=False,
        plays=None,
        min_overall_matches=int(settings.min_overall_matches),
        query_min_matches=int(settings.query_min_matches),
    )
