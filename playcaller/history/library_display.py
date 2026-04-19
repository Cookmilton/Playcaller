"""
Pure helpers for History library presentation: titles, table rows, filtering, duplicate hints.

No Streamlit imports — safe for tests and reuse outside the page.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

# --- Import batch lookup ---


def import_batches_by_id(manifest: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    out: Dict[str, Mapping[str, Any]] = {}
    for imp in manifest.get("imports") or []:
        if not isinstance(imp, dict):
            continue
        iid = str(imp.get("import_id") or "").strip()
        if iid:
            out[iid] = imp
    return out


def game_imported_at_display(rec: Mapping[str, Any], batches: Mapping[str, Mapping[str, Any]]) -> str:
    iid = str(rec.get("import_id") or "").strip()
    imp = batches.get(iid) or {}
    raw = str(imp.get("created_at_iso") or "").strip()
    if len(raw) >= 19:
        return raw[:19].replace("T", " ")
    return raw or "—"


def import_batch_label(batches: Mapping[str, Mapping[str, Any]], import_id: str) -> str:
    imp = batches.get(str(import_id).strip()) or {}
    kind = str(imp.get("source_kind") or "").strip() or "—"
    when = str(imp.get("created_at_iso") or "").strip()
    if len(when) >= 10:
        when = when[:10]
    return f"{when} · {kind}" if when else kind


# --- Title ---


def _normalize_date_fragment(s: str) -> str:
    t = str(s or "").strip()
    if not t:
        return ""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return t[:32]


def human_readable_game_title(rec: Mapping[str, Any]) -> str:
    """
    Primary library label: date · Team vs Opponent when possible; never raw filename alone.
    """
    team = str(rec.get("team") or "").strip()
    opponent = str(rec.get("opponent") or "").strip()
    date = _normalize_date_fragment(str(rec.get("game_date") or ""))
    glabel = str(rec.get("game_label") or "").strip()

    if team and opponent:
        core = f"{team} vs {opponent}"
        return f"{date} · {core}" if date else core

    if glabel:
        if date and date not in glabel:
            return f"{date} · {glabel}"
        return glabel

    fn = str(rec.get("source_filename") or "").strip()
    stem = _filename_stem(fn)
    rid = str(rec.get("repo_game_id") or "").strip()
    short = rid[:8] if rid else ""
    if stem:
        if short:
            return f"{stem[:56]}{'…' if len(stem) > 56 else ''} · {short}"
        return stem[:72] + ("…" if len(stem) > 72 else "")
    return f"Imported game · {short}" if short else "Imported game"


def _filename_stem(name: str) -> str:
    """Filename without extension."""
    base = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if base.lower().endswith(".json"):
        return base[:-5]
    return base


# --- Row building / context ---


def score_display(rec: Mapping[str, Any]) -> str:
    try:
        o = int(rec.get("offense_points"))
        d = int(rec.get("defense_points"))
        return f"{o}–{d}"
    except (TypeError, ValueError):
        return "—"


def sim_short(rec: Mapping[str, Any]) -> str:
    sim_raw = rec.get("session_is_simulated")
    if sim_raw is True:
        return "Sim"
    if sim_raw is False:
        return "Real"
    return "—"


def tags_display(rec: Mapping[str, Any]) -> str:
    tags = rec.get("tags")
    if not isinstance(tags, list) or not tags:
        return "—"
    return ", ".join(str(t) for t in tags[:12] if str(t).strip())


def validation_badge(rec: Mapping[str, Any]) -> str:
    st = str(rec.get("validation_status") or "").strip().lower()
    if st == "ok":
        return "OK"
    if st == "warnings":
        return "Warnings"
    return st.upper() if st else "—"


def build_library_table_row(
    rec: Mapping[str, Any],
    *,
    batches: Mapping[str, Mapping[str, Any]],
    duplicate_repo_ids: Set[str],
) -> Dict[str, Any]:
    rid = str(rec.get("repo_game_id") or "")
    title = human_readable_game_title(rec)
    dup = "Yes" if rid in duplicate_repo_ids else "—"
    return {
        "Title": title,
        "Date": str(rec.get("game_date") or "").strip() or "—",
        "Team": str(rec.get("team") or "").strip() or "—",
        "Opponent": str(rec.get("opponent") or "").strip() or "—",
        "Season": str(rec.get("season") or "").strip() or "—",
        "Roster": str(rec.get("roster_id") or "").strip() or "—",
        "Plays": rec.get("play_count") if rec.get("play_count") is not None else "—",
        "Drives": rec.get("drive_count") if rec.get("drive_count") is not None else "—",
        "Score": score_display(rec),
        "Status": validation_badge(rec),
        "Sim": sim_short(rec),
        "Tags": tags_display(rec),
        "Source file": str(rec.get("source_filename") or "").strip() or "—",
        "Imported": game_imported_at_display(rec, batches),
        "Batch": import_batch_label(batches, str(rec.get("import_id") or "")),
        "Dup?": dup,
        "_repo_game_id": rid,
    }


def compact_context_lines(rec: Mapping[str, Any], batches: Mapping[str, Mapping[str, Any]]) -> List[str]:
    """Short bullet lines for detail panel / tooltips."""
    lines = [
        f"**Title:** {human_readable_game_title(rec)}",
        f"**Team / opponent:** {rec.get('team') or '—'} vs {rec.get('opponent') or '—'}",
        f"**Date · season:** {rec.get('game_date') or '—'} · {rec.get('season') or '—'}",
        f"**Roster:** {rec.get('roster_id') or '—'}",
        f"**Plays / drives:** {rec.get('play_count')} · {rec.get('drive_count')}",
        f"**Score (off–def):** {score_display(rec)}",
        f"**Validation:** {validation_badge(rec)}",
        f"**Source file:** {rec.get('source_filename') or '—'}",
        f"**Imported:** {game_imported_at_display(rec, batches)}",
    ]
    w = rec.get("validation_warnings")
    if isinstance(w, list) and w:
        lines.append("**Warnings:** " + "; ".join(str(x) for x in w[:6]))
    return lines


# --- Duplicates ---


def session_game_id_duplicate_repo_ids(games: Sequence[Mapping[str, Any]]) -> Set[str]:
    """repo_game_ids that share a non-empty session_game_id with at least one other row."""
    buckets: Dict[str, List[str]] = {}
    for g in games:
        sid = str(g.get("session_game_id") or "").strip()
        rid = str(g.get("repo_game_id") or "").strip()
        if sid and rid:
            buckets.setdefault(sid, []).append(rid)
    out: Set[str] = set()
    for ids in buckets.values():
        if len(ids) > 1:
            out.update(ids)
    return out


def duplicate_hint_for_new_imports(
    all_games: Sequence[Mapping[str, Any]],
    newest_repo_ids: Set[str],
) -> Optional[str]:
    if not newest_repo_ids:
        return None
    dup_set = session_game_id_duplicate_repo_ids(all_games)
    touched = dup_set & newest_repo_ids
    if not touched:
        return None
    return (
        "Some new rows share a **session id** with another index entry — often a **re-import** of the same export. "
        "Use **Dup?** in the library or remove extras in `manifest.json` if needed."
    )


# --- Filtering ---


def sorted_distinct_str(values: Sequence[str]) -> List[str]:
    seen = sorted({str(v).strip() for v in values if str(v).strip()})
    return seen


def filter_game_records(
    games: List[Mapping[str, Any]],
    *,
    search: str = "",
    team: str = "",
    opponent: str = "",
    season: str = "",
    roster: str = "",
    validation: str = "all",
    import_id: str = "",
    tag: str = "",
    duplicates_only: bool = False,
    duplicate_repo_ids: Optional[Set[str]] = None,
) -> List[Mapping[str, Any]]:
    q = str(search or "").strip().lower()
    team_f = str(team or "").strip().lower()
    opp_f = str(opponent or "").strip().lower()
    season_f = str(season or "").strip().lower()
    roster_f = str(roster or "").strip().lower()
    val_f = str(validation or "").strip().lower()
    imp_f = str(import_id or "").strip()
    tag_f = str(tag or "").strip().lower()
    dup_ids = duplicate_repo_ids or set()

    out: List[Mapping[str, Any]] = []
    for g in games:
        if not isinstance(g, dict):
            continue
        if duplicates_only and str(g.get("repo_game_id") or "") not in dup_ids:
            continue
        if team_f and str(g.get("team") or "").strip().lower() != team_f:
            continue
        if opp_f and str(g.get("opponent") or "").strip().lower() != opp_f:
            continue
        if season_f and str(g.get("season") or "").strip().lower() != season_f:
            continue
        if roster_f and str(g.get("roster_id") or "").strip().lower() != roster_f:
            continue
        if val_f and val_f != "all":
            if str(g.get("validation_status") or "").strip().lower() != val_f:
                continue
        if imp_f and str(g.get("import_id") or "").strip() != imp_f:
            continue
        if tag_f:
            tags = g.get("tags")
            if not isinstance(tags, list) or not any(tag_f in str(t).lower() for t in tags):
                continue
        if q:
            blob = " ".join(
                [
                    human_readable_game_title(g),
                    str(g.get("team") or ""),
                    str(g.get("opponent") or ""),
                    str(g.get("game_label") or ""),
                    str(g.get("source_filename") or ""),
                    str(g.get("repo_game_id") or ""),
                    str(g.get("session_game_id") or ""),
                    tags_display(g),
                ]
            ).lower()
            if q not in blob:
                continue
        out.append(g)
    return out


def sort_games_for_library(
    games: List[Mapping[str, Any]],
    *,
    batches: Mapping[str, Mapping[str, Any]],
    sort_mode: str = "imported_desc",
) -> List[Mapping[str, Any]]:
    mode = str(sort_mode or "imported_desc").strip().lower()

    def imported_key(g: Mapping[str, Any]) -> str:
        return game_imported_at_display(g, batches)

    def date_key(g: Mapping[str, Any]) -> str:
        return str(g.get("game_date") or "")

    if mode == "date_desc":
        return sorted(games, key=lambda g: date_key(g), reverse=True)
    if mode == "date_asc":
        return sorted(games, key=lambda g: date_key(g))
    if mode == "title_asc":
        return sorted(games, key=lambda g: human_readable_game_title(g).lower())
    # imported_desc (default)
    return sorted(games, key=lambda g: imported_key(g), reverse=True)


# --- Ingest summary (duck-typed reports with files_found, etc.) ---


def aggregate_ingest_reports(reports: Sequence[Any]) -> Dict[str, Any]:
    total_found = 0
    total_imported = 0
    total_rejected = 0
    all_warnings: List[str] = []
    all_rejected: List[Tuple[str, str]] = []
    new_ids: List[str] = []
    for r in reports:
        total_found += int(getattr(r, "files_found", 0) or 0)
        total_imported += int(getattr(r, "files_imported", 0) or 0)
        total_rejected += int(getattr(r, "files_rejected", 0) or 0)
        for w in getattr(r, "warnings", None) or []:
            if w and str(w) not in all_warnings:
                all_warnings.append(str(w))
        for rej in getattr(r, "rejected", None) or []:
            name = str(getattr(rej, "logical_name", "") or "")
            reason = str(getattr(rej, "reason", "") or "")
            all_rejected.append((name, reason))
        for gid in getattr(r, "game_repo_ids", None) or []:
            new_ids.append(str(gid))
    return {
        "files_found": total_found,
        "files_imported": total_imported,
        "files_rejected": total_rejected,
        "game_repo_ids": new_ids,
        "warnings": all_warnings[:80],
        "rejected": all_rejected,
    }
