"""Optional / sidecar metadata extracted from exported game JSON (beyond ``game_from_dict`` core)."""

from __future__ import annotations

from typing import Any, Dict


def _first_str(data: Dict[str, Any], *keys: str) -> str:
    for k in keys:
        raw = data.get(k)
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    return ""


def extract_sidecar_metadata(data: Dict[str, Any]) -> Dict[str, str]:
    """
    Best-effort labels for repository indexing.

    Exports may omit these keys; operators can enrich later in the library UI.
    Falls back to **session_metadata** (Play Caller operator identity) when top-level keys are absent.
    """
    sm = data.get("session_metadata")
    sm_d: Dict[str, Any] = sm if isinstance(sm, dict) else {}

    def pick_team() -> str:
        v = _first_str(data, "team", "our_team", "offense_team", "home_team")
        return v or _first_str(sm_d, "team_name")

    def pick_opponent() -> str:
        v = _first_str(
            data, "opponent", "opponent_team", "defense_team", "their_team", "away_team"
        )
        return v or _first_str(sm_d, "opponent")

    def pick_game_date() -> str:
        v = _first_str(data, "game_date", "date", "played_at", "kickoff")
        return v or _first_str(sm_d, "game_date")

    def pick_season() -> str:
        v = _first_str(data, "season", "season_year", "year")
        return v or _first_str(sm_d, "season")

    def pick_roster() -> str:
        v = _first_str(data, "roster_id", "roster", "personnel_id", "roster_key")
        return v or _first_str(sm_d, "roster_version")

    return {
        "team": pick_team(),
        "opponent": pick_opponent(),
        "game_date": pick_game_date(),
        "season": pick_season(),
        "roster_id": pick_roster(),
    }


def merge_metadata_with_overrides(base: Dict[str, str], overrides: Dict[str, Any]) -> Dict[str, str]:
    """Non-empty override values win (strings only)."""
    out = dict(base)
    for k in ("team", "opponent", "game_date", "season", "roster_id", "game_label"):
        v = overrides.get(k)
        if v is not None and str(v).strip():
            out[k] = str(v).strip()
    return out
