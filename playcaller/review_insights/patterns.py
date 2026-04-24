"""Cross-drive tendency detection for Review Session (deterministic)."""

from __future__ import annotations

from typing import List, Optional, Sequence, Set, Tuple

from playcaller.game import DRIVE_END_PUNT, Drive, Game
from playcaller.review.unified_review import UnifiedReviewRow
from playcaller.review_insights.models import Pattern
from playcaller.review_insights.situational import (
    _down_dist,
    _is_backed_up_pre,
    _is_red_zone_pre,
    yards_for_row,
)
from playcaller.review_insights.thresholds import (
    BACKED_UP_MAX_OWN_YARDLINE,
    FIRST_AND_TEN_MAX_DISTANCE,
    FIRST_AND_TEN_MIN_DISTANCE,
    MIN_PLAYS_PATTERN,
    MIN_RED_ZONE_ATTEMPTS,
    SECOND_LONG_MIN_DISTANCE,
    SECOND_MEDIUM_MAX,
    SECOND_MEDIUM_MIN,
    SKEW_HIGH,
    SKEW_LOW,
)


def _run_pass(row: UnifiedReviewRow) -> Optional[str]:
    v = row.actual_structured.get("run_pass")
    if v in ("Run", "Pass"):
        return str(v)
    return None


def _is_distinctive_run_rate(run_share: float) -> bool:
    return run_share >= SKEW_HIGH or run_share <= SKEW_LOW


def _is_distinctive_pass_rate(pass_share: float) -> bool:
    return pass_share >= SKEW_HIGH or pass_share <= SKEW_LOW


def _fmt_pct(x: float) -> str:
    return f"{int(round(100 * x))}%"


def _third_long_pass_depth_line(rows: List[UnifiedReviewRow], indices: List[int]) -> Optional[Pattern]:
    """3rd & long (7+): pass depth mix on pass attempts only."""
    bucketed: List[Tuple[str, int]] = []
    for i in indices:
        row = rows[i]
        pre = row.pre_snap
        d, dist = _down_dist(pre)
        if d != 3 or dist is None or dist < SECOND_LONG_MIN_DISTANCE:
            continue
        if _run_pass(row) != "Pass":
            continue
        sb = str(row.actual_structured.get("summary_bucket") or row.actual_structured.get("actual_bucket") or "").lower()
        if "deep" in sb:
            bucketed.append(("deep", i))
        elif "medium" in sb or "dropback" in sb:
            bucketed.append(("intermediate", i))
        else:
            bucketed.append(("short", i))
    if len(bucketed) < MIN_PLAYS_PATTERN:
        return None
    deep = sum(1 for b, _ in bucketed if b == "deep")
    inter = sum(1 for b, _ in bucketed if b == "intermediate")
    short = sum(1 for b, _ in bucketed if b == "short")
    sup = tuple(i for _, i in bucketed)
    parts = []
    if deep:
        parts.append(f"{deep} deep")
    if inter:
        parts.append(f"{inter} intermediate")
    if short:
        parts.append(f"{short} short")
    conv_n = 0
    for i in indices:
        r = rows[i]
        d, dist = _down_dist(r.pre_snap)
        if d != 3 or (dist or 0) < SECOND_LONG_MIN_DISTANCE:
            continue
        rt = str(r.actual_structured.get("result_type") or "").lower()
        if "touchdown" in rt or rt == "first_down" or ("first" in rt and "down" in rt):
            conv_n += 1
    summary = (
        f"3rd & long: {len(bucketed)} pass attempts — "
        + ", ".join(parts)
        + f" — {conv_n} conversion(s)"
    )
    return Pattern(
        category="third_down",
        title="3rd & long pass depth",
        summary=summary,
        support_plays=sup,
        significance=72,
    )


