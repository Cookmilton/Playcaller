from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


# ──────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────────────────────

RUN_FAMILIES = {"inside_zone", "outside_zone", "duo", "power", "draw"}
PASS_FAMILIES = {"quick_game", "dropback_pass", "screen", "play_action", "fade_iso"}

# opponents' 35 ≈ 52-yard attempt — makeable for most kickers
FG_RANGE_YARDLINE = 35

# ── Provenance of a logged play's family / concept (K1.2) ─────────────────────
#: The operator ticked "Ran the recommended call": family/concept are the call's.
CALL_SOURCE_OPERATOR_CONFIRMED = "operator_confirmed"
#: Nobody recorded which call was run: family/concept are ``None``.
CALL_SOURCE_UNOBSERVED = "unobserved"
#: Derived from an ESPN feed row.
CALL_SOURCE_FEED = "feed"

#: Only these rows may be counted in family-match metrics. A missing ``call_source``
#: (legacy export) is untrusted and is excluded, exactly like J3's ``time_source``.
TRUSTED_CALL_SOURCES = frozenset({CALL_SOURCE_OPERATOR_CONFIRMED})


def call_is_observed(actual: "ActualPlayResult") -> bool:
    """Whether this row's ``family`` / ``concept_name`` reflect the call actually run."""
    return (
        getattr(actual, "call_source", None) in TRUSTED_CALL_SOURCES
        and bool(getattr(actual, "family", None))
    )


# ──────────────────────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class GameContext:
    """Everything an OC would see at the line of scrimmage."""

    # ── Core situation ────────────────────────────────────────────────────────
    down: int
    distance: int
    yardline: int
    territory: str  # "own" | "opponents"

    # ── Game script ───────────────────────────────────────────────────────────
    score_diff: int = 0  # positive = offense winning
    quarter: int = 2
    seconds_remaining: int = 1800
    own_timeouts: int = 3
    opp_timeouts: int = 3

    # ── Defensive pre-snap read ───────────────────────────────────────────────
    def_personnel: str = "unknown"  # base | nickel | dime | goal_line | unknown
    box_count: int = 7
    coverage_shell: str = "unknown"  # cover_0|cover_1|cover_2|cover_3|cover_4|quarters|unknown
    blitz_likely: bool = False
    safeties: str = "unknown"  # single_high | two_high | unknown

    # ── Environment ───────────────────────────────────────────────────────────
    weather: str = "clear"  # clear | wind | rain | snow
    wind_mph: int = 0
    turf: str = "turf"  # grass | turf

    # ── Personnel & matchup ───────────────────────────────────────────────────
    personnel_group: str = "11"  # 10 | 11 | 12 | 21 | 22
    mismatch: Optional[str] = None  # free text, e.g. "slot CB is undersized"
    qb_limited: bool = False

    # ── Drive state ───────────────────────────────────────────────────────────
    plays_this_drive: int = 0
    shown_concepts: List[str] = field(default_factory=list)
    run_plays_this_drive: int = 0  # used by play-action qualifier

    # ── Game mode ─────────────────────────────────────────────────────────────
    game_mode: str = "normal"  # normal | must_score | drain_clock | two_minute | two_point


