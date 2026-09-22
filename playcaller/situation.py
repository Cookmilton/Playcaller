"""
Drive situation progression (down / distance / field position).

Field position model (matches ``GameContext`` + UI sliders):

- ``territory`` is ``"own"`` or ``"opponents"``.
- ``yardline`` is always 1–50:
  - On **own**: yards from your **own** goal line toward midfield (own 1 … own 50).
  - On **opponents**: yards from the **opponent goal line** back toward midfield
    (opp 1 = goal line … opp 50 = midfield).

We convert to **yards from own goal** (1 = own GL, 99 ≈ opp GL, 50 = midfield) for
movement math, then convert back so territory flips automatically when crossing
midfield (50/50).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional

from .domain import ActualPlayResult

# ── Change-of-possession reasons (``SituationSnapshot.change_of_possession``) ──
#
# K1.1: these replace the old overloaded ``turnover_on_downs`` boolean, which a
# field-goal miss, a punt, and a generic turnover all set to True — so the UI
# announced "Turnover on downs" for every one of them. Each branch now states
# *why* possession changes; ``turnover_on_downs`` is derived from this and is
# True only for a genuine fourth-down failure.
COP_TURNOVER_ON_DOWNS = "turnover_on_downs"
COP_FIELD_GOAL_MADE = "field_goal_made"
COP_FIELD_GOAL_MISS = "field_goal_miss"
COP_INTERCEPTION = "interception"
COP_TURNOVER = "turnover"
COP_PUNT = "punt"

#: Reasons that end the offense's possession, so the open drive must be archived.
DRIVE_ENDING_CHANGE_OF_POSSESSION = frozenset(
    {
        COP_TURNOVER_ON_DOWNS,
        COP_FIELD_GOAL_MADE,
        COP_FIELD_GOAL_MISS,
        COP_INTERCEPTION,
        COP_TURNOVER,
        COP_PUNT,
    }
)

#: Operator-facing recap line per reason, and a short toast chip. Each reason has
#: its own wording — "Turnover on downs" belongs to the fourth-down failure alone.
_CHANGE_OF_POSSESSION_COPY: dict[str, tuple[str, str]] = {
    COP_TURNOVER_ON_DOWNS: ("Turnover on downs — defense takes over at this spot.", "TOD"),
    COP_FIELD_GOAL_MADE: ("Field goal good — drive over, kick off next.", "FG good"),
    COP_FIELD_GOAL_MISS: ("Field goal missed — defense takes over at the spot.", "FG miss"),
    COP_INTERCEPTION: ("Intercepted — defense takes over.", "INT"),
    COP_TURNOVER: ("Turnover — defense takes over.", "TO"),
    COP_PUNT: ("Punt — defense takes over.", "Punt"),
}


def change_of_possession_copy(reason: Optional[str]) -> Optional[tuple[str, str]]:
    """``(recap_line, toast_chip)`` for a change-of-possession reason, or ``None``."""
    if not reason:
        return None
    return _CHANGE_OF_POSSESSION_COPY.get(str(reason))


@dataclass(frozen=True)
class ProgressionTags:
    """Derived flags for one logged play (analytics / UI / hooks)."""

    no_gain: bool = False
    negative_play: bool = False
    first_down_exact: bool = False
    crossed_midfield: bool = False
    explosive_play: bool = False
    explosive_midfield: bool = False


# Optional app hook: ``fn(snapshot, payload)`` — set via ``register_post_play_hook``.
# Payload is a plain dict (yards, outcome, etc.) for future turnover/reset wiring.
_post_play_hook: Optional[Callable[["SituationSnapshot", Mapping[str, Any]], None]] = None


def register_post_play_hook(
    fn: Optional[Callable[["SituationSnapshot", Mapping[str, Any]], None]],
) -> None:
    """Register or clear a callback invoked after each logged play (Streamlit/tests)."""
    global _post_play_hook
    _post_play_hook = fn


def invoke_post_play_hook(snapshot: "SituationSnapshot", payload: Mapping[str, Any]) -> None:
    """Invoke the registered hook, if any. Swallows exceptions so logging never breaks."""
    if _post_play_hook is None:
        return
    try:
        _post_play_hook(snapshot, payload)
    except Exception:
        pass


def play_progression_tags(
    *,
    start_abs: int,
    abs_after_clamped: int,
    gain: int,
    pre_distance: int,
    earned_first_down: bool,
    touchdown: bool,
) -> ProgressionTags:
    """
    Tag a single play for UI / hooks.

    - **explosive_play**: gain ≥ 15 (positive).
    - **explosive_midfield**: crossed midfield on a gain of ≥ 10.
    - **crossed_midfield**: LOS moved from own half to opp half or vice versa (50 line).
    """
    sm = max(1, min(99, int(start_abs)))
    am = max(1, min(99, int(abs_after_clamped)))
    if touchdown:
        # Past midfield on TD: started on own half and ball passed the 50 on the play.
        crossed = sm <= 50 and (sm + int(gain)) > 50
    else:
        crossed = (sm <= 50 < am) or (sm > 50 >= am)

    no_gain = gain == 0 and not earned_first_down and not touchdown
    neg = gain < 0
    fd_exact = earned_first_down and not touchdown and gain == int(pre_distance)
    explosive = gain >= 15
    explosive_midfield = crossed and gain >= 10 and gain > 0
    return ProgressionTags(
        no_gain=no_gain,
        negative_play=neg,
        first_down_exact=fd_exact,
        crossed_midfield=crossed,
        explosive_play=explosive,
        explosive_midfield=explosive_midfield,
    )


@dataclass(frozen=True)
class SituationSnapshot:
    """Post-snap situation for the next play call."""

    territory: str
    yardline: int
    down: int
    distance: int
    touchdown: bool = False
    #: Why the offense loses the ball on this play, or ``None``. One of the
    #: ``COP_*`` constants above; see :data:`DRIVE_ENDING_CHANGE_OF_POSSESSION`.
    change_of_possession: Optional[str] = None
    tags: ProgressionTags = field(default_factory=ProgressionTags)

    @property
    def turnover_on_downs(self) -> bool:
        """Back-compat flag — a genuine fourth-down failure only.

        Derived, never stored, so no branch can set it independently of
        :attr:`change_of_possession` again.
        """
        return self.change_of_possession == COP_TURNOVER_ON_DOWNS

    @property
    def ends_drive(self) -> bool:
        """Whether this play hands the ball to the other team."""
        return self.change_of_possession in DRIVE_ENDING_CHANGE_OF_POSSESSION


def yards_from_own_goal(territory: str, yardline: int) -> int:
    """Ball position as yards from offense's own goal line (1–99 in field)."""
    y = max(1, min(50, int(yardline)))
    if territory == "opponents":
        return max(1, min(99, 100 - y))
    return y