def detect_patterns(
    our_offense_rows: Sequence[UnifiedReviewRow],
    game: Game,
) -> List[Pattern]:
    """
    Surface aggregate tendencies for the coached offense.

    ``our_offense_rows`` should already be filtered to offensive possessions for the coached team.
    """
    rows = list(our_offense_rows)
    out: List[Pattern] = []
    if len(rows) < MIN_PLAYS_PATTERN:
        return out

    n_all = len(rows)
    all_idx = list(range(n_all))

    # --- Overall run/pass ---
    rp_all = [i for i in all_idx if _run_pass(rows[i]) in ("Run", "Pass")]
    if len(rp_all) >= MIN_PLAYS_PATTERN:
        runs = sum(1 for i in rp_all if _run_pass(rows[i]) == "Run")
        run_share = runs / len(rp_all)
        if _is_distinctive_run_rate(run_share):
            passes = len(rp_all) - runs
            out.append(
                Pattern(
                    category="run_pass",
                    title="Overall run/pass",
                    summary=(
                        f"Overall: {_fmt_pct(run_share)} run ({runs} rushes, {passes} passes) "
                        f"on {len(rp_all)} tagged snaps"
                    ),
                    support_plays=tuple(rp_all),
                    significance=60,
                )
            )

    # --- By down (1–3) ---
    for dn in (1, 2, 3):
        idx = [i for i in all_idx if _down_dist(rows[i].pre_snap)[0] == dn]
        rp = [i for i in idx if _run_pass(rows[i]) in ("Run", "Pass")]
        if len(rp) < MIN_PLAYS_PATTERN:
            continue
        runs = sum(1 for i in rp if _run_pass(rows[i]) == "Run")
        run_share = runs / len(rp)
        if _is_distinctive_run_rate(run_share):
            passes = len(rp) - runs
            out.append(
                Pattern(
                    category="run_pass",
                    title=f"{dn}{_ordinal_suffix(dn)} down run rate",
                    summary=(
                        f"{dn}{_ordinal_suffix(dn)} down: {_fmt_pct(run_share)} run "
                        f"({runs} rushes, {passes} passes)"
                    ),
                    support_plays=tuple(rp),
                    significance=58,
                )
            )

    # --- By quarter ---
    for q in (1, 2, 3, 4):
        idx = [i for i in all_idx if rows[i].pre_snap.get("quarter") == q]
        rp = [i for i in idx if _run_pass(rows[i]) in ("Run", "Pass")]
        if len(rp) < MIN_PLAYS_PATTERN:
            continue
        runs = sum(1 for i in rp if _run_pass(rows[i]) == "Run")
        run_share = runs / len(rp)
        if _is_distinctive_run_rate(run_share):
            passes = len(rp) - runs
            out.append(
                Pattern(
                    category="run_pass",
                    title=f"Q{q} run/pass",
                    summary=f"Q{q}: {_fmt_pct(run_share)} run ({runs} rushes, {passes} passes)",
                    support_plays=tuple(rp),
                    significance=55,
                )
            )

    # --- First & ten tendencies ---
    first_ten_idx = [
        i
        for i in all_idx
        if _down_dist(rows[i].pre_snap)[0] == 1
        and _down_dist(rows[i].pre_snap)[1] is not None
        and FIRST_AND_TEN_MIN_DISTANCE <= int(_down_dist(rows[i].pre_snap)[1] or 0) <= FIRST_AND_TEN_MAX_DISTANCE
    ]
    rp_ft = [i for i in first_ten_idx if _run_pass(rows[i]) in ("Run", "Pass")]
    if len(rp_ft) >= MIN_PLAYS_PATTERN:
        runs = sum(1 for i in rp_ft if _run_pass(rows[i]) == "Run")
        run_share = runs / len(rp_ft)
        passes = len(rp_ft) - runs
        yards_list: List[int] = []
        for i in first_ten_idx:
            y = yards_for_row(game, rows[i])
            if y is not None:
                yards_list.append(y)
        yds_avg = sum(yards_list) / len(yards_list) if yards_list else None
        # Next play 2nd & medium after 1st & 10
        medium_after = 0
        first_ten_count = 0
        for i in first_ten_idx:
            first_ten_count += 1
            dr = rows[i].drive_id
            cur_play = rows[i].play_index_on_drive
            nxt = _next_offense_row_same_drive(rows, dr, cur_play)
            if nxt is None:
                continue
            d2, dist2 = _down_dist(nxt.pre_snap)
            if d2 == 2 and dist2 is not None and SECOND_MEDIUM_MIN <= dist2 <= SECOND_MEDIUM_MAX:
                medium_after += 1
        med_rate = (medium_after / first_ten_count) if first_ten_count else None
        parts = [
            f"1st & 10: {_fmt_pct(run_share)} run ({runs} rushes, {passes} passes)",
        ]
        if yds_avg is not None:
            parts.append(f"{yds_avg:.1f} yd/play avg")
        if med_rate is not None:
            parts.append(f"{_fmt_pct(med_rate)} of 1st & 10 snaps led to 2nd & medium (4–7)")
        if _is_distinctive_run_rate(run_share):
            out.append(
                Pattern(
                    category="first_down",
                    title="1st & 10",
                    summary=" — ".join(parts),
                    support_plays=tuple(first_ten_idx),
                    significance=62,
                )
            )

    # --- Third down family ---
    third_idx = [i for i in all_idx if _down_dist(rows[i].pre_snap)[0] == 3]
    if len(third_idx) >= MIN_PLAYS_PATTERN:
        conv = 0
        for i in third_idx:
            rt = str(rows[i].actual_structured.get("result_type") or "").lower()
            if "touchdown" in rt or rt == "first_down" or ("first" in rt and "down" in rt):
                conv += 1
        rp3 = [i for i in third_idx if _run_pass(rows[i]) in ("Run", "Pass")]
        if rp3:
            runs = sum(1 for i in rp3 if _run_pass(rows[i]) == "Run")
            passes = len(rp3) - runs
            summary = (
                f"3rd down: {_fmt_pct(conv / len(third_idx))} conversion ({conv}/{len(third_idx)}); "
                f"run/pass {runs}/{passes}"
            )
        else:
            summary = f"3rd down: {_fmt_pct(conv / len(third_idx))} conversion ({conv}/{len(third_idx)})"
        out.append(
            Pattern(
                category="third_down",
                title="3rd down overview",
                summary=summary,
                support_plays=tuple(third_idx),
                significance=70,
            )
        )

    # --- 3rd short / medium / long ---
    for label, lo, hi in (
        ("short (1–3)", 1, 3),
        ("medium (4–6)", 4, 6),
        ("long (7+)", 7, 99),
    ):
        idx = [
            i
            for i in third_idx
            if (d := _down_dist(rows[i].pre_snap)[1]) is not None and lo <= d <= hi
        ]
        if len(idx) < MIN_PLAYS_PATTERN:
            continue
        rp = [i for i in idx if _run_pass(rows[i]) in ("Run", "Pass")]
        if not rp:
            continue
        runs = sum(1 for i in rp if _run_pass(rows[i]) == "Run")
        conv = sum(
            1
            for i in idx
            if "touchdown" in str(rows[i].actual_structured.get("result_type") or "").lower()
            or str(rows[i].actual_structured.get("result_type") or "").lower() == "first_down"
            or "first" in str(rows[i].actual_structured.get("result_type") or "").lower()
        )
        passes = len(rp) - runs
        run_share = runs / len(rp)
        out.append(
            Pattern(
                category="third_down",
                title=f"3rd & {label}",
                summary=(
                    f"3rd & {label}: {_fmt_pct(conv / len(idx))} conv ({conv}/{len(idx)}); "
                    f"{_fmt_pct(run_share)} run ({runs}/{len(rp)} run/pass tagged)"
                ),
                support_plays=tuple(idx),
                significance=68,
            )
        )

    dep = _third_long_pass_depth_line(rows, all_idx)
    if dep is not None:
        out.append(dep)

    # --- Red zone ---
    rz_idx = [i for i in all_idx if _is_red_zone_pre(rows[i].pre_snap)]
    if len(rz_idx) >= MIN_RED_ZONE_ATTEMPTS:
        tds = sum(
            1
            for i in rz_idx
            if "touchdown" in str(rows[i].actual_structured.get("result_type") or "").lower()
        )
        rp_rz = [i for i in rz_idx if _run_pass(rows[i]) in ("Run", "Pass")]
        runs = sum(1 for i in rp_rz if _run_pass(rows[i]) == "Run") if rp_rz else 0
        passes = len(rp_rz) - runs
        td_rate = tds / len(rz_idx)
        rz_line = (
            f"Red zone: {len(rz_idx)} snaps, {_fmt_pct(td_rate)} TD ({tds}/{len(rz_idx)})"
        )
        if rp_rz:
            rz_line += f" — ran on {runs} of {len(rp_rz)} RZ tagged snaps"
        g2g_rate_line = _goal_to_go_line(game, rows, all_idx)
        if g2g_rate_line:
            rz_line += f" — {g2g_rate_line}"
        out.append(
            Pattern(
                category="red_zone",
                title="Red zone",
                summary=rz_line,
                support_plays=tuple(rz_idx),
                significance=74,
            )
        )

    # --- Backed up ---
    bu_idx = [i for i in all_idx if _is_backed_up_pre(rows[i].pre_snap)]
    if len(bu_idx) >= MIN_PLAYS_PATTERN:
        yds = [y for i in bu_idx if (y := yards_for_row(game, rows[i])) is not None]
        net = sum(yds) if yds else 0
        three_out = _three_and_out_rate_backed_up(game, rows, bu_idx)
        parts = [f"Backed up (own 1–10): {len(bu_idx)} snaps", f"{net} yds gained"]
        if three_out is not None:
            parts.append(three_out)
        out.append(
            Pattern(
                category="backed_up",
                title="Backed up",
                summary=" — ".join(parts),
                support_plays=tuple(bu_idx),
                significance=64,
            )
        )

    # --- Quarter pass shift vs overall (momentum narrative) ---
    overall_pass = None
    if len(rp_all) >= MIN_PLAYS_PATTERN:
        overall_pass = sum(1 for i in rp_all if _run_pass(rows[i]) == "Pass") / len(rp_all)
    if overall_pass is not None:
        for q in (2, 3, 4):
            idx = [i for i in all_idx if rows[i].pre_snap.get("quarter") == q]
            rpq = [i for i in idx if _run_pass(rows[i]) in ("Run", "Pass")]
            if len(rpq) < MIN_PLAYS_PATTERN:
                continue
            pq_share = sum(1 for i in rpq if _run_pass(rows[i]) == "Pass") / len(rpq)
            if abs(pq_share - overall_pass) >= 0.20 and _is_distinctive_pass_rate(pq_share):
                out.append(
                    Pattern(
                        category="momentum",
                        title=f"Q{q} pass rate shift",
                        summary=(
                            f"Q{q}: shifted to {_fmt_pct(pq_share)} pass "
                            f"(vs {_fmt_pct(overall_pass)} overall)"
                        ),
                        support_plays=tuple(rpq),
                        significance=52,
                    )
                )

    out.sort(key=lambda p: (-p.significance, p.title))
    return out


