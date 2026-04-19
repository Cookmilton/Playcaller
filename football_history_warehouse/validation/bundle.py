"""
Validate a :class:`~football_history_warehouse.normalization.bundle.CanonicalGameBundle` before persistence.

Normalization already enforces Pydantic bounds on individual models; this layer checks
cross-row consistency, ordering, and feed-quality heuristics. It does **not** mutate
the bundle — issues are returned for reporting and optional persistence gates.
"""

from __future__ import annotations

from football_history_warehouse.domain import Play
from football_history_warehouse.domain.enums import FieldSide, PlayFamily
from football_history_warehouse.normalization.bundle import CanonicalGameBundle

from . import codes as c
from .issues import (
    CanonicalBundleValidationResult,
    ValidationIssue,
    ValidationSeverity,
)

_SCRIMMAGE_LIKE = frozenset(
    {
        PlayFamily.RUN,
        PlayFamily.PASS,
        PlayFamily.OTHER,
        PlayFamily.NO_PLAY,
        PlayFamily.UNKNOWN,
    }
)


def _fatal(
    code: str,
    message: str,
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    field: str | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        severity=ValidationSeverity.FATAL,
        message=message,
        entity_type=entity_type,
        entity_id=entity_id,
        field=field,
    )


def _warn(
    code: str,
    message: str,
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    field: str | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        severity=ValidationSeverity.WARNING,
        message=message,
        entity_type=entity_type,
        entity_id=entity_id,
        field=field,
    )


def _nonempty_id(value: object) -> bool:
    if value is None:
        return False
    s = str(value).strip()
    return len(s) > 0


def validate_canonical_game_bundle(bundle: CanonicalGameBundle) -> CanonicalBundleValidationResult:
    """
    Run all bundle-level checks. Returns fatal + warning issues; callers decide whether to persist.

    Fatal issues indicate inconsistent identity, broken references, impossible numeric bounds not
    caught elsewhere, or invalid ordering. Warnings flag likely feed gaps or weak mappings without
    blocking storage (operators can filter in reporting).
    """
    issues: list[ValidationIssue] = []
    g = bundle.game
    gid = str(g.game_id)

    # --- Game identity ---
    for field_name, raw in (
        ("game_id", g.game_id),
        ("season_id", g.season_id),
        ("league_id", g.league_id),
        ("home_team_id", g.home_team_id),
        ("away_team_id", g.away_team_id),
    ):
        if not _nonempty_id(raw):
            issues.append(
                _fatal(
                    c.MISSING_GAME_IDENTITY,
                    f"Missing or empty required game field {field_name!r}.",
                    entity_type="game",
                    entity_id=gid if field_name != "game_id" else str(raw),
                    field=field_name,
                )
            )

    if _nonempty_id(g.home_team_id) and _nonempty_id(g.away_team_id) and str(g.home_team_id) == str(g.away_team_id):
        issues.append(
            _fatal(
                c.TEAM_IDENTITY_CONFLICT,
                "home_team_id and away_team_id must differ.",
                entity_type="game",
                entity_id=gid,
                field="home_team_id",
            )
        )

    drive_ids = {str(d.drive_id) for d in bundle.drives}
    for d in bundle.drives:
        if str(d.game_id) != gid:
            issues.append(
                _fatal(
                    c.DRIVE_GAME_MISMATCH,
                    f"Drive {d.drive_id!r} references game_id {d.game_id!r}, expected {gid!r}.",
                    entity_type="drive",
                    entity_id=str(d.drive_id),
                    field="game_id",
                )
            )
        if str(d.offense_team_id) == str(d.defense_team_id):
            issues.append(
                _fatal(
                    c.OFFENSE_DEFENSE_SAME_TEAM,
                    "Drive offense and defense team ids must differ.",
                    entity_type="drive",
                    entity_id=str(d.drive_id),
                )
            )

    # --- Plays: identity, drive FK, offense/defense ---
    seq_values: list[int] = []
    for p in bundle.plays:
        if str(p.game_id) != gid:
            issues.append(
                _fatal(
                    c.PLAY_GAME_MISMATCH,
                    f"Play {p.play_id!r} references game_id {p.game_id!r}, expected {gid!r}.",
                    entity_type="play",
                    entity_id=str(p.play_id),
                    field="game_id",
                )
            )
        if p.drive_id is not None and str(p.drive_id) not in drive_ids:
            issues.append(
                _fatal(
                    c.PLAY_DRIVE_UNKNOWN,
                    f"Play {p.play_id!r} references drive_id {p.drive_id!r} not present in bundle.drives.",
                    entity_type="play",
                    entity_id=str(p.play_id),
                    field="drive_id",
                )
            )
        if str(p.offense_team_id) == str(p.defense_team_id):
            issues.append(
                _fatal(
                    c.OFFENSE_DEFENSE_SAME_TEAM,
                    "Play offense and defense team ids must differ.",
                    entity_type="play",
                    entity_id=str(p.play_id),
                )
            )

        seq_values.append(p.sequence_in_game)

        # Hard bounds (belt-and-suspenders if models were built without validation)
        if p.down is not None and not (1 <= p.down <= 4):
            issues.append(
                _fatal(
                    c.DOWN_OUT_OF_RANGE,
                    f"down must be 1..4 or null, got {p.down}.",
                    entity_type="play",
                    entity_id=str(p.play_id),
                    field="down",
                )
            )
        if p.distance is not None and p.distance > 99:
            issues.append(
                _fatal(
                    c.DISTANCE_OUT_OF_RANGE,
                    f"distance exceeds plausible maximum (99), got {p.distance}.",
                    entity_type="play",
                    entity_id=str(p.play_id),
                    field="distance",
                )
            )
        if p.yards_to_goal_line is not None and not (1 <= p.yards_to_goal_line <= 99):
            issues.append(
                _fatal(
                    c.YARDS_TO_GOAL_OUT_OF_RANGE,
                    f"yards_to_goal_line must be 1..99 or null, got {p.yards_to_goal_line}.",
                    entity_type="play",
                    entity_id=str(p.play_id),
                    field="yards_to_goal_line",
                )
            )
        if p.clock_seconds_remaining_in_period is not None:
            if p.clock_seconds_remaining_in_period < 0 or p.clock_seconds_remaining_in_period > 3600:
                issues.append(
                    _fatal(
                        c.CLOCK_OUT_OF_RANGE,
                        f"clock_seconds_remaining_in_period must be 0..3600 or null, got {p.clock_seconds_remaining_in_period}.",
                        entity_type="play",
                        entity_id=str(p.play_id),
                        field="clock_seconds_remaining_in_period",
                    )
                )

        _play_warnings(p, g, issues)

    # --- Sequence ordering ---
    if seq_values:
        if len(set(seq_values)) != len(seq_values):
            issues.append(
                _fatal(
                    c.SEQUENCE_DUPLICATE,
                    "Duplicate sequence_in_game values in plays.",
                    entity_type="game",
                    entity_id=gid,
                    field="sequence_in_game",
                )
            )
        sorted_seq = sorted(seq_values)
        if seq_values != sorted_seq:
            issues.append(
                _fatal(
                    c.SEQUENCE_NOT_SORTED,
                    "plays tuple must be ordered by non-decreasing sequence_in_game.",
                    entity_type="game",
                    entity_id=gid,
                    field="sequence_in_game",
                )
            )
        for prev, nxt in zip(sorted_seq, sorted_seq[1:], strict=False):
            if nxt - prev > 1:
                issues.append(
                    _warn(
                        c.SEQUENCE_GAP,
                        f"Gap in sequence_in_game between {prev} and {nxt} (possible missing plays).",
                        entity_type="game",
                        entity_id=gid,
                        field="sequence_in_game",
                    )
                )

    return CanonicalBundleValidationResult(issues=tuple(issues))


