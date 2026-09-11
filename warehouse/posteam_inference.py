"""
Post-load posteam (possession team) gap filling for processed warehouse :class:`Play` rows.

Implements §10.1–§10.6: inference rules, drive boundaries, provenance, coverage metrics.
Does not persist to JSON, override non-empty feed values, or change scoring code.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any, Final, Sequence

from warehouse.models import DataSource, Game as WarehouseGame, GameStatus, GameType, Play
from warehouse.review_loader import parse_processed_payload
from warehouse.taxonomy import PlayType

# Drive heuristics default off: §9 validation showed *any* ffill to adjacent rows
# (e.g. PENALTY_NO_PLAY after scrimmage) can reorder implied point attribution; corpus
# |error| rose ~16×. Rules 3–4 remain in code; enable only after play-type-scoped
# gating in a follow-up. Rule 5 (modal) off by default for the same reason.
INFER_ENABLE_DRIVE_HEURISTICS: bool = False
INFER_ENABLE_DRIVE_MODE: bool = False

# Canonically aligned with ``warehouse.implied_score_audit`` skip-typed play coverage / classification.
_POSSESSION_COVERAGE_SKIPS: Final[frozenset[PlayType]] = frozenset(
    {
        PlayType.KICKOFF,
        PlayType.PUNT,
        PlayType.TIMEOUT,
        PlayType.PENALTY_NO_PLAY,
        PlayType.SPIKE,
        PlayType.KNEEL,
        PlayType.UNKNOWN,
    }
)

SOURCE_FEED = "feed"
SOURCE_MISSING = "missing"
TAG_INFERRED_OFFENSE = "inferred_offense_team"
TAG_INFERRED_DEFENSE = "inferred_defense_team"
TAG_INFERRED_FFILL = "inferred_drive_ffill"
TAG_INFERRED_BFILL = "inferred_drive_bfill"
TAG_INFERRED_MODE = "inferred_drive_mode"


@dataclass(frozen=True, slots=True)
class GameInferenceResult:
    game_id: str
    n_plays: int
    n_plays_possession: int
    coverage_overall_before: float
    coverage_possession_before: float
    coverage_overall_after: float
    coverage_possession_after: float
    n_originally_missing: int
    n_inferred_filled: int
    recovery_rate: float
    per_rule_fills: dict[str, int]
    play_source_by_sorted_index: dict[int, str]
    quality_bucket: str  # "clean" | "moderate" | "aggressive"


def is_skip_play_type(wt: PlayType) -> bool:
    return wt in _POSSESSION_COVERAGE_SKIPS


def _strip_team(x: str | None) -> str:
    if x is None:
        return ""
    return str(x).strip()


def _is_valid_abbr(ab: str, *, home_team: str, away_team: str) -> bool:
    a = _strip_team(ab)
    h, w = _strip_team(home_team), _strip_team(away_team)
    if not a or not h or not w:
        return False
    return a == h or a == w


def _feed_posteam_stripped(p: Play) -> str:
    return _strip_team(p.scoring_possession_team)


def _try_rule1_offense(
    p: Play, *, home_team: str, away_team: str
) -> tuple[str, str] | None:
    o = getattr(p, "offense_team", None)
    s = _strip_team(o) if o is not None else ""
    if s and _is_valid_abbr(s, home_team=home_team, away_team=away_team):
        return (s, TAG_INFERRED_OFFENSE)
    return None


def _try_rule2_defense(
    p: Play, *, home_team: str, away_team: str
) -> tuple[str, str] | None:
    d = _strip_team(p.defense_team)
    h, a = _strip_team(home_team), _strip_team(away_team)
    if not d or not h or not a:
        return None
    if d == h:
        return (a, TAG_INFERRED_DEFENSE)
    if d == a:
        return (h, TAG_INFERRED_DEFENSE)
    return None


def _drive_modal_feed_only(
    drive_plays: list[Play], home_team: str, away_team: str
) -> str | None:
    vals: list[str] = []
    for p in drive_plays:
        f = _feed_posteam_stripped(p)
        if f and _is_valid_abbr(f, home_team=home_team, away_team=away_team):
            vals.append(f)
    n = len(vals)
    if n < 3:
        return None
    counts: dict[str, int] = {}
    for v in vals:
        counts[v] = counts.get(v, 0) + 1
    best = max(counts.values())
    winners = [k for k, c in counts.items() if c == best]
    if not winners or best <= n * 0.5:
        return None
    return sorted(winners)[0]


def _metrics_for_plays(
    pls: list[Play], *, which: str
) -> tuple[float, float, int]:
    def _v(p: Play) -> str:
        if which == "scoring":
            return _strip_team(p.scoring_possession_team)
        if which == "display":
            return _strip_team(p.display_possession_team)
        msg = f"which must be 'scoring' or 'display', got {which!r}"
        raise ValueError(msg)

    tot = n_poss = fil_tot = fil_p = 0
    for p in pls:
        filled = 1 if _v(p) else 0
        tot += 1
        fil_tot += filled
        if not is_skip_play_type(p.play_type):
            n_poss += 1
            fil_p += filled
    ovr = fil_tot / tot if tot else 0.0
    pss = fil_p / n_poss if n_poss else 0.0
    return ovr, pss, n_poss


def infer_warehouse_plays(
    plays: Sequence[Play],
    features: Sequence,
    wh_game: WarehouseGame,
) -> tuple[list[Play], dict[int, str], GameInferenceResult]:
    """
    Fill missing **display** posteam (``display_possession_team``) when allowed; never mutates
    ``scoring_possession_team`` (feed-only). See §10.1.
    Returns new ``Play`` list (same order as *plays*), ``posteam_source`` by sorted index, stats.
    """
    home_team, away_team = wh_game.home_team, wh_game.away_team
    by_pid = {f.play_id: f for f in features}
    ordered = sorted(plays, key=lambda x: (x.play_sequence, str(x.external_play_id)))
    n = len(ordered)

    drive_for: list[int] = []
    for p in ordered:
        f = by_pid.get(p.id)
        drive_for.append(int(f.drive_number) if f is not None else -1)

    original_feed: list[str] = [_feed_posteam_stripped(p) for p in ordered]
    is_feed: list[bool] = [bool(x) for x in original_feed]
    r1: list[str | None] = [None] * n
    r2: list[str | None] = [None] * n
    for i, p in enumerate(ordered):
        if is_feed[i]:
            continue
        t = _try_rule1_offense(p, home_team=home_team, away_team=away_team)
        if t:
            r1[i] = t[0]
        t2 = _try_rule2_defense(p, home_team=home_team, away_team=away_team)
        if t2:
            r2[i] = t2[0]

    def base_anchor(i: int) -> str:
        v = original_feed[i]
        if v:
            return v
        if r1[i]:
            return r1[i]  # type: ignore[return-value]
        if r2[i]:
            return r2[i]  # type: ignore[return-value]
        return ""

    by_drv: dict[int, list[int]] = defaultdict(list)
    for i, dn in enumerate(drive_for):
        if dn >= 0:
            by_drv[dn].append(i)
    for dn in by_drv:
        by_drv[dn].sort()

    final_t: list[str] = [original_feed[i] for i in range(n)]
    tag: list[str] = [SOURCE_FEED if is_feed[i] else SOURCE_MISSING for i in range(n)]

    for i in range(n):
        if is_feed[i]:
            continue
        if r1[i]:
            final_t[i] = r1[i]  # type: ignore[assignment]
            tag[i] = TAG_INFERRED_OFFENSE
            continue
        if r2[i]:
            final_t[i] = r2[i]  # type: ignore[assignment]
            tag[i] = TAG_INFERRED_DEFENSE
            continue
        if not INFER_ENABLE_DRIVE_HEURISTICS:
            tag[i] = SOURCE_MISSING
            continue
        dix = drive_for[i]
        dixl = by_drv.get(dix, [])

        def _anchorable(j: int) -> bool:
            if is_skip_play_type(ordered[j].play_type):
                return False
            return bool(base_anchor(j))

        # Rule 3 — ffill: immediate predecessor in the global order *when same drive* (tight vs §10.1 "most recent")
        if (
            i > 0
            and drive_for[i - 1] == dix
            and _anchorable(i - 1)
        ):
            final_t[i] = base_anchor(i - 1)
            tag[i] = TAG_INFERRED_FFILL
            continue
        if (
            i + 1 < n
            and drive_for[i + 1] == dix
            and _anchorable(i + 1)
        ):
            final_t[i] = base_anchor(i + 1)
            tag[i] = TAG_INFERRED_BFILL
            continue
        if INFER_ENABLE_DRIVE_MODE and dix >= 0:
            dplays = [ordered[j] for j in dixl if not is_skip_play_type(ordered[j].play_type)]
            mode = _drive_modal_feed_only(dplays, home_team, away_team)
            if mode:
                final_t[i] = mode
                tag[i] = TAG_INFERRED_MODE
                continue
        tag[i] = SOURCE_MISSING

    new_ordered: list[Play] = []
    for i, p in enumerate(ordered):
        if is_feed[i]:
            new_ordered.append(p)
        else:
            if final_t[i] and tag[i] != SOURCE_MISSING:
                new_ordered.append(
                    replace(
                        p,
                        display_possession_team=final_t[i],
                        posteam_source=tag[i],
                    )
                )
            else:
                new_ordered.append(p)

    by_id: dict[str, Play] = {p.id: p for p in new_ordered}
    out = [by_id[p.id] for p in plays]

    source_by_sorted_index = {i: tag[i] for i in range(n)}

    ovr0, pss0, n_poss = _metrics_for_plays(list(ordered), which="scoring")
    ovr1, pss1, _ = _metrics_for_plays(new_ordered, which="display")
    n_feed = sum(1 for x in is_feed if x)
    n_orig_missing = n - n_feed
    n_inferred = sum(1 for i in range(n) if tag[i].startswith("inferred_"))
    recovery = n_inferred / n_orig_missing if n_orig_missing else 1.0
    per_rule: dict[str, int] = {}
    for i in range(n):
        t = tag[i]
        if t.startswith("inferred_"):
            per_rule[t] = per_rule.get(t, 0) + 1
    if n_inferred <= 2:
        qbucket = "clean"
    elif n_inferred <= 10:
        qbucket = "moderate"
    else:
        qbucket = "aggressive"

    gid = str(wh_game.external_game_id or wh_game.id)
    res = GameInferenceResult(
        game_id=gid,
        n_plays=n,
        n_plays_possession=n_poss,
        coverage_overall_before=ovr0,
        coverage_possession_before=pss0,
        coverage_overall_after=ovr1,
        coverage_possession_after=pss1,
        n_originally_missing=n_orig_missing,
        n_inferred_filled=n_inferred,
        recovery_rate=recovery,
        per_rule_fills=per_rule,
        play_source_by_sorted_index=dict(source_by_sorted_index),
        quality_bucket=qbucket,
    )
    return (out, source_by_sorted_index, res)


def infer_posteam(
    plays: list[Play],
    features: list,
    *,
    home_team: str,
    away_team: str,
) -> tuple[list[Play], dict[int, str]]:
    """
    Pure-function surface: needs drive features for §10 drive rules. Builds a
    throwaway :class:`WarehouseGame` (IDs placeholder) to supply home/away.
    For full stats use :func:`infer_warehouse_plays` with a real ``wh_game``.
    """
    wh = WarehouseGame(
        id="_infer",
        source=DataSource.OTHER,
        external_game_id="_infer",
        season=0,
        week=0,
        game_type=GameType.REG,
        home_team=home_team,
        away_team=away_team,
        game_date=date(2000, 1, 1),
        status=GameStatus.FINAL,
    )
    npl, tags, _ = infer_warehouse_plays(plays, features, wh)
    return npl, tags


def infer_corpus(
    game_payloads: list[dict[str, Any]],
) -> dict[str, GameInferenceResult]:
    out: dict[str, GameInferenceResult] = {}
    for data in game_payloads:
        wh, plays, feats = parse_processed_payload(data)
        _np, _tags, res = infer_warehouse_plays(plays, feats, wh)
        out[res.game_id] = res
    return out


def playcaller_game_from_processed_path(
    path: str | Path, *, with_posteam_inference: bool = False
):
    """Thin convenience around :func:`warehouse.review_loader.warehouse_bundle_from_processed_path` (keeps I/O and JSON errors in one place)."""
    from warehouse.review_loader import warehouse_bundle_from_processed_path

    g, _rows = warehouse_bundle_from_processed_path(
        path, with_posteam_inference=with_posteam_inference
    )
    return g