def _abs_to_territory_yardline(abs_y: int) -> tuple[str, int]:
    """Map absolute yard from own goal to (territory, yardline) with 1–50 convention."""
    abs_y = max(1, min(99, int(abs_y)))
    if abs_y <= 50:
        return "own", abs_y
    return "opponents", 100 - abs_y


def territory_yardline_from_abs_yards(abs_y: int) -> tuple[str, int]:
    """
    Public helper: ball spot as yards from the offense's own goal (1–99) → (territory, yardline).

    Used by live-data ingestion to map external feeds into ``GameContext`` field conventions.
    """
    return _abs_to_territory_yardline(abs_y)


def yards_to_opponent_goal_from_abs(abs_y: int) -> int:
    """Yards remaining to opponent goal for offense at ``abs_y``."""
    return max(1, 100 - max(1, min(99, int(abs_y))))


def earned_first_down_for_actual_play(
    actual: ActualPlayResult,
    net_gain: int,
    distance: int,
) -> bool:
    """Whether chains move from logged semantics + net yards (excludes INT, incomplete, sack)."""
    if bool(actual.first_down):
        return True
    if actual.turnover or (actual.turnover_kind or "").lower() == "interception":
        return False
    pr = (actual.pass_result or "").lower()
    if pr in ("incomplete", "intercepted", "sack"):
        return False
    if actual.sack:
        return False
    return int(net_gain) >= int(distance)


