from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from warehouse.models import Game, Play
from warehouse.taxonomy import PlayResult, PlayType
from warehouse.validation import (
    _declares_scoring_event,
    _pat_one_point_tolerance,
    admin_play_missing_score_context,
    canonical_home_away_scores,
)


@dataclass(kw_only=True, slots=True)
class QualityIssue:
    game_id: str
    play_id: str | None
    rule: str
    detail: str


def _total_points(p: Play) -> int:
    return int(p.score_offense) + int(p.score_defense)


def _explains_possession_change(prev: Play, curr: Play) -> bool:
    if curr.play_type == PlayType.KICKOFF:
        return True
    if prev.play_type in (PlayType.EXTRA_POINT, PlayType.TWO_POINT):
        return True
    if "two-point conversion" in (prev.raw_description or "").lower():
        return True
    if (
        prev.down == 4
        and not prev.first_down
        and prev.play_type in (PlayType.PASS, PlayType.RUN, PlayType.SACK, PlayType.SCRAMBLE)
    ):
        return True
    if prev.play_type in (PlayType.PUNT, PlayType.KICKOFF):
        return True
    if prev.turnover:
        return True
    if prev.play_result in (PlayResult.INTERCEPTION, PlayResult.FUMBLE_LOST):
        return True
    if prev.touchdown:
        return True
    if prev.play_type == PlayType.FIELD_GOAL:
        return True
    if prev.play_result == PlayResult.SAFETY:
        return True
    d = (prev.raw_description or "").upper()
    if "END OF" in d and ("QUARTER" in d or "HALF" in d):
        return True
    if "END OF GAME" in d:
        return True
    if "turnover on downs" in (prev.raw_description or "").lower():
        return True
    return False


_SCRIMMAGE_TYPES = frozenset(
    {PlayType.RUN, PlayType.PASS, PlayType.SACK, PlayType.SCRAMBLE}
)


def check_quality(game: Game, plays: list[Play]) -> list[QualityIssue]:
    gid = game.id
    out: list[QualityIssue] = []

    seq_counts = Counter(p.play_sequence for p in plays)
    dup_seqs = {s for s, c in seq_counts.items() if c > 1}
    for p in plays:
        if p.play_sequence in dup_seqs:
            out.append(
                QualityIssue(
                    game_id=gid,
                    play_id=p.external_play_id,
                    rule="duplicate_play_sequence",
                    detail=f"play_sequence={p.play_sequence} appears {seq_counts[p.play_sequence]} times",
                )
            )

    for p in plays:
        if p.play_type in _SCRIMMAGE_TYPES:
            desc_u = (p.raw_description or "").upper()
            if "TWO-POINT CONVERSION" in desc_u or "TWO POINT CONVERSION" in desc_u:
                continue
            if p.down is None or p.distance is None or p.yardline_100 is None:
                out.append(
                    QualityIssue(
                        game_id=gid,
                        play_id=p.external_play_id,
                        rule="missing_situation",
                        detail=(
                            f"down={p.down} distance={p.distance} "
                            f"yardline_100={p.yardline_100} for play_type={p.play_type.value}"
                        ),
                    )
                )

    for p in plays:
        y = p.yardline_100
        if y is not None and not (0 <= y <= 100):
            out.append(
                QualityIssue(
                    game_id=gid,
                    play_id=p.external_play_id,
                    rule="yardline_out_of_range",
                    detail=f"yardline_100={y}",
                )
            )

    for prev, curr in zip(plays, plays[1:]):
        if admin_play_missing_score_context(prev) or admin_play_missing_score_context(curr):
            continue
        t0 = _total_points(prev)
        t1 = _total_points(curr)
        if t0 == t1:
            continue
        ha0 = canonical_home_away_scores(prev, game)
        ha1 = canonical_home_away_scores(curr, game)
        if ha0 is not None and ha1 is not None and ha0 == ha1:
            continue
        delta_signed = t1 - t0
        delta = abs(delta_signed)
        if delta <= 8:
            continue
        if _declares_scoring_event(curr):
            continue
        if _declares_scoring_event(prev):
            continue
        if _pat_one_point_tolerance(curr, prev, delta_signed):
            continue
        out.append(
            QualityIssue(
                game_id=gid,
                play_id=curr.external_play_id,
                rule="unexplained_score_jump",
                detail=(
                    f"total points {t0} -> {t1} (|Δ|={delta}) without recognized "
                    f"scoring play on this snap"
                ),
            )
        )

    for prev, curr in zip(plays, plays[1:]):
        a, b = prev.possession_team, curr.possession_team
        if a is None or b is None or a == b:
            continue
        if not _explains_possession_change(prev, curr):
            out.append(
                QualityIssue(
                    game_id=gid,
                    play_id=curr.external_play_id,
                    rule="unexplained_possession_change",
                    detail=f"possession {a} -> {b} after play not tagged as change-of-possession type",
                )
            )

    for p in plays:
        d = p.down
        if d is not None and d not in (1, 2, 3, 4):
            out.append(
                QualityIssue(
                    game_id=gid,
                    play_id=p.external_play_id,
                    rule="impossible_down",
                    detail=f"down={d}",
                )
            )

    for p in plays:
        if p.play_result == PlayResult.INCOMPLETE:
            yg = p.yards_gained
            if yg is not None and yg != 0:
                ru = (p.raw_description or "").upper()
                if any(s in ru for s in ("CHALLENGE", "REPLAY", "OVERTURN", "REVIEWED")):
                    continue
                out.append(
                    QualityIssue(
                        game_id=gid,
                        play_id=p.external_play_id,
                        rule="negative_yards_on_incomplete",
                        detail=f"yards_gained={yg}",
                    )
                )

    return out


def summarize_quality(issues: list[QualityIssue]) -> dict[str, int]:
    return dict(Counter(i.rule for i in issues))