def related_drive_indices_for_pattern(
    pattern: Pattern,
    our_offense_rows: Sequence[UnifiedReviewRow],
) -> Tuple[int, ...]:
    """
    Map ``pattern.support_plays`` (indices into ``our_offense_rows``) to distinct drive ids.

    Indices are 0-based into ``Game.drives``, same as ``GameStoryBullet.related_drive_indices``.
    """
    rows = list(our_offense_rows)
    n = len(rows)
    found: Set[int] = set()
    for i in pattern.support_plays:
        if not isinstance(i, int) or i < 0 or i >= n:
            continue
        found.add(rows[i].drive_id)
    return tuple(sorted(found))


def _ordinal_suffix(n: int) -> str:
    if n == 1:
        return "st"
    if n == 2:
        return "nd"
    if n == 3:
        return "rd"
    return "th"


def _next_offense_row_same_drive(
    rows: List[UnifiedReviewRow],
    drive_id: int,
    play_index_on_drive: int,
) -> Optional[UnifiedReviewRow]:
    cands = [r for r in rows if r.drive_id == drive_id and r.play_index_on_drive > play_index_on_drive]
    if not cands:
        return None
    return min(cands, key=lambda r: r.play_index_on_drive)


def _goal_to_go_line(game: Game, rows: List[UnifiedReviewRow], all_idx: List[int]) -> str:
    """TDs / goal-to-go snaps (inferred presnap)."""
    g2g_idx: List[int] = []
    for i in all_idx:
        pre = rows[i].pre_snap
        if str(pre.get("territory")) != "opponents":
            continue
        try:
            yl = int(pre.get("yardline", 99))
            dist = int(pre.get("distance") or 99)
        except (TypeError, ValueError):
            continue
        if 1 <= yl <= 10 and dist >= yl:
            g2g_idx.append(i)
    if len(g2g_idx) < MIN_PLAYS_PATTERN:
        return ""
    tds = sum(
        1
        for i in g2g_idx
        if "touchdown" in str(rows[i].actual_structured.get("result_type") or "").lower()
    )
    return f"goal-to-go: {_fmt_pct(tds / len(g2g_idx))} TD ({tds}/{len(g2g_idx)} G2G snaps)"


def _three_and_out_rate_backed_up(
    game: Game,
    rows: List[UnifiedReviewRow],
    bu_idx: List[int],
) -> Optional[str]:
    """Drives that include backed-up context: 3-and-out rate."""
    drives: Set[int] = set(rows[i].drive_id for i in bu_idx)
    three_out = 0
    eligible = 0
    for d in drives:
        if d < 0 or d >= len(game.drives):
            continue
        dr: Drive = game.drives[d]
        plays = dr.plays or []
        if not plays:
            continue
        # Drive started inside own 10?
        fa = plays[0]
        if str(fa.feed_presnap_territory) != "own":
            continue
        try:
            yl = int(fa.feed_presnap_yardline or 99)
        except (TypeError, ValueError):
            continue
        if yl > BACKED_UP_MAX_OWN_YARDLINE:
            continue
        eligible += 1
        res = dr.result
        if len(plays) <= 3 and res is not None and str(res.kind) == DRIVE_END_PUNT:
            three_out += 1
    if eligible < 1:
        return None
    return f"3-and-out {three_out}/{eligible} on drives starting inside own 10"