def _play_warnings(p: Play, game, issues: list[ValidationIssue]) -> None:
    """Append heuristic warnings for one play (mutates ``issues``)."""
    pid = str(p.play_id)
    reg = game.regulation_period_count

    if p.period is not None and p.period > reg + 4:
        issues.append(
            _warn(
                c.PERIOD_EXTREME_OT,
                f"period {p.period} is far beyond regulation+OT heuristic (regulation_period_count={reg}).",
                entity_type="play",
                entity_id=pid,
                field="period",
            )
        )

    if (
        p.period is not None
        and 1 <= p.period <= reg
        and p.clock_seconds_remaining_in_period is not None
        and p.clock_seconds_remaining_in_period > 900
    ):
        issues.append(
            _warn(
                c.CLOCK_EXCEEDS_REGULATION_QUARTER,
                "Clock exceeds 15:00 for a regulation-period play (check quarter vs clock).",
                entity_type="play",
                entity_id=pid,
                field="clock_seconds_remaining_in_period",
            )
        )

    if p.clock_seconds_remaining_in_period is not None and p.period is None and p.play_family in _SCRIMMAGE_LIKE:
        issues.append(
            _warn(
                c.PERIOD_CLOCK_MISMATCH,
                "Clock present without period for a scrimmage-like play.",
                entity_type="play",
                entity_id=pid,
                field="period",
            )
        )

    down_set = p.down is not None
    dist_set = p.distance is not None
    if p.play_family in _SCRIMMAGE_LIKE and down_set != dist_set:
        issues.append(
            _warn(
                c.SITUATION_INCOMPLETE,
                "down and distance should both be set or both null for scrimmage-like plays (unless feed is truly partial).",
                entity_type="play",
                entity_id=pid,
                field="down",
            )
        )

    if p.play_family in (PlayFamily.RUN, PlayFamily.PASS):
        missing_situation = sum(
            1
            for x in (
                p.period,
                p.clock_seconds_remaining_in_period,
                p.down,
                p.distance,
            )
            if x is None
        )
        if missing_situation >= 4:
            issues.append(
                _warn(
                    c.SITUATION_SPARSE_SCRIMMAGE,
                    "Run/pass play lacks period, clock, down, and distance (likely incomplete feed mapping).",
                    entity_type="play",
                    entity_id=pid,
                )
            )

    # Field position: soft consistency (avoid noisy rules — only flag strong contradictions)
    if p.field_side in (FieldSide.OWN, FieldSide.OPPONENT) and p.yards_to_goal_line is not None:
        ytg = p.yards_to_goal_line
        if p.field_side == FieldSide.OPPONENT and ytg > 55:
            issues.append(
                _warn(
                    c.FIELD_POSITION_SUSPICIOUS,
                    "field_side=opponent but yards_to_goal_line is very large (labeling may be wrong).",
                    entity_type="play",
                    entity_id=pid,
                    field="field_side",
                )
            )
        if p.field_side == FieldSide.OWN and ytg < 15:
            issues.append(
                _warn(
                    c.FIELD_POSITION_SUSPICIOUS,
                    "field_side=own but yards_to_goal_line is very small (labeling may be wrong).",
                    entity_type="play",
                    entity_id=pid,
                    field="field_side",
                )
            )
