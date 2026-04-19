"""
Football-first situation buckets for historical similarity (interpretable, no ML).

Used for both **live** ``GameContext`` and **normalized** rows (recomputed from
``down``, ``distance``, ``territory``, ``yardline`` when present — not from stale
stored bucket strings alone).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from playcaller.domain import GameContext

from .normalize import derive_yardline_100


def is_goal_to_go(
    *,
    territory: Optional[str],
    yardline: Optional[int],
    distance: Optional[int],
    down: Optional[int],
) -> bool:
    """Opponent territory and the sticks are at or past the goal line (1st–3rd down)."""
    if territory is None or yardline is None or distance is None or down is None:
        return False
    if str(territory) != "opponents":
        return False
    if int(down) >= 4:
        return False
    try:
        return int(yardline) <= int(distance)
    except (TypeError, ValueError):
        return False


def match_distance_bucket(
    *,
    down: Optional[int],
    distance: Optional[int],
    territory: Optional[str],
    yardline: Optional[int],
) -> Optional[str]:
    """
    To-go buckets: ``short`` (1–2), ``medium`` (3–6), ``long`` (7+), ``fourth_down``, ``goal_to_go``.

    ``goal_to_go`` takes precedence over short/medium/long on 1st–3rd.
    """
    if down is None or distance is None:
        return None
    try:
        d_int = int(down)
        dist_int = int(distance)
    except (TypeError, ValueError):
        return None
    if d_int == 4:
        return "fourth_down"
    if is_goal_to_go(territory=territory, yardline=yardline, distance=distance, down=down):
        return "goal_to_go"
    if dist_int <= 2:
        return "short"
    if dist_int <= 6:
        return "medium"
    return "long"


def match_field_zone(
    *,
    yardline_100: Optional[int],
    territory: Optional[str],
    yardline: Optional[int],
    distance: Optional[int],
    down: Optional[int],
) -> Optional[str]:
    """
    Field buckets (offense yardline from own goal, 1–99):

    - ``goal_to_go`` — same rule as distance bucket (caller may duplicate-check)
    - ``backed_up`` — own 1–15
    - ``own_territory`` — own 16–50
    - ``midfield`` — 51–60
    - ``fringe`` —61–79 (attack area, not yet RZ)
    - ``red_zone`` — 80+ (opponent ~20 and in)
    """
    if is_goal_to_go(territory=territory, yardline=yardline, distance=distance, down=down):
        return "goal_to_go"
    if yardline_100 is None:
        return None
    try:
        y = int(yardline_100)
    except (TypeError, ValueError):
        return None
    y = max(1, min(99, y))
    if y <= 15:
        return "backed_up"
    if y <= 50:
        return "own_territory"
    if y <= 60:
        return "midfield"
    if y <= 79:
        return "fringe"
    return "red_zone"


@dataclass(frozen=True)
class SituationSignature:
    """Bucketing snapshot used for similarity (all optional fields explicit)."""

    down: int
    distance_bucket: str
    field_zone: str
    yardline_100: Optional[int]
    territory: Optional[str]
    yardline: Optional[int]
    distance: Optional[int]
    score_diff: Optional[int] = None

    def describe(self) -> str:
        y = f"y100={self.yardline_100}" if self.yardline_100 is not None else "y100=—"
        sd = (
            f"score_diff={self.score_diff}"
            if self.score_diff is not None
            else "score_diff=—"
        )
        return (
            f"{self.down}{self.distance_bucket}/{self.field_zone} · {y} · {sd} "
            f"(LOS {self.territory or '—'} {self.yardline if self.yardline is not None else '—'})"
        )


def situation_signature_from_context(ctx: GameContext) -> SituationSignature:
    """Build buckets from a live pre-snap context."""
    y100 = derive_yardline_100(territory=ctx.territory, yardline=ctx.yardline)
    db = match_distance_bucket(
        down=ctx.down,
        distance=ctx.distance,
        territory=ctx.territory,
        yardline=ctx.yardline,
    )
    fz = match_field_zone(
        yardline_100=y100,
        territory=ctx.territory,
        yardline=ctx.yardline,
        distance=ctx.distance,
        down=ctx.down,
    )
    if db is None or fz is None:
        raise ValueError("Cannot derive situation buckets from GameContext (check down/distance/field).")
    return SituationSignature(
        down=int(ctx.down),
        distance_bucket=db,
        field_zone=fz,
        yardline_100=y100,
        territory=str(ctx.territory),
        yardline=int(ctx.yardline),
        distance=int(ctx.distance),
        score_diff=int(ctx.score_diff),
    )


def situation_signature_from_normalized_row(
    *,
    down: Optional[int],
    distance: Optional[int],
    territory: Optional[str],
    yardline: Optional[int],
    score_diff: Optional[int],
) -> Optional[SituationSignature]:
    """Rebuild signature from a row's situation columns; ``None`` if insufficient data."""
    if down is None or distance is None:
        return None
    if territory is None or yardline is None:
        return None
    y100 = derive_yardline_100(territory=territory, yardline=yardline)
    if y100 is None:
        return None
    db = match_distance_bucket(
        down=down,
        distance=distance,
        territory=territory,
        yardline=yardline,
    )
    fz = match_field_zone(
        yardline_100=y100,
        territory=territory,
        yardline=yardline,
        distance=distance,
        down=down,
    )
    if db is None or fz is None:
        return None
    return SituationSignature(
        down=int(down),
        distance_bucket=db,
        field_zone=fz,
        yardline_100=y100,
        territory=str(territory),
        yardline=int(yardline),
        distance=int(distance),
        score_diff=int(score_diff) if score_diff is not None else None,
    )


# --- Explicit widening (fallback) helpers: adjacency is readable and finite ---

DISTANCE_BUCKET_NEIGHBORS: dict[str, tuple[str, ...]] = {
    "short": ("short", "medium"),
    "medium": ("short", "medium", "long"),
    "long": ("medium", "long", "goal_to_go"),
    "goal_to_go": ("long", "goal_to_go", "short"),
    "fourth_down": ("fourth_down", "medium", "long"),
}

FIELD_ZONE_NEIGHBORS: dict[str, tuple[str, ...]] = {
    "backed_up": ("backed_up", "own_territory"),
    "own_territory": ("backed_up", "own_territory", "midfield"),
    "midfield": ("own_territory", "midfield", "fringe"),
    "fringe": ("midfield", "fringe", "red_zone"),
    "red_zone": ("fringe", "red_zone", "goal_to_go"),
    "goal_to_go": ("red_zone", "goal_to_go", "fringe"),
}


def distance_buckets_relaxed(bucket: str) -> tuple[str, ...]:
    return DISTANCE_BUCKET_NEIGHBORS.get(bucket, (bucket,))


def field_zones_relaxed(zone: str) -> tuple[str, ...]:
    return FIELD_ZONE_NEIGHBORS.get(zone, (zone,))


def yardline_within_tolerance(
    y_a: Optional[int],
    y_b: Optional[int],
    *,
    yards: int,
) -> bool:
    """If ``yards <= 0``, yardline is not used as a filter (buckets carry field position)."""
    if int(yards) <= 0:
        return True
    if y_a is None or y_b is None:
        return True
    try:
        return abs(int(y_a) - int(y_b)) <= int(yards)
    except (TypeError, ValueError):
        return True