def advance_game_state_after_actual(
    *,
    territory: str,
    yardline: int,
    down: int,
    distance: int,
    actual: ActualPlayResult,
) -> SituationSnapshot:
    """
    Advance down/distance/field using **logged** play data only (no projection).

    - Net movement: ``yards_gained`` plus ``penalty_yards`` when ``penalty`` is true.
    - ``touchdown`` on the actual forces enough gain to reach the goal if needed.
    - ``turnover`` (non-TD) parks a new possession at the post-play spot (1st & 10).
    """
    t = territory if territory in ("own", "opponents") else "own"
    d = max(1, min(4, int(down)))
    dist = max(1, min(25, int(distance)))
    start_abs = yards_from_own_goal(t, yardline)

    rt_act = (actual.result_type or "").strip().lower()
    if rt_act == "field_goal":
        tags = ProgressionTags()
        return SituationSnapshot(
            territory="own",
            yardline=25,
            down=1,
            distance=10,
            touchdown=False,
            change_of_possession=COP_FIELD_GOAL_MADE,
            tags=tags,
        )
    if rt_act == "field_goal_miss":
        ytg = yards_to_opponent_goal_from_abs(start_abs)
        tags = ProgressionTags()
        return SituationSnapshot(
            territory=t,
            yardline=int(yardline),
            down=1,
            distance=min(10, ytg),
            touchdown=False,
            change_of_possession=COP_FIELD_GOAL_MISS,
            tags=tags,
        )
    if rt_act == "kickoff":
        g = int(actual.yards_gained)
        yl = min(50, max(1, 25 + max(0, g)))
        tags = ProgressionTags()
        return SituationSnapshot(
            territory="own",
            yardline=yl,
            down=1,
            distance=10,
            touchdown=False,
            change_of_possession=None,
            tags=tags,
        )
    if rt_act == "punt":
        tags = ProgressionTags()
        return SituationSnapshot(
            territory="own",
            yardline=25,
            down=1,
            distance=10,
            touchdown=False,
            change_of_possession=COP_PUNT,
            tags=tags,
        )
    if rt_act in ("extra_point", "extra_point_miss"):
        tags = ProgressionTags()
        return SituationSnapshot(
            territory="own",
            yardline=25,
            down=1,
            distance=10,
            touchdown=False,
            change_of_possession=None,
            tags=tags,
        )

    net_gain = int(actual.yards_gained)
    if actual.penalty:
        net_gain += int(actual.penalty_yards)

    if actual.touchdown:
        net_gain = max(net_gain, 100 - start_abs)

    earned_fd = earned_first_down_for_actual_play(actual, net_gain, dist)
    snap = advance_game_state_after_play(
        territory=t,
        yardline=int(yardline),
        down=d,
        distance=dist,
        yards_gained=net_gain,
        earned_first_down=earned_fd,
    )

    if actual.turnover and not snap.touchdown:
        abs_y = yards_from_own_goal(snap.territory, snap.yardline)
        ytg = yards_to_opponent_goal_from_abs(abs_y)
        kind = (actual.turnover_kind or "").strip().lower()
        pr = (actual.pass_result or "").strip().lower()
        if kind == "interception" or pr == "intercepted" or rt_act == "interception":
            reason = COP_INTERCEPTION
        else:
            reason = COP_TURNOVER
        return SituationSnapshot(
            territory=snap.territory,
            yardline=snap.yardline,
            down=1,
            distance=min(10, ytg),
            touchdown=False,
            change_of_possession=reason,
            tags=snap.tags,
        )
    return snap


