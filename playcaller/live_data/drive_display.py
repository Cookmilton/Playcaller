"""Pure helpers for labeling archived drives in the UI (no Streamlit imports)."""

from __future__ import annotations

from typing import List, Optional

from playcaller.game import Drive, Game

# ``ui_previous_drives_filter`` / session values (stable strings).
PREVIOUS_DRIVES_FILTER_OUR = "our"
PREVIOUS_DRIVES_FILTER_OPPONENT = "opponent"
PREVIOUS_DRIVES_FILTER_BOTH = "both"

_PREVIOUS_DRIVES_FILTER_LABEL = {
    PREVIOUS_DRIVES_FILTER_OUR: "Our team only",
    PREVIOUS_DRIVES_FILTER_OPPONENT: "Opponent only",
    PREVIOUS_DRIVES_FILTER_BOTH: "Both teams",
}


def previous_drives_empty_filter_message(mode: str) -> str:
    """User-facing copy when no archived drives match the Previous drives filter."""
    m = str(mode or "").strip().lower()
    label = _PREVIOUS_DRIVES_FILTER_LABEL.get(m, _PREVIOUS_DRIVES_FILTER_LABEL[PREVIOUS_DRIVES_FILTER_OUR])
    return (
        f"No drives match the current filter (**{label}**). "
        "Try **Both teams** to see all drives."
    )


def drive_identity_key(dr: Drive) -> str:
    """Stable key for per-team drive numbering (feed id preferred)."""
    tid = str(getattr(dr, "feed_team_espn_id", "") or "").strip()
    if tid:
        return f"espn:{tid}"
    return f"pos:{getattr(dr, 'possessing_team', 'offense')}"


def chronological_team_drive_indices(game: Game) -> List[int]:
    """
    For each drive in ``game.drives`` (in order), the 1-based index of that drive
    for its possessing team (using :func:`drive_identity_key`).
    """
    seq: dict[str, int] = {}
    out: List[int] = []
    for dr in game.drives:
        k = drive_identity_key(dr)
        seq[k] = seq.get(k, 0) + 1
        out.append(seq[k])
    return out


def classify_drive_team_side(dr: Drive, *, our_coached_espn_id: str) -> Optional[str]:
    """
    Return ``"our"`` or ``"opp"`` for filter bucketing, or ``None`` when the drive
    cannot be classified without guessing (feed team id present but coached ESPN id unknown).
    """
    tid = str(getattr(dr, "feed_team_espn_id", "") or "").strip()
    oid = str(our_coached_espn_id or "").strip()
    if tid:
        if not oid:
            return None
        return "our" if tid == oid else "opp"
    poss = str(getattr(dr, "possessing_team", "offense") or "offense")
    return "our" if poss == "offense" else "opp"


def filter_previous_drive_indices(
    game: Game,
    *,
    mode: str,
    our_coached_espn_id: str,
) -> List[int]:
    """
    Indices into ``game.drives`` in chronological order that match ``mode``.

    * ``our`` / ``opponent`` — exclude drives with no resolvable side (see :func:`classify_drive_team_side`). ``both`` includes every drive.
    """
    n = len(game.drives)
    if mode == PREVIOUS_DRIVES_FILTER_BOTH:
        return list(range(n))
    want: Optional[str] = "our" if mode == PREVIOUS_DRIVES_FILTER_OUR else (
        "opp" if mode == PREVIOUS_DRIVES_FILTER_OPPONENT else None
    )
    if want is None:
        return list(range(n))
    out: List[int] = []
    for i, dr in enumerate(game.drives):
        side = classify_drive_team_side(dr, our_coached_espn_id=our_coached_espn_id)
        if side == want:
            out.append(i)
    return out


def prior_drive_heading(drive: Drive, team_drive_index: int) -> str:
    """
    Primary expander title for a completed drive (newest-first lists pass the same index).

    Examples: ``NYG drive 1 · Punt — 3 plays, …`` or ``Our team drive 2`` when no feed labels.
    """
    res = drive.result
    outcome = res.headline if res else "Drive"
    detail = res.detail_line if res else ""

    ab = str(getattr(drive, "feed_team_abbr", "") or "").strip()
    name = str(getattr(drive, "feed_team_display_name", "") or "").strip()
    if ab and name and ab.upper() != name.upper():
        team_part = f"{name} ({ab}) drive {team_drive_index}"
    elif name:
        team_part = f"{name} drive {team_drive_index}"
    elif ab:
        team_part = f"{ab} drive {team_drive_index}"
    else:
        side = "Our team" if drive.possessing_team == "offense" else "Opponent"
        team_part = f"{side} drive {team_drive_index}"

    if detail:
        return f"{team_part} · {outcome} — {detail}"
    return f"{team_part} · {outcome}"