@dataclass
class ActualPlayResult:
    """
    Post-play truth recorded when the user logs a play.

    Separate from ``PredictedPlayResult`` (pre-snap projection on recommendations only).
    Use ``format_actual_play_result_description`` for a one-line summary from these fields.
    """

    # K1.2: ``None`` means "not recorded", not "empty". The operator Log path used to
    # copy the *recommendation's* family/concept onto the logged play, so every logged
    # row claimed the call that was suggested — even a field goal. Only an operator
    # confirmation (``call_source == "operator_confirmed"``) may fill these now.
    concept_name: Optional[str] = None
    family: Optional[str] = None
    play_type: Optional[str] = None  # run | pass | qb_scramble | two_point | …
    #: Provenance of ``family`` / ``concept_name`` — see ``CALL_SOURCE_*`` below.
    #: Absent in legacy exports, which means untrusted (same rule as J3 ``time_source``).
    call_source: Optional[str] = None
    result_type: str = ""  # first_down | interception | incomplete | sack | …
    yards_gained: int = 0
    ball_carrier_or_target: str = ""
    target_position: Optional[str] = None
    target_role_label: str = ""  # e.g. slot, TE, X receiver — for phrasing
    pass_result: str = ""  # complete | incomplete | intercepted | sack | ""
    scramble: bool = False
    first_down: bool = False
    touchdown: bool = False
    turnover: bool = False
    turnover_kind: str = ""  # interception | fumble | ""
    sack: bool = False
    penalty: bool = False
    penalty_yards: int = 0
    notes: str = ""
    description: str = ""  # formatted summary; filled at log time if empty
    # ESPN / feed row id when known (dedup across syncs; optional for manual-only rows).
    external_play_id: Optional[str] = None
    # Optional feed overlays (display / debugging only; not used by the predictor).
    feed_passer_label: str = ""
    feed_receiver_label: str = ""
    feed_rusher_label: str = ""
    # Broad receiving role when the feed (structured or text) supplies it — WR / TE / RB only.
    feed_target_role: str = ""
    feed_passer_jersey: str = ""
    feed_receiver_jersey: str = ""
    feed_rusher_jersey: str = ""
    # Defender / pass rusher only when explicitly present (e.g. structured sackedBy).
    feed_defender_label: str = ""
    # ESPN summary ``drives.*.plays[]`` pre-snap metadata (when imported from feed; None for manual).
    feed_period_number: Optional[int] = None
    feed_clock_display: Optional[str] = None
    feed_presnap_down: Optional[int] = None
    feed_presnap_distance: Optional[int] = None
    # Raw ESPN ``start.yardLine`` (often equals yards-to-endzone on summary plays).
    feed_start_yard_line: Optional[int] = None
    feed_yards_to_endzone: Optional[int] = None
    # Canonical field (1–50, ``GameContext`` / ``situation.py`` convention) after parse.
    feed_presnap_territory: Optional[str] = None  # "own" | "opponents"
    feed_presnap_yardline: Optional[int] = None
    feed_possession_team_id: Optional[str] = None
    feed_possession_team_abbr: Optional[str] = None
    # True when ESPN text indicates ``& Goal`` (structured distance may still be numeric).
    feed_presnap_goal_down: bool = False
    feed_home_score: Optional[int] = None
    feed_away_score: Optional[int] = None
    # ESPN ``plays[].sequenceNumber`` when imported from feed (drive sort). None for manual rows.
    feed_sequence_number: Optional[int] = None


# Backwards-compatible name for drive logging (same shape as ``ActualPlayResult``).
PlayResult = ActualPlayResult


def play_type_for_family(family: Optional[str]) -> str:
    # K1.2: ``None`` family means the call was never recorded — never stringify it to
    # the literal "None", which would read as a play type downstream.
    if not family:
        return ""
    f = str(family)
    if f in RUN_FAMILIES:
        return "run"
    if f in PASS_FAMILIES:
        return "pass"
    if f == "two_point":
        return "two_point"
    return f


def ball_carrier_and_target_from_play(play: dict, family: str) -> tuple[str, Optional[str]]:
    """
    Design-time primary from the call sheet (not the pre-snap projection).

    Returns (ball_carrier_or_target, target_position).
    """
    pt = play_type_for_family(family)
    routes = play.get("routes") or {}
    if pt == "run":
        scheme = str(play.get("run_scheme") or "").lower()
        if "qb" in scheme and "sneak" in scheme:
            return "QB", None
        return "RB", None
    if routes:
        pos = str(next(iter(routes.keys())))
        return pos, pos
    return "", None

