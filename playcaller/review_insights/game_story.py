"""Deterministic game-level coaching bullets from reconciled session data."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Sequence, Tuple

from playcaller.game import (
    DRIVE_END_FIELD_GOAL,
    DRIVE_END_FIELD_GOAL_MISS,
    DRIVE_END_PUNT,
    DRIVE_END_TOUCHDOWN,
    DRIVE_END_TURNOVER_FUMBLE,
    DRIVE_END_TURNOVER_INT,
    DRIVE_END_TURNOVER_ON_DOWNS,
    Drive,
    Game,
)
from playcaller.live_data.drive_display import classify_drive_team_side
from playcaller.play_event_segment import PlayEventSegment, segment_from_actual
from playcaller.reconciliation.drive_reconciler import ReconciledDrive, reconcile_drive
from playcaller.review.unified_review import UnifiedReviewRow, high_confidence_full_agreement_counts
from playcaller.review_insights.models import GameStoryBullet
from playcaller.review_insights.scoring_weights import (
    GAME_STORY_MAX_BULLET_CHARS,
    GAME_STORY_MIN_DRIVES_FOR_HALF_SPLIT,
    GAME_STORY_MIN_DRIVES_TOTAL,
    GAME_STORY_MIN_EXPLOSIVES_TO_MENTION,
    GAME_STORY_MIN_NEGATIVES_TO_MENTION,
    GAME_STORY_MIN_PLAYS_PER_DOWN_BUCKET,
    GAME_STORY_MIN_RED_ZONE_TRIPS,
    GAME_STORY_MIN_STREAK,
    GAME_STORY_MIN_THIRD_ATTEMPTS,
    GAME_STORY_TOP_BULLETS,
    SIGNIFICANCE_EFFICIENCY_DOWN,
    SIGNIFICANCE_EXPLOSIVE,
    SIGNIFICANCE_HALF_SPLIT,
    SIGNIFICANCE_HIGH_CONF_AGREE,
    SIGNIFICANCE_MODEL_LOW_DRIVE,
    SIGNIFICANCE_NEGATIVE,
    SIGNIFICANCE_RED_ZONE,
    SIGNIFICANCE_SCORING_DROUGHT,
    SIGNIFICANCE_SCORING_RUN,
    SIGNIFICANCE_STREAK_FAIL,
    SIGNIFICANCE_THIRD_DOWN,
    NEGATIVE_PLAY_YARDS_THRESHOLD,
)


def _reconcile_all(game: Game) -> List[ReconciledDrive]:
    out: List[ReconciledDrive] = []
    for dr in game.drives or []:
        out.append(reconcile_drive(dr, espn=dr.feed_audit))
    return out


def _clip(s: str) -> str:
    s = s.strip()
    if len(s) <= GAME_STORY_MAX_BULLET_CHARS:
        return s
    return s[: GAME_STORY_MAX_BULLET_CHARS - 1].rstrip() + "…"


def _scoring_possession(rec: ReconciledDrive) -> bool:
    if rec.possession_points and rec.possession_points > 0:
        return True
    return rec.outcome_kind in (DRIVE_END_TOUCHDOWN, DRIVE_END_FIELD_GOAL)


def _empty_possession(rec: ReconciledDrive) -> bool:
    if rec.espn_coarse_bucket == "END_HALF":
        return False
    if _scoring_possession(rec):
        return False
    return rec.outcome_kind in (
        DRIVE_END_PUNT,
        DRIVE_END_TURNOVER_INT,
        DRIVE_END_TURNOVER_FUMBLE,
        DRIVE_END_TURNOVER_ON_DOWNS,
        DRIVE_END_FIELD_GOAL_MISS,
    ) or (rec.possession_points == 0 and rec.outcome_kind not in (DRIVE_END_TOUCHDOWN, DRIVE_END_FIELD_GOAL))


def _drive_span_label(indices: Tuple[int, ...]) -> str:
    human = tuple(i + 1 for i in indices)
    if len(human) == 1:
        return str(human[0])
    return f"{human[0]}–{human[-1]}"


def _add(
    pool: List[GameStoryBullet],
    *,
    text: str,
    category: str,
    significance: int,
    drives: Tuple[int, ...],
) -> None:
    pool.append(
        GameStoryBullet(
            text=_clip(text),
            category=category,
            significance=significance,
            related_drive_indices=drives,
        )
    )


def _dedupe(pool: List[GameStoryBullet]) -> List[GameStoryBullet]:
    seen: set[Tuple[str, Tuple[int, ...]]] = set()
    texts: set[str] = set()
    out: List[GameStoryBullet] = []
    for b in sorted(pool, key=lambda x: (-x.significance, x.category, x.text)):
        key = (b.category, b.related_drive_indices)
        if key in seen or b.text in texts:
            continue
        seen.add(key)
        texts.add(b.text)
        out.append(b)
    return out


def generate_game_story(
    game: Game,
    unified_rows: Sequence[UnifiedReviewRow],
    *,
    our_coached_espn_id: str = "",
) -> List[GameStoryBullet]:
    """
    Produce the top :data:`GAME_STORY_TOP_BULLETS` bullets (ranked, deterministic).

    Uses reconciled drives only — no re-parse of raw feeds beyond :func:`reconcile_drive`.
    """
    pool: List[GameStoryBullet] = []
    drives: List[Drive] = list(game.drives or [])
    if not drives:
        return []

    recs = _reconcile_all(game)
    n = len(drives)

    # --- Streaks (chronological, both teams) ---
    sch: List[bool] = [_scoring_possession(recs[i]) for i in range(n)]
    i0 = 0
    while i0 < n:
        if not sch[i0]:
            i0 += 1
            continue
        i1 = i0
        while i1 < n and sch[i1]:
            i1 += 1
        if i1 - i0 >= GAME_STORY_MIN_STREAK:
            idxs = tuple(range(i0, i1))
            span = _drive_span_label(idxs)
            _add(
                pool,
                text=f"Scored on {i1 - i0} straight possessions (drives {span})",
                category="scoring",
                significance=SIGNIFICANCE_SCORING_RUN,
                drives=idxs,
            )
        i0 = i1

    emp: List[bool] = [_empty_possession(recs[i]) for i in range(n)]
    j0 = 0
    while j0 < n:
        if not emp[j0]:
            j0 += 1
            continue
        j1 = j0
        while j1 < n and emp[j1]:
            j1 += 1
        if j1 - j0 >= GAME_STORY_MIN_STREAK:
            idxs = tuple(range(j0, j1))
            span = _drive_span_label(idxs)
            _add(
                pool,
                text=f"{j1 - j0} straight empty possessions (drives {span})",
                category="streak",
                significance=SIGNIFICANCE_SCORING_DROUGHT,
                drives=idxs,
            )
        j0 = j1

    # --- Red zone efficiency (trips reaching opp ≤20) ---
    rz_trips: List[Tuple[int, bool]] = []
    for di, dr in enumerate(drives):
        reached = False
        for p in dr.plays or []:
            if segment_from_actual(p) != PlayEventSegment.OFFENSE:
                continue
            terr = (p.feed_presnap_territory or "").strip()
            try:
                yl = int(p.feed_presnap_yardline) if p.feed_presnap_yardline is not None else 99
            except (TypeError, ValueError):
                yl = 99
            if terr == "opponents" and yl <= 20:
                reached = True
        if reached:
            r = recs[di]
            scored = r.outcome_kind in (DRIVE_END_TOUCHDOWN, DRIVE_END_FIELD_GOAL)
            rz_trips.append((di, scored))
    if len(rz_trips) >= GAME_STORY_MIN_RED_ZONE_TRIPS:
        conv = sum(1 for _, ok in rz_trips if ok)
        _add(
            pool,
            text=f"Red zone: {conv}/{len(rz_trips)} trips ended in TD/FG",
            category="efficiency",
            significance=SIGNIFICANCE_RED_ZONE,
            drives=tuple(t[0] for t in rz_trips),
        )

    # --- Half split (scoring rate) ---
    if n >= GAME_STORY_MIN_DRIVES_FOR_HALF_SPLIT:
        h1 = [i for i in range(n) if recs[i].start_quarter > 0 and recs[i].start_quarter <= 2]
        h2 = [i for i in range(n) if recs[i].start_quarter >= 3]
        if len(h1) >= 4 and len(h2) >= 4:
            s1 = sum(1 for i in h1 if _scoring_possession(recs[i])) / len(h1)
            s2 = sum(1 for i in h2 if _scoring_possession(recs[i])) / len(h2)
            if abs(s1 - s2) >= 0.25:
                which = "1H" if s1 > s2 else "2H"
                _add(
                    pool,
                    text=f"More scoring possessions in {which} vs other half",
                    category="momentum",
                    significance=SIGNIFICANCE_HALF_SPLIT,
                    drives=tuple(h1 + h2),
                )

    # --- Our-team efficiency: YPP by down, 3rd downs, explosives, negatives ---
    our_id = str(our_coached_espn_id or "").strip()
    yds_by_down: Dict[int, List[int]] = defaultdict(list)
    third_attempts = 0
    third_conv = 0
    explosives = 0
    negatives = 0
    for dr in drives:
        side = classify_drive_team_side(dr, our_coached_espn_id=our_id)
        if side != "our":
            continue
        for p in dr.plays or []:
            if segment_from_actual(p) != PlayEventSegment.OFFENSE:
                continue
            try:
                d0 = int(p.feed_presnap_down) if p.feed_presnap_down is not None else 0
            except (TypeError, ValueError):
                d0 = 0
            y = int(p.yards_gained or 0)
            if 1 <= d0 <= 3:
                yds_by_down[d0].append(y)
            if d0 == 3:
                third_attempts += 1
                if p.first_down or p.touchdown:
                    third_conv += 1
            if y >= 20:
                explosives += 1
            if p.sack or y <= NEGATIVE_PLAY_YARDS_THRESHOLD:
                negatives += 1

    if n >= GAME_STORY_MIN_DRIVES_TOTAL and third_attempts >= GAME_STORY_MIN_THIRD_ATTEMPTS:
        rate = third_conv / third_attempts
        _add(
            pool,
            text=f"3rd down: {third_conv}/{third_attempts} converted ({int(round(100 * rate))}%)",
            category="efficiency",
            significance=SIGNIFICANCE_THIRD_DOWN,
            drives=tuple(range(n)),
        )

    weak_down = None
    weak_ypp = 99.0
    for d in (1, 2, 3):
        ys = yds_by_down.get(d, [])
        if len(ys) < GAME_STORY_MIN_PLAYS_PER_DOWN_BUCKET:
            continue
        ypp = sum(ys) / len(ys)
        if ypp < weak_ypp:
            weak_ypp = ypp
            weak_down = d
    if weak_down is not None and weak_ypp < 3.5 and n >= GAME_STORY_MIN_DRIVES_TOTAL:
        ord_lbl = {1: "1st", 2: "2nd", 3: "3rd"}.get(weak_down, str(weak_down))
        _add(
            pool,
            text=f"Thin {ord_lbl}-down efficiency (~{weak_ypp:.1f} yd/play)",
            category="efficiency",
            significance=SIGNIFICANCE_EFFICIENCY_DOWN,
            drives=tuple(range(n)),
        )

    if explosives >= GAME_STORY_MIN_EXPLOSIVES_TO_MENTION and n >= GAME_STORY_MIN_DRIVES_TOTAL:
        _add(
            pool,
            text=f"{explosives} explosive gains (20+ yds) on offense",
            category="efficiency",
            significance=SIGNIFICANCE_EXPLOSIVE,
            drives=tuple(range(n)),
        )

    if negatives >= GAME_STORY_MIN_NEGATIVES_TO_MENTION and n >= GAME_STORY_MIN_DRIVES_TOTAL:
        _add(
            pool,
            text=f"{negatives} negative plays (sack / TFL lane)",
            category="efficiency",
            significance=SIGNIFICANCE_NEGATIVE,
            drives=tuple(range(n)),
        )

    # --- Model: lowest-agreement drive (offense rows) ---
    by_drive: Dict[int, List[UnifiedReviewRow]] = defaultdict(list)
    for r in unified_rows:
        if r.event_segment != PlayEventSegment.OFFENSE:
            continue
        by_drive[r.drive_id].append(r)

    worst: Optional[Tuple[float, int]] = None
    for did, grp in by_drive.items():
        usable = [
            r
            for r in grp
            if not r.replay_error
            and r.comparison.run_pass_match is not None
            and r.comparison.summary_bucket_match is not None
        ]
        if len(usable) < 4:
            continue
        agree = sum(
            1
            for r in usable
            if r.comparison.run_pass_match
            and r.comparison.summary_bucket_match
            and (r.comparison.family_match is not False)
        )
        rate = agree / len(usable)
        if rate < 0.45:
            tup = (rate, did)
            if worst is None or tup < worst:
                worst = tup
    if worst is not None:
        _, did = worst
        _add(
            pool,
            text=f"Replay disagreed most on drive {did + 1} (low model match)",
            category="comparison",
            significance=SIGNIFICANCE_MODEL_LOW_DRIVE,
            drives=(did,),
        )

    agree_n, agree_d = high_confidence_full_agreement_counts(unified_rows)
    if agree_d >= 5:
        pct = int(round(100 * agree_n / agree_d))
        _add(
            pool,
            text=f"High-confidence snaps matched model {pct}% ({agree_n}/{agree_d})",
            category="comparison",
            significance=SIGNIFICANCE_HIGH_CONF_AGREE,
            drives=tuple(range(n)),
        )

    ranked = _dedupe(pool)
    ranked.sort(key=lambda b: (-b.significance, b.category, b.related_drive_indices, b.text))
    return ranked[:GAME_STORY_TOP_BULLETS]
