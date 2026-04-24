from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass
from typing import Literal

from warehouse.models import Game, Play
from warehouse.taxonomy import PlayResult, PlayType

logger = logging.getLogger(__name__)

Severity = Literal["info", "warning", "error"]


@dataclass(frozen=True, slots=True, kw_only=True)
class ValidationIssue:
    play_id: str | None
    rule: str
    severity: Severity
    message: str


@dataclass(kw_only=True, slots=True)
class ValidationReport:
    game_id: str
    issues: list[ValidationIssue]

    @property
    def valid(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    @property
    def summary(self) -> dict[str, int]:
        return dict(Counter(i.severity for i in self.issues))


def _append(
    issues: list[ValidationIssue],
    *,
    rule: str,
    severity: Severity,
    message: str,
    play_id: str | None = None,
) -> None:
    issues.append(
        ValidationIssue(
            play_id=play_id,
            rule=rule,
            severity=severity,
            message=message,
        )
    )
    if severity == "warning":
        logger.warning("[%s] %s (play_id=%s)", rule, message, play_id)
    elif severity == "error":
        logger.error("[%s] %s (play_id=%s)", rule, message, play_id)


def _total_points(p: Play) -> int:
    return int(p.score_offense) + int(p.score_defense)


def canonical_home_away_scores(p: Play, game: Game) -> tuple[int, int] | None:
    """Map posteam/defteam columns to fixed (home_score, away_score)."""
    if p.possession_team is None:
        return None
    if p.possession_team == game.home_team:
        return (int(p.score_offense), int(p.score_defense))
    if p.possession_team == game.away_team:
        return (int(p.score_defense), int(p.score_offense))
    return None


def admin_play_missing_score_context(p: Play) -> bool:
    """Timeouts / end-period markers often omit possession; totals are not comparable."""
    if p.possession_team is not None:
        return False
    d = (p.raw_description or "").lower()
    if "timeout" in d:
        return True
    if "game has resumed" in d:
        return True
    if _end_of_half(p):
        return True
    return False


def _declares_scoring_event(p: Play) -> bool:
    if p.touchdown:
        return True
    if p.play_type in (PlayType.EXTRA_POINT, PlayType.TWO_POINT):
        return True
    dl = (p.raw_description or "").lower()
    if "two-point conversion" in dl and "succeeds" in dl:
        return True
    if p.play_result in (
        PlayResult.FIELD_GOAL_MADE,
        PlayResult.EXTRA_POINT_MADE,
        PlayResult.TWO_POINT_GOOD,
        PlayResult.SAFETY,
        PlayResult.TOUCHDOWN_RUN,
        PlayResult.TOUCHDOWN_PASS,
        PlayResult.TOUCHDOWN_RETURN,
        PlayResult.KICKOFF_RETURN_TD,
    ):
        return True
    return False


def _pat_one_point_tolerance(curr: Play, prev: Play, delta: int) -> bool:
    if abs(delta) != 1:
        return False
    if curr.play_type in (PlayType.EXTRA_POINT, PlayType.TWO_POINT):
        return True
    if prev.touchdown and curr.play_type in (PlayType.EXTRA_POINT, PlayType.TWO_POINT):
        return True
    if curr.play_result in (
        PlayResult.EXTRA_POINT_MADE,
        PlayResult.EXTRA_POINT_MISSED,
        PlayResult.EXTRA_POINT_BLOCKED,
    ):
        return True
    return False


def _check_sequence_monotonic(plays: list[Play], issues: list[ValidationIssue]) -> None:
    if len(plays) < 2:
        return
    for prev, curr in zip(plays, plays[1:]):
        d = curr.play_sequence - prev.play_sequence
        if d <= 0:
            _append(
                issues,
                rule="sequence_monotonic",
                severity="error",
                message=(
                    f"play_sequence not strictly increasing: "
                    f"{prev.play_sequence} -> {curr.play_sequence}"
                ),
                play_id=curr.external_play_id,
            )
        elif d > 1:
            _append(
                issues,
                rule="sequence_monotonic",
                severity="error",
                message=f"play_sequence gap {d} > 1 after play {prev.play_sequence}",
                play_id=curr.external_play_id,
            )


def _check_quarter_progression(plays: list[Play], issues: list[ValidationIssue]) -> None:
    if len(plays) < 2:
        return
    for prev, curr in zip(plays, plays[1:]):
        if curr.quarter < prev.quarter:
            if _end_of_half(curr):
                continue
            if "timeout" in (curr.raw_description or "").lower():
                continue
            _append(
                issues,
                rule="quarter_progression",
                severity="error",
                message=f"quarter regressed {prev.quarter} -> {curr.quarter}",
                play_id=curr.external_play_id,
            )


def _check_clock_monotonic(plays: list[Play], issues: list[ValidationIssue]) -> None:
    equal_budget = 1
    prev_clock: int | None = None
    prev_q: int | None = None
    for p in plays:
        if p.clock_seconds is None:
            continue
        if "timeout" in (p.raw_description or "").lower():
            continue
        if prev_q is not None and p.quarter == prev_q and prev_clock is not None:
            if p.clock_seconds > prev_clock:
                _append(
                    issues,
                    rule="clock_monotonic",
                    severity="warning",
                    message=(
                        f"clock increased within Q{p.quarter}: "
                        f"{prev_clock}s -> {p.clock_seconds}s"
                    ),
                    play_id=p.external_play_id,
                )
            elif p.clock_seconds == prev_clock:
                if equal_budget <= 0:
                    _append(
                        issues,
                        rule="clock_monotonic",
                        severity="warning",
                        message=(
                            f"second equal clock within Q{p.quarter} "
                            f"({p.clock_seconds}s) after tolerance used"
                        ),
                        play_id=p.external_play_id,
                    )
                else:
                    equal_budget -= 1
        if prev_q is None or p.quarter != prev_q:
            equal_budget = 4
        elif p.play_type == PlayType.PENALTY_NO_PLAY or p.play_result == PlayResult.NO_PLAY:
            equal_budget = 4
        prev_q = p.quarter
        prev_clock = p.clock_seconds


def _check_down_reset_on_first_down(plays: list[Play], issues: list[ValidationIssue]) -> None:
    if len(plays) < 2:
        return
    for prev, curr in zip(plays, plays[1:]):
        if not prev.first_down:
            continue
        pt = prev.possession_team
        ct = curr.possession_team
        if pt is None or ct is None or pt != ct:
            continue
        if curr.down is not None and curr.down != 1:
            _append(
                issues,
                rule="down_reset_on_first_down",
                severity="warning",
                message=f"after first down, expected down=1, got down={curr.down}",
                play_id=curr.external_play_id,
            )


def _check_score_only_on_scoring_play(
    game: Game, plays: list[Play], issues: list[ValidationIssue]
) -> None:
    if len(plays) < 2:
        return
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
        delta = t1 - t0
        if _declares_scoring_event(curr):
            continue
        if _declares_scoring_event(prev):
            continue
        if _pat_one_point_tolerance(curr, prev, delta):
            continue
        if curr.play_type == PlayType.KICKOFF and abs(delta) <= 8:
            continue
        _append(
            issues,
            rule="score_only_on_scoring_play",
            severity="error",
            message=(
                f"total score changed {t0} -> {t1} (Δ{delta}) without "
                f"a recognized scoring play on {curr.external_play_id}"
            ),
            play_id=curr.external_play_id,
        )


def _end_of_half(p: Play) -> bool:
    d = p.raw_description.upper()
    return bool(
        re.search(r"END\s+OF\s+(QUARTER|HALF)|END\s+QUARTER", d)
    )


def _end_of_game(p: Play) -> bool:
    return "END OF GAME" in p.raw_description.upper()


def _turnover_on_downs(p: Play) -> bool:
    return "turnover on downs" in p.raw_description.lower()


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
    if _end_of_half(prev) or _end_of_game(prev):
        return True
    if _turnover_on_downs(prev):
        return True
    return False


def _check_possession_change_explained(plays: list[Play], issues: list[ValidationIssue]) -> None:
    if len(plays) < 2:
        return
    for prev, curr in zip(plays, plays[1:]):
        a, b = prev.possession_team, curr.possession_team
        if a is None or b is None or a == b:
            continue
        if not _explains_possession_change(prev, curr):
            _append(
                issues,
                rule="possession_change_explained",
                severity="warning",
                message=(
                    f"possession {a} -> {b} not explained by typical "
                    f"previous-play events (prev play {prev.external_play_id})"
                ),
                play_id=curr.external_play_id,
            )


def _check_yardline_range(plays: list[Play], issues: list[ValidationIssue]) -> None:
    for p in plays:
        y = p.yardline_100
        if y is None:
            continue
        if not (0 <= y <= 100):
            _append(
                issues,
                rule="yardline_range",
                severity="error",
                message=f"yardline_100={y} not in [0, 100]",
                play_id=p.external_play_id,
            )


def validate_play_sequence(game: Game, plays: list[Play]) -> ValidationReport:
    issues: list[ValidationIssue] = []
    _check_sequence_monotonic(plays, issues)
    _check_quarter_progression(plays, issues)
    _check_clock_monotonic(plays, issues)
    _check_down_reset_on_first_down(plays, issues)
    _check_score_only_on_scoring_play(game, plays, issues)
    _check_possession_change_explained(plays, issues)
    _check_yardline_range(plays, issues)
    return ValidationReport(game_id=game.id, issues=issues)
