"""
Football-native situation input ↔ ``GameContext`` / session fields.

Keeps **predictor-facing** ``GameContext.quarter`` (1–4) and ``seconds_remaining``
(quarter clock) stable while the UI uses period1–5 (5 = OT) and explicit quarter time.
"""

from __future__ import annotations

from typing import Tuple

# UI period: 1–4 regulation, 5 = overtime. Predictor uses quarter 1–4 only; OT maps to 4.
PERIOD_OT = 5

# Regulation quarter length (NFL-style15:00). OT period length for clamping UI input.
SECONDS_PER_REG_QUARTER = 15 * 60
SECONDS_PER_OT_PERIOD = 10 * 60


def is_overtime_period(period: int) -> bool:
    return int(period) == PERIOD_OT


def context_quarter_from_period(period: int) -> int:
    """Map UI period (1–5) to ``GameContext.quarter`` / normalization (max 4)."""
    p = int(period)
    if p < 1:
        return 1
    if p >= PERIOD_OT:
        return 4
    return min(4, p)


def max_seconds_in_period(period: int) -> int:
    return SECONDS_PER_OT_PERIOD if is_overtime_period(period) else SECONDS_PER_REG_QUARTER


def clamp_quarter_clock_seconds(period: int, total_seconds: int) -> int:
    """Clamp clock-in-period to valid range for that period."""
    return max(0, min(int(total_seconds), max_seconds_in_period(period)))


def split_clock(mins: int, secs: int, period: int) -> Tuple[int, int, int]:
    """
    Clamp minute/second pickers and return (total_seconds, clamped_mins, clamped_secs).

    ``mins`` / ``secs`` are **within the current quarter** (not game-total).
    """
    m = max(0, int(mins))
    s = max(0, min(59, int(secs)))
    total = clamp_quarter_clock_seconds(period, m * 60 + s)
    return total, total // 60, total % 60


def period_display_label(period: int) -> str:
    p = int(period)
    if p == PERIOD_OT:
        return "OT"
    if 1 <= p <= 4:
        return f"Q{p}"
    return f"Q{min(4, max(1, p))}"


def format_clock_left_in_quarter(*, period: int, seconds_in_quarter: int) -> str:
    """e.g. ``Q2 · 9:32 left`` or ``OT · 8:00 left``."""
    sec = clamp_quarter_clock_seconds(period, int(seconds_in_quarter))
    m, s = divmod(sec, 60)
    return f"{period_display_label(period)} · {m}:{s:02d} left"


def format_ball_spot(*, territory: str, yardline: int) -> str:
    """e.g. ``Own 25``, ``Opp 37`` (``territory`` is ``own`` | ``opponents``)."""
    t = str(territory).strip().lower()
    side = "Own" if t == "own" else "Opp"
    return f"{side} {int(yardline)}"


def format_down_distance(down: int, distance: int) -> str:
    d = max(1, min(4, int(down)))
    dist = max(1, int(distance))
    ordn = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}.get(d, f"{d}th")
    return f"{ordn} & {dist}"


def format_live_situation_summary(
    *,
    period: int,
    seconds_in_quarter: int,
    our_score: int,
    their_score: int,
    territory: str,
    yardline: int,
    down: int,
    distance: int,
) -> str:
    """
    Single-line operator-facing summary (first is **our** score).

    Example: ``Q2 · 9:32 left · Ball on Opp 37 · 17–21 · 2nd & 6``
    """
    clock = format_clock_left_in_quarter(period=period, seconds_in_quarter=seconds_in_quarter)
    ball = format_ball_spot(territory=territory, yardline=yardline)
    dd = format_down_distance(down, distance)
    return f"{clock} · Ball on {ball} · {int(our_score)}–{int(their_score)} · {dd}"


def score_diff_from_board(*, our_score: int, their_score: int) -> int:
    """``GameContext.score_diff``: positive = offense (we) winning."""
    return int(our_score) - int(their_score)
