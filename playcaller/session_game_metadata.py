"""
Session-level game identity for Play Caller: ties drives, audits, and exports to one operator record.

Stored on ``Game.session_metadata`` as a plain dict for JSON round-trip; use :class:`SessionGameMetadata`
for typed access.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from typing import Any, Mapping, MutableMapping, Optional, Sequence


SESSION_METADATA_STORAGE_VERSION = 1


@dataclass
class SessionGameMetadata:
    """Operator-defined context for the current Streamlit session / saved game file."""

    session_game_id: str = ""
    team_name: str = ""
    opponent: str = ""
    game_date: str = ""
    game_label: str = ""
    season: str = ""
    roster_version: str = ""
    notes: str = ""
    is_simulated: bool = False

    def to_storage_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["_version"] = SESSION_METADATA_STORAGE_VERSION
        return d

    @classmethod
    def from_storage_dict(cls, raw: Optional[Mapping[str, Any]]) -> SessionGameMetadata:
        if not raw:
            return cls(session_game_id=str(uuid.uuid4()))
        sid = str(raw.get("session_game_id") or "").strip() or str(uuid.uuid4())
        return cls(
            session_game_id=sid,
            team_name=str(raw.get("team_name") or ""),
            opponent=str(raw.get("opponent") or ""),
            game_date=str(raw.get("game_date") or ""),
            game_label=str(raw.get("game_label") or ""),
            season=str(raw.get("season") or ""),
            roster_version=str(raw.get("roster_version") or ""),
            notes=str(raw.get("notes") or ""),
            is_simulated=bool(raw.get("is_simulated")) if "is_simulated" in raw else False,
        )


def fresh_session_metadata_dict() -> dict[str, Any]:
    """Used by ``Game.new_game()`` — new stable id, blank fields, real (non-simulated) default."""
    return SessionGameMetadata(session_game_id=str(uuid.uuid4())).to_storage_dict()


def session_metadata_is_identified(meta: Optional[Mapping[str, Any]]) -> bool:
    """Enough to treat the session as a deliberate game record (team + date + explicit real/sim flag)."""
    if not meta:
        return False
    team = str(meta.get("team_name") or "").strip()
    gd = str(meta.get("game_date") or "").strip()
    if not team or not gd:
        return False
    # is_simulated must be present as bool (legacy dicts without key → not identified)
    if "is_simulated" not in meta:
        return False
    return True


def session_metadata_warnings(meta: Optional[Mapping[str, Any]]) -> list[str]:
    """Human-readable gaps for the UI."""
    if session_metadata_is_identified(meta):
        return []
    out: list[str] = []
    if not meta or not str(meta.get("team_name") or "").strip():
        out.append("Add **our team name** so this session links to a real sideline.")
    if not meta or not str(meta.get("game_date") or "").strip():
        out.append("Add a **game date** (e.g. YYYY-MM-DD).")
    if not meta or "is_simulated" not in meta:
        out.append("Set **Simulated** vs **real** using the checkbox.")
    return out


def compact_session_summary_line(meta: Optional[Mapping[str, Any]]) -> str:
    """One-line status for the main console (plain text)."""
    if not meta:
        return "Session game: not configured"
    m = SessionGameMetadata.from_storage_dict(dict(meta))
    team = (m.team_name or "").strip() or "—"
    opp = (m.opponent or "").strip()
    dt = (m.game_date or "").strip()
    sim = "Simulated" if m.is_simulated else "Real"
    label = (m.game_label or "").strip()
    core = f"{team} vs {opp}" if opp else team
    if dt:
        core = f"{core} · {dt}"
    if label:
        core = f"{label}: {core}"
    return f"{core} · {sim} · id `{m.session_game_id[:8]}…`"


def audit_context_from_game_metadata(meta: Optional[Mapping[str, Any]]) -> Optional[dict[str, Any]]:
    """Slim payload embedded on each recommendation audit row."""
    if not meta:
        return None
    m = SessionGameMetadata.from_storage_dict(dict(meta))
    if not (m.session_game_id or "").strip():
        return None
    return {
        "session_game_id": m.session_game_id,
        "team_name": m.team_name,
        "opponent": m.opponent,
        "game_date": m.game_date,
        "game_label": m.game_label,
        "season": m.season,
        "roster_version": m.roster_version,
        "is_simulated": m.is_simulated,
    }


def format_audit_session_context_line(ctx: Mapping[str, Any]) -> str:
    """Short line for metrics / evaluation summaries."""
    team = str(ctx.get("team_name") or "").strip() or "—"
    opp = str(ctx.get("opponent") or "").strip()
    dt = str(ctx.get("game_date") or "").strip()
    sim = "sim" if ctx.get("is_simulated") else "real"
    tail = f" vs {opp}" if opp else ""
    dtp = f" · {dt}" if dt else ""
    return f"{team}{tail}{dtp} ({sim}) · {str(ctx.get('session_game_id') or '')[:8]}"


def read_session_metadata_dict(game: Any) -> Optional[dict[str, Any]]:
    """Return a copy of ``game.session_metadata`` when present (any object with that attribute)."""
    meta = getattr(game, "session_metadata", None)
    if not isinstance(meta, dict):
        return None
    return dict(meta)


def session_metadata_label_value_rows(meta: Optional[Mapping[str, Any]]) -> list[tuple[str, str]]:
    """(label, value) pairs for review / export UI — single source for operator-facing fields."""
    if not meta:
        return [
            (
                "Session game record",
                "Not set — use **Play Caller** session game details before export, or this file may predate session metadata.",
            )
        ]
    m = SessionGameMetadata.from_storage_dict(dict(meta))
    rows: list[tuple[str, str]] = [
        ("Our team", m.team_name.strip() or "—"),
        ("Opponent", m.opponent.strip() or "—"),
        ("Game date", m.game_date.strip() or "—"),
        ("Label / title", m.game_label.strip() or "—"),
        ("Season", m.season.strip() or "—"),
        ("Roster version", m.roster_version.strip() or "—"),
        ("Session mode", "Simulated" if m.is_simulated else "Real game"),
    ]
    if m.notes.strip():
        note = m.notes.strip()
        if len(note) > 220:
            note = note[:217] + "…"
        rows.append(("Notes", note))
    if m.session_game_id.strip():
        rows.append(("Session game id (stable linkage)", m.session_game_id))
    return rows


def format_session_metadata_markdown(meta: Optional[Mapping[str, Any]]) -> str:
    """Bullet markdown for Streamlit (operator-controlled text; keep simple markdown)."""
    lines = []
    for label, value in session_metadata_label_value_rows(meta):
        lines.append(f"- **{label}:** {value}")
    return "\n".join(lines)


def historical_snapshot_session_fields(
    meta: Optional[Mapping[str, Any]],
) -> tuple[Optional[str], Optional[bool]]:
    """``session_game_id`` and simulated flag for history snapshots / manifest (``None`` = unknown or legacy)."""
    if not meta:
        return None, None
    sid = str(meta.get("session_game_id") or "").strip() or None
    if "is_simulated" not in meta:
        return sid, None
    return sid, bool(meta.get("is_simulated"))


def session_flat_for_normalize(game: Any) -> dict[str, Any]:
    """Flat session fields copied onto each normalized historical play row."""
    sm = read_session_metadata_dict(game)
    if not sm:
        return {
            "session_game_id": None,
            "session_team_name": None,
            "session_opponent": None,
            "session_game_date": None,
            "session_game_label": None,
            "session_season": None,
            "session_roster_version": None,
            "session_is_simulated": None,
        }
    m = SessionGameMetadata.from_storage_dict(sm)
    sim: Optional[bool]
    if "is_simulated" not in sm:
        sim = None
    else:
        sim = bool(sm.get("is_simulated"))
    return {
        "session_game_id": m.session_game_id.strip() or None,
        "session_team_name": m.team_name.strip() or None,
        "session_opponent": m.opponent.strip() or None,
        "session_game_date": m.game_date.strip() or None,
        "session_game_label": m.game_label.strip() or None,
        "session_season": m.season.strip() or None,
        "session_roster_version": m.roster_version.strip() or None,
        "session_is_simulated": sim,
    }


def session_audit_identity_warning(
    game_meta: Optional[Mapping[str, Any]],
    audit: Sequence[Mapping[str, Any]],
) -> Optional[str]:
    """Warn when audit ``session_context`` disagrees with the game's ``session_metadata``."""
    if not isinstance(game_meta, dict):
        return None
    gid = str(game_meta.get("session_game_id") or "").strip()
    if not gid:
        return None
    for r in audit:
        if not isinstance(r, dict):
            continue
        sc = r.get("session_context")
        if not isinstance(sc, dict):
            continue
        aid = str(sc.get("session_game_id") or "").strip()
        if not aid:
            continue
        if aid != gid:
            return (
                f"Audit **session_context** id (`{aid[:8]}…`) does not match this file's "
                f"**session_metadata** (`{gid[:8]}…`). Possible merge or mixed exports."
            )
        return None
    return None


def game_json_export_hint_caption() -> str:
    """Sidebar / help: what is in a downloaded game JSON."""
    return (
        "The JSON includes **session_metadata** (team, opponent, date, label, season, roster version, "
        "simulated vs real, stable **session_game_id**) together with **drives** and the snap review timeline "
        "(**snap_review_log** and **recommendation_audit**, same rows)."
    )
