"""
CLI: per-play implied scoring audit for one processed warehouse JSON game.

Replays :func:`playcaller.implied_scoring.warehouse_session_points_for_play` in
drive order and prints enum vs scoreboard-delta vs skipped rows for triage
(posteam join, feed lag, abbr drift).

From repo root::

    python3 -m warehouse.implied_score_audit path/to/00afde0b7876f92a.json
    python3 -m warehouse.implied_score_audit path/to/game.json --csv
    python3 -m warehouse.implied_score_audit a.json b.json c.json
    python3 -m warehouse.implied_score_audit --batch gap_list.txt
    python3 -m warehouse.implied_score_audit --summary data/processed
    python3 -m warehouse.implied_score_audit --summary data/processed --with-inference
    python3 -m warehouse.implied_score_audit --summary data/processed --inference-compare
    python3 -m warehouse.implied_score_audit --summary data/processed --classification-csv /tmp/out.csv
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence, TextIO

from playcaller.implied_scoring import (
    UnattributableScoreAccumulator,
    _admin_play_skip_delta,
    _scoreboard_delta_ha,
    implied_totals_and_breakdown_from_warehouse_plays,
    points_for_play,
    warehouse_session_points_for_play,
)
from playcaller.domain import ActualPlayResult
from playcaller.game import Game
from warehouse.review_loader import warehouse_bundle_from_processed_path
from warehouse.taxonomy import PlayType as _PlayTypeEnum

# --- Failure-mode taxonomy (§10.1) — thresholds tunable within commented ranges ---
POSTEAM_MISSING = "POSTEAM_MISSING"
POSTEAM_MISALIGNED = "POSTEAM_MISALIGNED"
DELTA_LAG = "DELTA_LAG"
DOUBLE_COUNT_DELTA = "DOUBLE_COUNT_DELTA"
ENUM_MISSED_TD = "ENUM_MISSED_TD"
MIXED_FEED_INCONSISTENCY = "MIXED_FEED_INCONSISTENCY"
UNKNOWN = "UNKNOWN"

ALL_FAILURE_LABELS: tuple[str, ...] = (
    POSTEAM_MISSING,
    POSTEAM_MISALIGNED,
    DELTA_LAG,
    DOUBLE_COUNT_DELTA,
    ENUM_MISSED_TD,
    MIXED_FEED_INCONSISTENCY,
    UNKNOWN,
)

# POSTEAM_MISSING: coverage < threshold (allowed 0.90–0.98)
T_POSTEAM_COVERAGE_MIN = 0.95
# POSTEAM_MISALIGNED: mismatch rate > threshold (allowed 0.03–0.10)
T_POSTEAM_MISMATCH = 0.05
# DELTA_LAG: pct_delta_only > threshold (allowed 0.15–0.30)
T_DELTA_LAG_FRAC = 0.20
# ENUM_MISSED_TD: count >= threshold (allowed 1–3)
T_ENUM_MISSED_TD_COUNT = 2

_DOMINANT_PRIORITY: tuple[str, ...] = (
    POSTEAM_MISSING,
    DOUBLE_COUNT_DELTA,
    POSTEAM_MISALIGNED,
    ENUM_MISSED_TD,
    DELTA_LAG,
    MIXED_FEED_INCONSISTENCY,
    UNKNOWN,
)

_SKIP_PLAYTYPE_MEMBERS: frozenset[_PlayTypeEnum] = frozenset(
    {
        _PlayTypeEnum.KICKOFF,
        _PlayTypeEnum.PUNT,
        _PlayTypeEnum.TIMEOUT,
        _PlayTypeEnum.PENALTY_NO_PLAY,
        _PlayTypeEnum.SPIKE,
        _PlayTypeEnum.KNEEL,
        _PlayTypeEnum.UNKNOWN,
    }
)
_ADMIN_SKIP_WTYPE_CANONICAL: frozenset[str] = frozenset(
    m.value for m in _SKIP_PLAYTYPE_MEMBERS
)


@dataclass(frozen=True)
class GameClassification:
    game_id: str
    n_plays: int
    error_home: int | None
    error_away: int | None
    game_error_magnitude: int | None
    pct_enum: float
    pct_delta_only: float
    pct_skipped: float
    # Share of plays with a **feed** (scoring) posteam — drives POSTEAM_MISSING.
    posteam_coverage: float
    # Share of plays with a non-empty **display** posteam (feed or inference).
    posteam_display_coverage: float
    posteam_mismatch_rate: float
    n_double_delta: int
    n_delta_on_skip_play_type: int
    n_extreme_delta: int
    n_likely_missed_td: int
    applied_labels: tuple[str, ...]
    dominant_failure_mode: str | None
    explanation: str
    classification_error: str | None = None


def _possession_join(
    abbr: Optional[str], *, home_team: str, away_team: str
) -> str:
    a = (abbr or "").strip()
    h, w = (home_team or "").strip(), (away_team or "").strip()
    if not a:
        return "null"
    if h and a == h:
        return "home"
    if w and a == w:
        return "away"
    return "mismatch"


def _parse_board_delta(row: dict[str, Any]) -> tuple[int | None, int | None]:
    dh_raw, da_raw = row.get("d_home"), row.get("d_away")
    if dh_raw is None or da_raw is None or dh_raw == "" or da_raw == "":
        return None, None
    try:
        return int(dh_raw), int(da_raw)
    except (TypeError, ValueError):
        return None, None


def _drive_mode_posteams(rows: list[dict[str, Any]]) -> dict[int, str]:
    by_drive: dict[int, list[str]] = {}
    for r in rows:
        d = int(r["drive_index"])
        pt = (r.get("posteam") or "").strip()
        if not pt:
            continue
        by_drive.setdefault(d, []).append(pt)
    modes: dict[int, str] = {}
    for d, lst in by_drive.items():
        c = Counter(lst)
        best = max(c.values())
        tiebreak = sorted(k for k, v in c.items() if v == best)
        modes[d] = tiebreak[0]
    return modes


def _posteam_mismatch_rate(rows: list[dict[str, Any]]) -> float:
    modes = _drive_mode_posteams(rows)
    num = den = 0
    for r in rows:
        pt = (r.get("posteam") or "").strip()
        if not pt:
            continue
        den += 1
        dix = int(r["drive_index"])
        expected = modes.get(dix, pt)
        if pt != expected:
            num += 1
    return num / den if den else 0.0


def classify_game(
    per_play_rows: Sequence[dict[str, Any]],
    game_id: str,
    *,
    session_home: int | None = None,
    session_away: int | None = None,
) -> GameClassification:
    """Classify one game from in-memory per-play audit dicts (see :func:`per_play_row_dicts_from_game`)."""
    rows = list(per_play_rows)
    try:
        return _classify_game_impl(rows, game_id, session_home=session_home, session_away=session_away)
    except Exception as exc:
        return GameClassification(
            game_id=game_id,
            n_plays=len(rows),
            error_home=None,
            error_away=None,
            game_error_magnitude=None,
            pct_enum=0.0,
            pct_delta_only=0.0,
            pct_skipped=0.0,
            posteam_coverage=0.0,
            posteam_display_coverage=0.0,
            posteam_mismatch_rate=0.0,
            n_double_delta=0,
            n_delta_on_skip_play_type=0,
            n_extreme_delta=0,
            n_likely_missed_td=0,
            applied_labels=(),
            dominant_failure_mode=None,
            explanation="Classification failed.",
            classification_error=str(exc),
        )


def _classify_game_impl(
    rows: list[dict[str, Any]],
    game_id: str,
    *,
    session_home: int | None,
    session_away: int | None,
) -> GameClassification:
    n_plays = len(rows)
    if n_plays == 0:
        return GameClassification(
            game_id=game_id,
            n_plays=0,
            error_home=None,
            error_away=None,
            game_error_magnitude=None,
            pct_enum=0.0,
            pct_delta_only=0.0,
            pct_skipped=0.0,
            posteam_coverage=0.0,
            posteam_display_coverage=0.0,
            posteam_mismatch_rate=0.0,
            n_double_delta=0,
            n_delta_on_skip_play_type=0,
            n_extreme_delta=0,
            n_likely_missed_td=0,
            applied_labels=(),
            dominant_failure_mode=None,
            explanation="No plays in audit.",
            classification_error="no plays in audit",
        )

    n_cov = sum(1 for r in rows if (r.get("posteam_scoring") or "").strip())
    posteam_coverage = n_cov / n_plays
    n_disp = sum(1 for r in rows if (r.get("posteam") or "").strip())
    posteam_display_coverage = n_disp / n_plays
    mismatch_rate = _posteam_mismatch_rate(rows)

    n_enum = n_delta_only = n_skipped = 0
    n_double_delta = n_delta_on_skip = n_extreme = n_missed_td = 0
    for r in rows:
        used = str(r.get("used") or "none")
        if used == "enum":
            n_enum += 1
        elif used == "delta":
            n_delta_only += 1
        else:
            n_skipped += 1

        if bool(r.get("skip_delta")) and str(r.get("used")) == "delta":
            n_delta_on_skip += 1

        dh, da = _parse_board_delta(r)
        if dh is not None and da is not None:
            if dh > 0 and da > 0:
                n_double_delta += 1
            if abs(dh) > 8 or abs(da) > 8:
                n_extreme += 1

            one_sided_td = (
                (dh > 0 and da == 0 and dh in (6, 7, 8))
                or (da > 0 and dh == 0 and da in (6, 7, 8))
            )
            enum_pt = int(r.get("enum_pt") or 0)
            if one_sided_td and enum_pt == 0:
                n_missed_td += 1

    pct_enum = n_enum / n_plays
    pct_delta_only = n_delta_only / n_plays
    pct_skipped = n_skipped / n_plays

    last = rows[-1]
    implied_home = int(last.get("cum_off") or 0)
    implied_away = int(last.get("cum_def") or 0)

    err_h: int | None = None
    err_a: int | None = None
    mag: int | None = None
    if session_home is not None and session_away is not None:
        err_h = implied_home - int(session_home)
        err_a = implied_away - int(session_away)
        mag = abs(err_h) + abs(err_a)

    applied: set[str] = set()
    if posteam_coverage < T_POSTEAM_COVERAGE_MIN:
        applied.add(POSTEAM_MISSING)
    if mismatch_rate > T_POSTEAM_MISMATCH:
        applied.add(POSTEAM_MISALIGNED)
    if pct_delta_only > T_DELTA_LAG_FRAC:
        applied.add(DELTA_LAG)
    if n_double_delta >= 1:
        applied.add(DOUBLE_COUNT_DELTA)
    if n_missed_td >= T_ENUM_MISSED_TD_COUNT:
        applied.add(ENUM_MISSED_TD)
    if n_delta_on_skip >= 2 or n_extreme >= 1:
        applied.add(MIXED_FEED_INCONSISTENCY)

    if not applied and mag is not None and mag >= 2:
        applied.add(UNKNOWN)

    applied_sorted = tuple(sorted(applied))

    dom: str | None = None
    if applied_sorted:
        for cand in _DOMINANT_PRIORITY:
            if cand in applied:
                dom = cand
                break

    if dom:
        expl = (
            f"Dominant failure mode is {dom} (game error magnitude {mag if mag is not None else 'n/a'})."
        )
    elif applied_sorted:
        expl = f"Failure signals: {', '.join(applied_sorted)}."
    elif mag is not None and mag == 0:
        expl = "Implied score matches session board; no failure heuristics triggered."
    else:
        expl = "Structural signals only; session score unavailable for residual error check."

    return GameClassification(
        game_id=game_id,
        n_plays=n_plays,
        error_home=err_h,
        error_away=err_a,
        game_error_magnitude=mag,
        pct_enum=pct_enum,
        pct_delta_only=pct_delta_only,
        pct_skipped=pct_skipped,
        posteam_coverage=posteam_coverage,
        posteam_display_coverage=posteam_display_coverage,
        posteam_mismatch_rate=mismatch_rate,
        n_double_delta=n_double_delta,
        n_delta_on_skip_play_type=n_delta_on_skip,
        n_extreme_delta=n_extreme,
        n_likely_missed_td=n_missed_td,
        applied_labels=applied_sorted,
        dominant_failure_mode=dom,
        explanation=expl,
        classification_error=None,
    )


def per_play_row_dicts_from_game(game: Game) -> list[dict[str, Any]]:
    """Build per-play dicts mirroring :func:`_audit_text` / CSV semantics (classification input)."""
    meta = game.session_metadata or {}
    home_team = str(meta.get("warehouse_home_team") or "")
    away_team = str(meta.get("warehouse_away_team") or "")
    rows: list[dict[str, Any]] = []
    prev: Optional[ActualPlayResult] = None
    cum_o = cum_d = 0
    for dr_i, dr in enumerate(game.drives):
        for p in dr.plays:
            e_pts, e_ha = points_for_play(p, home_team=home_team, away_team=away_team)
            skip = _admin_play_skip_delta(p)
            d_pts, d_ha = (0, None) if skip else _scoreboard_delta_ha(p, prev)
            if p.feed_cumulative_home is None or p.feed_cumulative_away is None:
                dh, da = "", ""
            elif prev and prev.feed_cumulative_home is not None and prev.feed_cumulative_away is not None:
                dh = int(p.feed_cumulative_home) - int(prev.feed_cumulative_home)
                da = int(p.feed_cumulative_away) - int(prev.feed_cumulative_away)
            else:
                dh, da = int(p.feed_cumulative_home), int(p.feed_cumulative_away)
            a_off, a_def, raw_pts, src, _s_ha = warehouse_session_points_for_play(
                p, prev, game, home_team=home_team, away_team=away_team
            )
            cum_o += a_off
            cum_d += a_def
            pos = str(
                (getattr(p, "display_possession_team_abbr", None) or p.feed_possession_team_abbr)
                or ""
            ).strip()
            pos_scoring = str(p.feed_possession_team_abbr or "").strip()
            join = _possession_join(pos, home_team=home_team, away_team=away_team) if home_team and away_team else "?"
            rows.append(
                {
                    "drive_index": dr_i,
                    "posteam": pos,
                    "posteam_scoring": pos_scoring,
                    "posteam_join": join,
                    "wtype": (p.feed_warehouse_play_type or "").strip(),
                    "enum_pt": int(e_pts),
                    "skip_delta": skip,
                    "d_home": dh,
                    "d_away": da,
                    "used": src,
                    "td_flag": bool(p.touchdown),
                    "cum_off": cum_o,
                    "cum_def": cum_d,
                }
            )
            prev = p
    return rows


def _audit_text(game: Game, *, out: TextIO) -> None:
    meta = game.session_metadata or {}
    home_team = str(meta.get("warehouse_home_team") or "")
    away_team = str(meta.get("warehouse_away_team") or "")
    uacc = UnattributableScoreAccumulator()
    io_implied, id_implied, _bd = implied_totals_and_breakdown_from_warehouse_plays(
        game, unattributable=uacc
    )
    bo, bd = int(game.offense_points), int(game.defense_points)
    out.write(
        f"session_board (offense/home, defense/away): {bo}–{bd}  |  implied: {io_implied}–{id_implied}  |  "
        f"per-team gap: {io_implied - bo:+d} (off), {id_implied - bd:+d} (def)\n"
    )
    if uacc.n_unattributable_scores:
        out.write(
            f"unattributable scoring plays (feed posteam/defteam missing): {uacc.n_unattributable_scores}  "
            f"by reason {dict(uacc.unattributable_by_reason)}\n"
        )
    out.write(
        f"teams: home={home_team!r} away={away_team!r}  warehouse_processed={meta.get('warehouse_processed')!r}\n"
    )
    out.write("—\n")

    rows: list[list[Any]] = []
    prev: Optional[ActualPlayResult] = None
    cum_o = cum_d = 0
    for dr in game.drives:
        for p in dr.plays:
            e_pts, e_ha = points_for_play(p, home_team=home_team, away_team=away_team)
            skip = _admin_play_skip_delta(p)
            d_pts, d_ha = (0, None) if skip else _scoreboard_delta_ha(p, prev)
            if p.feed_cumulative_home is None or p.feed_cumulative_away is None:
                dh, da = "", ""
            elif prev and prev.feed_cumulative_home is not None and prev.feed_cumulative_away is not None:
                dh = int(p.feed_cumulative_home) - int(prev.feed_cumulative_home)
                da = int(p.feed_cumulative_away) - int(prev.feed_cumulative_away)
            else:
                dh, da = int(p.feed_cumulative_home), int(p.feed_cumulative_away)
            a_off, a_def, raw_pts, src, _s_ha = warehouse_session_points_for_play(
                p, prev, game, home_team=home_team, away_team=away_team
            )
            cum_o += a_off
            cum_d += a_def
            pos = str(
                (getattr(p, "display_possession_team_abbr", None) or p.feed_possession_team_abbr)
                or ""
            ).strip()
            join = _possession_join(pos, home_team=home_team, away_team=away_team) if home_team and away_team else "?"
            wt = (p.feed_warehouse_play_type or "")[:12]
            wr = (p.feed_warehouse_play_result or "")[:14]
            ex = (p.external_play_id or "")[:20]
            rows.append(
                [
                    len(rows) + 1,
                    ex,
                    pos or "",
                    join,
                    "Y" if p.touchdown else "",
                    wt,
                    wr,
                    e_pts,
                    "" if e_ha is None else e_ha[:1],
                    "Y" if skip else "",
                    d_pts,
                    "" if d_ha is None else d_ha[:1],
                    dh,
                    da,
                    src,
                    a_off,
                    a_def,
                    raw_pts,
                    cum_o,
                    cum_d,
                ]
            )
            prev = p

    headers = [
        "i",
        "ext_play",
        "posteam",
        "posteam_join",
        "td",
        "wtype",
        "wresult",
        "enum_pt",
        "e_ha",
        "skip_Δ",
        "Δpt",
        "Δha",
        "d_home",
        "d_away",
        "used",
        "+off",
        "+def",
        "raw",
        "cum_off",
        "cum_def",
    ]
    w = [len(str(h)) for h in headers]
    for r in rows:
        for j, c in enumerate(r):
            w[j] = max(w[j], len(str(c)))

    def fmt(i: int, c: Any) -> str:
        s = str(c)
        if i == 0:
            return s.rjust(w[i])
        return s.ljust(w[i])

    for line in [
        " ".join(fmt(i, h) for i, h in enumerate(headers)),
        " ".join("-" * w[i] for i in range(len(headers))),
    ]:
        out.write(line + "\n")
    for r in rows:
        out.write(" ".join(fmt(i, c) for i, c in enumerate(r)) + "\n")


def _audit_csv(game: Game, *, out: TextIO) -> None:
    meta = game.session_metadata or {}
    home_team = str(meta.get("warehouse_home_team") or "")
    away_team = str(meta.get("warehouse_away_team") or "")
    uacc = UnattributableScoreAccumulator()
    io_implied, id_implied, _bd = implied_totals_and_breakdown_from_warehouse_plays(
        game, unattributable=uacc
    )
    bo, bd = int(game.offense_points), int(game.defense_points)
    w = csv.writer(out, lineterminator="\n")
    w.writerow(
        [
            "session_offense",
            "session_defense",
            "implied_offense",
            "implied_defense",
            "gap_off",
            "gap_def",
        ]
    )
    w.writerow(
        [bo, bd, io_implied, id_implied, io_implied - bo, id_implied - bd]
    )
    w.writerow(
        [
            "unattributable_scoring_plays",
            uacc.n_unattributable_scores,
        ]
    )
    w.writerow([])
    w.writerow(
        [
            "i",
            "external_play_id",
            "posteam",
            "posteam_join",
            "touchdown",
            "warehouse_play_type",
            "warehouse_play_result",
            "enum_points",
            "enum_side_ha",
            "admin_skip_delta",
            "delta_points",
            "delta_side_ha",
            "raw_d_home",
            "raw_d_away",
            "source_used",
            "add_offense",
            "add_defense",
            "raw_points_on_play",
            "cum_implied_offense",
            "cum_implied_defense",
        ]
    )
    prev: Optional[ActualPlayResult] = None
    cum_o = cum_d = 0
    i = 0
    for dr in game.drives:
        for p in dr.plays:
            i += 1
            e_pts, e_ha = points_for_play(p, home_team=home_team, away_team=away_team)
            skip = _admin_play_skip_delta(p)
            d_pts, d_ha = (0, None) if skip else _scoreboard_delta_ha(p, prev)
            if p.feed_cumulative_home is None or p.feed_cumulative_away is None:
                dh, da = "", ""
            elif prev and prev.feed_cumulative_home is not None and prev.feed_cumulative_away is not None:
                dh = int(p.feed_cumulative_home) - int(prev.feed_cumulative_home)
                da = int(p.feed_cumulative_away) - int(prev.feed_cumulative_away)
            else:
                dh, da = int(p.feed_cumulative_home), int(p.feed_cumulative_away)
            a_off, a_def, raw_pts, src, _s_ha = warehouse_session_points_for_play(
                p, prev, game, home_team=home_team, away_team=away_team
            )
            cum_o += a_off
            cum_d += a_def
            pos = str(
                (getattr(p, "display_possession_team_abbr", None) or p.feed_possession_team_abbr)
                or ""
            ).strip()
            join = _possession_join(pos, home_team=home_team, away_team=away_team) if home_team and away_team else ""
            w.writerow(
                [
                    i,
                    p.external_play_id or "",
                    pos,
                    join,
                    p.touchdown,
                    p.feed_warehouse_play_type or "",
                    p.feed_warehouse_play_result or "",
                    e_pts,
                    e_ha or "",
                    skip,
                    d_pts,
                    d_ha or "",
                    dh,
                    da,
                    src,
                    a_off,
                    a_def,
                    raw_pts,
                    cum_o,
                    cum_d,
                ]
            )
            prev = p


def _paths_from_batch_file(path: Path) -> list[Path]:
    raw = path.expanduser().read_text(encoding="utf-8", errors="replace").splitlines()
    out: list[Path] = []
    for line in raw:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        out.append(Path(s))
    return out


def _audit_batch(
    paths: list[Path], *, out: TextIO, as_csv: bool, errors_to_stderr: bool
) -> int:
    """One row per file: path, session and implied board, per-team gap."""
    err = 0
    if as_csv:
        w = csv.writer(out, lineterminator="\n")
        w.writerow(
            [
                "path",
                "session_offense",
                "session_defense",
                "implied_offense",
                "implied_defense",
                "gap_off",
                "gap_def",
            ]
        )
    else:
        headers = [
            "path",
            "sess O",
            "sess D",
            "imp O",
            "imp D",
            "gap O",
            "gap D",
        ]
        wnum = [len(h) for h in headers]

    rows_data: list[tuple[str, int, int, int, int, int, int]] = []
    for p in paths:
        ep = p.expanduser()
        try:
            game, _rows = warehouse_bundle_from_processed_path(ep)
        except (OSError, ValueError, KeyError) as e:
            err = 1
            if errors_to_stderr:
                print(f"error: {ep}: {e}", file=sys.stderr)
            continue
        io_im, id_im, _ = implied_totals_and_breakdown_from_warehouse_plays(game)
        bo, bd = int(game.offense_points), int(game.defense_points)
        rows_data.append(
            (str(ep), bo, bd, io_im, id_im, io_im - bo, id_im - bd)
        )

    for tup in rows_data:
        if as_csv:
            w.writerow(tup)  # type: ignore[union-attr]
        else:
            r = [str(c) for c in tup]
            for j, c in enumerate(r):
                wnum[j] = max(wnum[j], len(c))

    if not as_csv:
        line0 = " ".join(h.ljust(wnum[i]) for i, h in enumerate(headers))
        line1 = " ".join("-" * wnum[i] for i in range(len(headers)))
        out.write(line0 + "\n" + line1 + "\n")
        for tup in rows_data:
            r = [str(c) for c in tup]
            out.write(" ".join(r[i].ljust(wnum[i]) for i in range(len(r))) + "\n")

    return err


def expand_summary_paths(paths: Sequence[Path]) -> list[Path]:
    """Expand directories to ``*.json`` files; sort for deterministic runs."""
    found: list[Path] = []
    for p in paths:
        q = p.expanduser()
        if q.is_dir():
            found.extend(q.rglob("*.json"))
        elif q.is_file():
            found.append(q)
    return sorted({p.resolve() for p in found}, key=lambda x: str(x))


def _failed_load_classification(path: Path, exc: BaseException) -> GameClassification:
    return GameClassification(
        game_id=path.stem,
        n_plays=0,
        error_home=None,
        error_away=None,
        game_error_magnitude=None,
        pct_enum=0.0,
        pct_delta_only=0.0,
        pct_skipped=0.0,
        posteam_coverage=0.0,
        posteam_display_coverage=0.0,
        posteam_mismatch_rate=0.0,
        n_double_delta=0,
        n_delta_on_skip_play_type=0,
        n_extreme_delta=0,
        n_likely_missed_td=0,
        applied_labels=(),
        dominant_failure_mode=None,
        explanation="",
        classification_error=f"load failed: {exc}",
    )


def classify_corpus(
    paths: Sequence[Path], *, with_posteam_inference: bool = False
) -> list[GameClassification]:
    """Load each processed JSON, build per-play rows, classify. Load errors become records with ``classification_error``."""
    out: list[GameClassification] = []
    for path in expand_summary_paths(paths):
        try:
            game, _rows = warehouse_bundle_from_processed_path(
                path, with_posteam_inference=with_posteam_inference
            )
        except (OSError, ValueError, KeyError) as e:
            out.append(_failed_load_classification(path, e))
            continue
        rows = per_play_row_dicts_from_game(game)
        gid = str(getattr(game, "game_id", "") or path.stem)
        out.append(
            classify_game(
                rows,
                gid,
                session_home=int(game.offense_points),
                session_away=int(game.defense_points),
            )
        )
    return out


def summarize_classifications(
    classifications: Sequence[GameClassification],
    *,
    root: str,
    top_n: int = 5,
) -> dict[str, Any]:
    """Structured §10.9 summary data (CLI printer and tests)."""
    clist = list(classifications)
    load_failures = sum(1 for c in clist if c.classification_error)

    abs_h = sum(abs(c.error_home) for c in clist if c.error_home is not None)
    abs_a = sum(abs(c.error_away) for c in clist if c.error_away is not None)
    mags = [c.game_error_magnitude for c in clist if c.game_error_magnitude is not None]
    mean_mag = statistics.mean(mags) if mags else 0.0
    median_mag = float(statistics.median(mags)) if mags else 0.0

    applied_counts: dict[str, int] = {k: 0 for k in ALL_FAILURE_LABELS}
    dominant_counts: dict[str, int] = {k: 0 for k in ALL_FAILURE_LABELS}
    dominant_counts["(none)"] = 0

    dom_mags: dict[str, list[int]] = {k: [] for k in ALL_FAILURE_LABELS}
    dom_mags["(none)"] = []

    for c in clist:
        if c.classification_error:
            continue
        for lab in c.applied_labels:
            if lab in applied_counts:
                applied_counts[lab] += 1
        if c.dominant_failure_mode is None:
            dominant_counts["(none)"] += 1
            if c.game_error_magnitude is not None:
                dom_mags["(none)"].append(c.game_error_magnitude)
        else:
            dominant_counts[c.dominant_failure_mode] += 1
            if c.game_error_magnitude is not None:
                dom_mags[c.dominant_failure_mode].append(c.game_error_magnitude)

    ranked = sorted(
        (c for c in clist if not c.classification_error),
        key=lambda c: (
            0 if c.game_error_magnitude is not None else 1,
            -(c.game_error_magnitude or 0),
            c.game_id,
        ),
    )
    top_worst = ranked[:top_n]

    examples: dict[str, str] = {}
    for lab in ALL_FAILURE_LABELS:
        hits = sorted(
            c.game_id for c in clist if lab in c.applied_labels and not c.classification_error
        )
        examples[lab] = hits[0] if hits else ""

    dom_means: dict[str, float] = {}
    for k, vals in dom_mags.items():
        dom_means[k] = statistics.mean(vals) if vals else 0.0

    return {
        "root": root,
        "top_n": top_n,
        "games_analyzed": len(clist),
        "load_failures": load_failures,
        "total_abs_error_home": abs_h,
        "total_abs_error_away": abs_a,
        "mean_game_error_magnitude": mean_mag,
        "median_game_error_magnitude": median_mag,
        "applied_counts": applied_counts,
        "dominant_counts": dominant_counts,
        "top_worst": top_worst,
        "examples_applied": examples,
        "dominant_mean_magnitude": dom_means,
    }


def format_summary_text(data: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("Implied score audit summary")
    lines.append(f"Root: {data['root']}")
    lines.append(
        f"Games analyzed: {data['games_analyzed']} (load failures: {data['load_failures']})"
    )
    lines.append("")
    lines.append("Score error totals")
    lines.append(f"  Total |error_home|: {data['total_abs_error_home']}")
    lines.append(f"  Total |error_away|: {data['total_abs_error_away']}")
    lines.append(f"  Mean game error magnitude: {data['mean_game_error_magnitude']:.2f}")
    lines.append(f"  Median game error magnitude: {data['median_game_error_magnitude']:.2f}")
    lines.append("")
    lines.append("Failure mode counts (a game can apply to multiple)")
    ac = data["applied_counts"]
    for lab in ALL_FAILURE_LABELS:
        lines.append(f"  {lab}: {ac[lab]}")
    lines.append("")
    lines.append("Dominant mode counts (each game counted exactly once)")
    dc = data["dominant_counts"]
    for lab in ALL_FAILURE_LABELS:
        lines.append(f"  {lab} (dominant): {dc[lab]}")
    lines.append(f"  (none): {dc['(none)']}")
    lines.append("")
    tw = data["top_worst"]
    lines.append(
        f"Top {data['top_n']} worst games (by |error_home| + |error_away|)"
    )
    for i, c in enumerate(tw, start=1):
        eh = c.error_home if c.error_home is not None else "?"
        ea = c.error_away if c.error_away is not None else "?"
        dom = c.dominant_failure_mode or "—"
        lines.append(
            f"  {i}. {c.game_id}  err=(home, away)=({eh}, {ea})  dominant={dom}"
        )
    lines.append("")
    lines.append("Example game per failure mode")
    ex = data["examples_applied"]
    for lab in ALL_FAILURE_LABELS:
        g = ex.get(lab, "")
        lines.append(f"  {lab}: {g if g else '(none)'}")
    return "\n".join(lines) + "\n"


def compare_corpus_magnitude_text(
    before: Sequence[GameClassification],
    after: Sequence[GameClassification],
) -> str:
    """§10.7-style delta between two classification runs (same paths order / game_id alignment)."""
    by_after = {c.game_id: c for c in after}
    improved = unchanged = worse = 0
    total_b = 0
    total_a = 0
    worse_list: list[tuple[str, int, int]] = []
    for cb in before:
        if cb.classification_error or cb.game_error_magnitude is None:
            continue
        ca = by_after.get(cb.game_id)
        if ca is None or ca.classification_error or ca.game_error_magnitude is None:
            continue
        mb, ma = int(cb.game_error_magnitude), int(ca.game_error_magnitude)
        total_b += mb
        total_a += ma
        if ma < mb:
            improved += 1
        elif ma == mb:
            unchanged += 1
        else:
            worse += 1
            worse_list.append((cb.game_id, mb, ma))
    n_pair = improved + unchanged + worse
    lines = [
        "Corpus magnitude comparison (paired games, non-load error)",
        f"  Pairs: {n_pair}  |  improved: {improved}  unchanged: {unchanged}  worsened: {worse}",
    ]
    if n_pair and total_b > 0:
        pct = (total_b - total_a) / float(total_b)
        lines.append(
            f"  Total game_error_magnitude: before={total_b}  after={total_a}  improvement_pct={pct * 100.0:.2f}%"
        )
    if worse_list:
        lines.append("  Worsened (game_id, before, after):")
        for gid, mb, ma in sorted(worse_list, key=lambda t: t[0])[:200]:
            lines.append(f"    {gid}  {mb} -> {ma}  (delta {ma - mb:+d})")
    lines.append("")
    return "\n".join(lines) + "\n"


def write_classification_csv(
    classifications: Sequence[GameClassification], path: Path
) -> None:
    """§10.7 CSV (Tier 2). Sorted by game_error_magnitude desc, game_id asc."""
    clist = sorted(
        classifications,
        key=lambda c: (
            0 if c.game_error_magnitude is not None else 1,
            -(c.game_error_magnitude or 0),
            c.game_id,
        ),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(
            [
                "game_id",
                "error_home",
                "error_away",
                "game_error_magnitude",
                "applied_labels (semicolon-separated)",
                "dominant_failure_mode",
                "posteam_coverage",
                "posteam_display_coverage",
                "posteam_mismatch_rate",
                "pct_enum",
                "pct_delta_only",
                "pct_skipped",
                "n_double_delta",
                "n_delta_on_skip_play_type",
                "n_extreme_delta",
                "n_likely_missed_td",
                "n_plays",
            ]
        )
        for c in clist:
            labs = ";".join(c.applied_labels)
            w.writerow(
                [
                    c.game_id,
                    "" if c.error_home is None else c.error_home,
                    "" if c.error_away is None else c.error_away,
                    "" if c.game_error_magnitude is None else c.game_error_magnitude,
                    labs,
                    c.dominant_failure_mode or "",
                    f"{c.posteam_coverage:.6f}",
                    f"{c.posteam_display_coverage:.6f}",
                    f"{c.posteam_mismatch_rate:.6f}",
                    f"{c.pct_enum:.6f}",
                    f"{c.pct_delta_only:.6f}",
                    f"{c.pct_skipped:.6f}",
                    c.n_double_delta,
                    c.n_delta_on_skip_play_type,
                    c.n_extreme_delta,
                    c.n_likely_missed_td,
                    c.n_plays,
                ]
            )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Audit per-play implied scoring vs session board for processed warehouse JSON."
    )
    p.add_argument(
        "json_path",
        type=Path,
        nargs="*",
        help="Path(s) to processed game JSON (under data/processed/…). "
        "Multiple paths: summary table only. Use with --batch instead of a long shell list.",
    )
    p.add_argument(
        "--batch",
        type=Path,
        metavar="FILE",
        default=None,
        help="File with one JSON path per line (# comments and blank lines ok).",
    )
    p.add_argument(
        "--csv",
        action="store_true",
        help="For a single file: per-play CSV. For two or more files: one summary row per file.",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Write to this file instead of stdout.",
    )
    p.add_argument(
        "--summary",
        action="store_true",
        help="Classify failure modes across file(s) or directories; prints aggregate summary only (no per-play table).",
    )
    p.add_argument(
        "--classification-csv",
        type=Path,
        default=None,
        metavar="PATH",
        help="With --summary, write per-game classification CSV (§10.7). Requires --summary.",
    )
    p.add_argument(
        "--top",
        type=int,
        default=5,
        metavar="N",
        help="With --summary, number of worst games to list (default 5).",
    )
    p.add_argument(
        "--with-inference",
        action="store_true",
        help="With --summary, load plays with posteam gap-fill (warehouse.posteam_inference) before classifying. Default: off.",
    )
    p.add_argument(
        "--inference-compare",
        action="store_true",
        help="With --summary, run baseline vs with-inference and print before/after plus magnitude deltas. Implies two passes over the corpus.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.batch is not None and args.json_path:
        print("error: use either --batch or positional paths, not both", file=sys.stderr)
        return 1

    if args.classification_csv is not None and not args.summary:
        print("error: --classification-csv requires --summary", file=sys.stderr)
        return 1

    if args.inference_compare and not args.summary:
        print("error: --inference-compare requires --summary", file=sys.stderr)
        return 1

    if args.with_inference and args.inference_compare:
        print(
            "error: use --inference-compare alone for A/B (it includes inference); "
            "do not combine with --with-inference",
            file=sys.stderr,
        )
        return 1

    if args.batch is not None:
        paths = _paths_from_batch_file(args.batch)
    elif args.json_path:
        paths = [p.expanduser() for p in args.json_path]
    else:
        print("error: pass at least one json_path or --batch FILE", file=sys.stderr)
        return 1

    if len(paths) == 0:
        print("error: --batch file produced no paths", file=sys.stderr)
        return 1

    if args.summary and args.csv:
        print(
            "error: --csv (per-play / batch export) cannot be combined with --summary; "
            "use --classification-csv for summary export",
            file=sys.stderr,
        )
        return 1

    sink: TextIO
    f_out = None
    if args.output is not None:
        f_out = args.output.open("w", encoding="utf-8", newline="")
        sink = f_out
    else:
        sink = sys.stdout

    exit_c = 0
    try:
        if args.summary:
            root_display = str(paths[0].expanduser())
            if args.inference_compare:
                base = classify_corpus(paths, with_posteam_inference=False)
                aug = classify_corpus(paths, with_posteam_inference=True)
                sb = summarize_classifications(
                    base, root=root_display, top_n=int(args.top)
                )
                sa = summarize_classifications(
                    aug, root=root_display, top_n=int(args.top)
                )
                sink.write("=== Baseline (no posteam inference) ===\n\n")
                sink.write(format_summary_text(sb))
                sink.write("\n=== With posteam inference ===\n\n")
                sink.write(format_summary_text(sa))
                sink.write(compare_corpus_magnitude_text(base, aug))
                if args.classification_csv is not None:
                    try:
                        write_classification_csv(aug, args.classification_csv)
                    except OSError as e:
                        print(
                            f"error: could not write classification CSV: {e}",
                            file=sys.stderr,
                        )
                        exit_c = 1
                if sb["load_failures"] or sa["load_failures"]:
                    exit_c = 1
            else:
                classifications = classify_corpus(
                    paths, with_posteam_inference=bool(args.with_inference)
                )
                summary = summarize_classifications(
                    classifications, root=root_display, top_n=int(args.top)
                )
                sink.write(format_summary_text(summary))
                if args.classification_csv is not None:
                    try:
                        write_classification_csv(
                            classifications, args.classification_csv
                        )
                    except OSError as e:
                        print(
                            f"error: could not write classification CSV: {e}",
                            file=sys.stderr,
                        )
                        exit_c = 1
                if summary["load_failures"]:
                    exit_c = 1
        elif len(paths) > 1:
            if args.csv:
                exit_c = _audit_batch(
                    paths, out=sink, as_csv=True, errors_to_stderr=True
                )
            else:
                exit_c = _audit_batch(
                    paths, out=sink, as_csv=False, errors_to_stderr=True
                )
        else:
            path = paths[0]
            try:
                game, _rows = warehouse_bundle_from_processed_path(path)
            except (OSError, ValueError, KeyError) as e:
                print(f"error: {e}", file=sys.stderr)
                return 1
            if args.csv:
                _audit_csv(game, out=sink)
            else:
                _audit_text(game, out=sink)
    finally:
        if f_out is not None:
            f_out.close()
    return exit_c


if __name__ == "__main__":
    raise SystemExit(main())
