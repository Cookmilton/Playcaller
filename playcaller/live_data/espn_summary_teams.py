"""Map ESPN summary competition blocks to stable team labels (id → abbrev / display)."""

from __future__ import annotations

from typing import Any, Dict, Tuple


def team_labels_from_espn_summary(payload: Dict[str, Any]) -> Dict[str, Tuple[str, str]]:
    """
    Return ``team_espn_id -> (abbreviation, display_name)`` from ``header.competitions[0]``.

    Falls back to team id when abbrev or display names are missing.
    """
    header = payload.get("header") or {}
    comps = header.get("competitions") or []
    c0 = comps[0] if comps and isinstance(comps[0], dict) else None
    if not c0:
        return {}

    out: Dict[str, Tuple[str, str]] = {}
    for co in c0.get("competitors") or []:
        if not isinstance(co, dict):
            continue
        tid = str(co.get("id") or "").strip()
        team = co.get("team") if isinstance(co.get("team"), dict) else {}
        if not tid:
            continue
        abbr = str(team.get("abbreviation") or "").strip()
        display = str(
            team.get("displayName")
            or team.get("shortDisplayName")
            or team.get("name")
            or abbr
            or ""
        ).strip()
        if not display:
            display = f"Team {tid}"
        if not abbr:
            abbr = display[:10] if len(display) > 10 else display
        out[tid] = (abbr, display)
    return out


def team_label_pair(labels: Dict[str, Tuple[str, str]], team_espn_id: str) -> Tuple[str, str]:
    """Resolve abbrev + display for a drive's ``team.id``; safe when lookup fails."""
    tid = str(team_espn_id or "").strip()
    if tid and tid in labels:
        return labels[tid]
    if tid:
        return ("?", f"Team {tid}")
    return ("?", "Unknown team")