def advance_game_state_after_play(
    *,
    territory: str,
    yardline: int,
    down: int,
    distance: int,
    yards_gained: int,
    earned_first_down: bool,
) -> SituationSnapshot:
    """
    Apply one offensive play and return the next down/distance/field.

    Assumptions (OC / rehearsal tool, not full game sim):

    - **Touchdown**: ``abs >= 100`` → parked at opp 1, 1st & goal from the 1,
      ``touchdown=True`` (use **New drive** for kickoff / next series).
    - **Safety / own GL**: LOS clamped to own 1 if chain would go ``< 1``.
    - **Turnover on downs**: if offense fails on 4th (no new first), next snap is
      treated as **1st & 10** at the same post-play spot for the *next* offensive
      possession (defense ball spot); ``change_of_possession="turnover_on_downs"``.
    - **New first down**: distance is ``min(10, yards_to_goal)`` (goal-to-go cap).
    """
    t = territory if territory in ("own", "opponents") else "own"
    d = max(1, min(4, int(down)))
    dist = max(1, min(25, int(distance)))
    gain = int(yards_gained)

    start_abs = yards_from_own_goal(t, yardline)
    abs_after = start_abs + gain

    if abs_after >= 100:
        tags = play_progression_tags(
            start_abs=start_abs,
            abs_after_clamped=99,
            gain=gain,
            pre_distance=dist,
            earned_first_down=True,
            touchdown=True,
        )
        return SituationSnapshot(
            territory="opponents",
            yardline=1,
            down=1,
            distance=1,
            touchdown=True,
            change_of_possession=None,
            tags=tags,
        )

    if abs_after < 1:
        abs_after = 1

    new_t, new_y = _abs_to_territory_yardline(abs_after)
    ytg = yards_to_opponent_goal_from_abs(abs_after)

    if earned_first_down:
        new_dist = min(10, ytg)
        tags = play_progression_tags(
            start_abs=start_abs,
            abs_after_clamped=abs_after,
            gain=gain,
            pre_distance=dist,
            earned_first_down=True,
            touchdown=False,
        )
        return SituationSnapshot(
            territory=new_t,
            yardline=new_y,
            down=1,
            distance=max(1, new_dist),
            touchdown=False,
            change_of_possession=None,
            tags=tags,
        )

    next_down = d + 1
    next_dist = max(1, dist - gain)

    if next_down > 4:
        tags = play_progression_tags(
            start_abs=start_abs,
            abs_after_clamped=abs_after,
            gain=gain,
            pre_distance=dist,
            earned_first_down=False,
            touchdown=False,
        )
        return SituationSnapshot(
            territory=new_t,
            yardline=new_y,
            down=1,
            distance=min(10, ytg),
            touchdown=False,
            change_of_possession=COP_TURNOVER_ON_DOWNS,
            tags=tags,
        )

    tags = play_progression_tags(
        start_abs=start_abs,
        abs_after_clamped=abs_after,
        gain=gain,
        pre_distance=dist,
        earned_first_down=False,
        touchdown=False,
    )
    return SituationSnapshot(
        territory=new_t,
        yardline=new_y,
        down=next_down,
        distance=next_dist,
        touchdown=False,
        change_of_possession=None,
        tags=tags,
    )


def classify_logged_outcome(
    *,
    yards: int,
    to_go: int,
    earned_first_down: bool,
    touchdown: bool,
) -> str:
    """
    Map yards + flags to a stable ``ActualPlayResult.result_type`` string for ``DriveLogger``.
    """
    if touchdown:
        return "touchdown"
    if earned_first_down:
        return "first_down_exact" if int(yards) == int(to_go) else "first_down"
    if int(yards) == 0:
        return "no_gain"
    if int(yards) < 0:
        return "sack" if int(yards) <= -4 else "negative"
    return "short"
