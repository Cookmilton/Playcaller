"""
Game session: multiple drives, Gamecast-style summaries.

Aggregates ``ActualPlayResult`` rows without changing the logging / advancement pipeline.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field, fields, replace
from typing import Any, Dict, List, Literal, Optional

from .domain import ActualPlayResult
from .possession import flipped_possession

logger = logging.getLogger(__name__)

# Drive ended how (stable keys for analytics / UI)
DRIVE_END_TOUCHDOWN = "touchdown"
DRIVE_END_FIELD_GOAL = "field_goal"
DRIVE_END_FIELD_GOAL_MISS = "field_goal_miss"
DRIVE_END_PUNT = "punt"
DRIVE_END_TURNOVER_INT = "turnover_interception"
DRIVE_END_TURNOVER_FUMBLE = "turnover_fumble"
DRIVE_END_TURNOVER_ON_DOWNS = "turnover_on_downs"
DRIVE_END_END_OF_HALF = "end_of_half"
DRIVE_END_END_OF_GAME = "end_of_game"
DRIVE_END_UNKNOWN = "unknown"

# Drive endings that change who has the ball (simplified: always flip offense ↔ defense).
# Terminal period markers are known non-scoring ends — no flip.
DRIVE_END_CHANGE_OF_POSSESSION_KINDS = frozenset(
    {
        DRIVE_END_TOUCHDOWN,
        DRIVE_END_FIELD_GOAL,
        DRIVE_END_FIELD_GOAL_MISS,
        DRIVE_END_PUNT,
        DRIVE_END_TURNOVER_INT,
        DRIVE_END_TURNOVER_FUMBLE,
        DRIVE_END_TURNOVER_ON_DOWNS,
    }
)

# Kinds allowed for explicit user override when completing a drive (includes ``unknown``).
DRIVE_END_OVERRIDE_KINDS = frozenset(
    {
        DRIVE_END_TOUCHDOWN,
        DRIVE_END_FIELD_GOAL,
        DRIVE_END_FIELD_GOAL_MISS,
        DRIVE_END_PUNT,
        DRIVE_END_TURNOVER_INT,
        DRIVE_END_TURNOVER_FUMBLE,
        DRIVE_END_TURNOVER_ON_DOWNS,
        DRIVE_END_END_OF_HALF,
        DRIVE_END_END_OF_GAME,
        DRIVE_END_UNKNOWN,
    }
)

# Sidebar / form ordering for “how did this drive end?” (values match ``DRIVE_END_*`` or ``auto``).
DRIVE_END_UI_AUTO = "auto"
DRIVE_END_UI_OPTIONS = (
    DRIVE_END_UI_AUTO,
    DRIVE_END_TOUCHDOWN,
    DRIVE_END_FIELD_GOAL,
    DRIVE_END_FIELD_GOAL_MISS,
    DRIVE_END_PUNT,
    DRIVE_END_TURNOVER_INT,
    DRIVE_END_TURNOVER_FUMBLE,
    DRIVE_END_TURNOVER_ON_DOWNS,
    DRIVE_END_END_OF_HALF,
    DRIVE_END_END_OF_GAME,
    DRIVE_END_UNKNOWN,
)
DRIVE_END_UI_LABELS = {
    DRIVE_END_UI_AUTO: "Auto (infer from plays & last snap)",
    DRIVE_END_TOUCHDOWN: "Touchdown",
    DRIVE_END_FIELD_GOAL: "Field goal (good)",
    DRIVE_END_FIELD_GOAL_MISS: "Field goal (missed)",
    DRIVE_END_PUNT: "Punt",
    DRIVE_END_TURNOVER_INT: "Interception",
    DRIVE_END_TURNOVER_FUMBLE: "Fumble",
    DRIVE_END_TURNOVER_ON_DOWNS: "Turnover on downs",
    DRIVE_END_END_OF_HALF: "End of half",
    DRIVE_END_END_OF_GAME: "End of game",
    DRIVE_END_UNKNOWN: "Other / unclear",
}

_GAME_JSON_VERSION = 1

_DRIVE_END_HEADLINE: Dict[str, str] = {
    DRIVE_END_TOUCHDOWN: "Touchdown",
    DRIVE_END_FIELD_GOAL: "Field goal",
    DRIVE_END_FIELD_GOAL_MISS: "Missed field goal",
    DRIVE_END_PUNT: "Punt",
    DRIVE_END_TURNOVER_INT: "Interception",
    DRIVE_END_TURNOVER_FUMBLE: "Fumble",
    DRIVE_END_TURNOVER_ON_DOWNS: "Turnover on downs",
    DRIVE_END_END_OF_HALF: "End of half",
    DRIVE_END_END_OF_GAME: "End of game",
    DRIVE_END_UNKNOWN: "Drive ended",
}


@dataclass
class DriveResult:
    """How the drive ended + Gamecast-style lines."""

    kind: str
    headline: str
    detail_line: str

    @property
    def full_line(self) -> str:
        return f"{self.headline} — {self.detail_line}"


@dataclass
class DriveFeedAuditSnapshot:
    """
    ESPN ``drives.previous[]`` fields captured at import for audits (optional).

    Down/distance at first scrimmage snap are often omitted from summary JSON; those
    fields stay empty unless we extend the ingest later.
    """

    espn_result_code: str = ""
    espn_display_result: str = ""
    espn_is_score: Optional[bool] = None
    start_period: Optional[int] = None
    start_clock_display: str = ""
    start_yard_line: Optional[int] = None
    start_field_text: str = ""
    feed_offensive_plays: Optional[int] = None
    feed_yards: Optional[int] = None
    time_elapsed_display: str = ""
    time_elapsed_seconds: Optional[int] = None
    first_play_period: Optional[int] = None
    first_play_clock_display: str = ""
    end_period: Optional[int] = None
    end_clock_display: str = ""
    end_field_text: str = ""
    # After TD: PAT / 2PT signal from drive play text (see ``espn_drive_audit_parse``).
    espn_td_extra_point: Optional[Literal["pat", "two_point", "pat_missed"]] = None


# Where ``Drive.result.kind`` came from (export / audit provenance).
OUTCOME_SOURCE_ESPN = "espn"
OUTCOME_SOURCE_INFERRED = "inferred"
OUTCOME_SOURCE_UNKNOWN = "unknown"
OutcomeSource = Literal["espn", "inferred", "unknown"]

# Where ``Drive.total_yards`` came from.
YARDS_SOURCE_ESPN = "espn"
YARDS_SOURCE_COMPUTED = "computed"
YardsSource = Literal["espn", "computed"]

# Where ``Drive.time_elapsed_seconds`` came from. Missing / not ``espn`` is untrusted.
TIME_SOURCE_ESPN = "espn"
TimeSource = Literal["espn"]


@dataclass
class Drive:
    plays: List[ActualPlayResult] = field(default_factory=list)
    total_yards: int = 0
    play_count: int = 0
    time_elapsed_seconds: Optional[int] = None
    result: Optional[DriveResult] = None
    # Team that had the ball for this drive: ``offense`` = OC / our team, ``defense`` = opponent on offense.
    possessing_team: str = "offense"
    # ``"espn"`` when assembled from ESPN completed-drive import (subtle UI badge only).
    feed_import_tag: Optional[str] = None
    # Possession team from feed (completed-drive import); drives UI / export only.
    feed_team_espn_id: str = ""
    feed_team_abbr: str = ""
    feed_team_display_name: str = ""
    # ESPN drive-level metadata (see :class:`DriveFeedAuditSnapshot`); ``None`` for manual archives.
    feed_audit: Optional["DriveFeedAuditSnapshot"] = None
    # Session snap-review counter at **End drive** (stable across ``game.drives`` re-sort). None for ESPN import.
    session_drive_epoch: Optional[int] = None
    # Provenance for ``result``: ESPN feed, play inference, or unresolved.
    outcome_source: Optional[str] = None
    # Play-sum yards (always computed); ``total_yards`` prefers ESPN ``yards`` when present.
    computed_yards: Optional[int] = None
    yards_source: Optional[str] = None
    # Shadow play-inferred kind (audit cross-check); never the exported primary outcome.
    inferred_kind: Optional[str] = None
    # Provenance for ``time_elapsed_seconds``. Only ``espn`` is a real duration.
    time_source: Optional[str] = None
    # Per-play estimate (``seconds_per_play * snaps``); shadow only — never the stored duration.
    inferred_time_seconds: Optional[int] = None

    def with_computed_stats(
        self,
        *,
        seconds_per_play: int = 38,
        result: Optional[DriveResult] = None,
    ) -> "Drive":
        from playcaller.live_data.espn_drive_audit_parse import parse_espn_time_elapsed_display
        from playcaller.play_event_segment import counts_as_offensive_snap, play_net_yards_for_drive

        computed = sum(play_net_yards_for_drive(p) for p in self.plays)
        n = sum(1 for p in self.plays if counts_as_offensive_snap(p))
        inferred_elapsed = max(0, int(seconds_per_play) * n)
        r = result if result is not None else self.result
        espn_yards = None
        if self.feed_audit is not None and self.feed_audit.feed_yards is not None:
            try:
                espn_yards = int(self.feed_audit.feed_yards)
            except (TypeError, ValueError):
                espn_yards = None
        if espn_yards is not None:
            total = espn_yards
            ysrc = YARDS_SOURCE_ESPN
        else:
            total = computed
            ysrc = YARDS_SOURCE_COMPUTED
        espn_sec: Optional[int] = None
        if self.feed_audit is not None:
            if self.feed_audit.time_elapsed_seconds is not None:
                try:
                    espn_sec = int(self.feed_audit.time_elapsed_seconds)
                except (TypeError, ValueError):
                    espn_sec = None
            if espn_sec is None:
                espn_sec = parse_espn_time_elapsed_display(self.feed_audit.time_elapsed_display)
        if espn_sec is not None:
            elapsed: Optional[int] = espn_sec
            tsrc: Optional[str] = TIME_SOURCE_ESPN
        else:
            elapsed = None
            tsrc = None
        return replace(
            self,
            total_yards=total,
            computed_yards=int(computed),
            yards_source=ysrc,
            play_count=n,
            time_elapsed_seconds=elapsed,
            time_source=tsrc,
            inferred_time_seconds=inferred_elapsed,
            result=r,
            possessing_team=self.possessing_team,
        )


@dataclass
class Game:
    """One session (e.g. one full game or one half)."""

    game_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    drives: List[Drive] = field(default_factory=list)
    offense_points: int = 0
    defense_points: int = 0
    # ``offense`` | ``defense`` | ``None`` (fresh / new-game board has no side yet).
    possession: Optional[str] = None
    quarter: int = 1
    clock_seconds_remaining: Optional[int] = None
    # Snap-level review timeline (model-at-Generate + optional ``linked_actual``); JSON ``snap_review_log`` alias.
    recommendation_audit: List[Dict[str, Any]] = field(default_factory=list)
    # Operator session identity (team, date, simulated vs real, …) — JSON ``session_metadata`` object.
    session_metadata: Optional[Dict[str, Any]] = None

    @property
    def snap_review_log(self) -> List[Dict[str, Any]]:
        """Same list as :attr:`recommendation_audit` (export primary key ``snap_review_log``)."""
        return self.recommendation_audit

    @classmethod
    def new_game(cls) -> "Game":
        from .session_game_metadata import fresh_session_metadata_dict

        return cls(
            game_id=str(uuid.uuid4())[:8],
            session_metadata=fresh_session_metadata_dict(),
        )


def drive_index_for_session_epoch(game: Game, epoch: int) -> Optional[int]:
    """
    List index of the archived drive tagged with ``session_drive_epoch``.

    After E2 re-sort, ``epoch`` is not a list position. When no drive is tagged
    (legacy JSON), fall back to treating ``epoch`` as an index.
    """
    drives = game.drives or []
    tagged = [i for i, d in enumerate(drives) if d.session_drive_epoch is not None]
    if tagged:
        for i in tagged:
            if drives[i].session_drive_epoch == int(epoch):
                return i
        return None
    if 0 <= int(epoch) < len(drives):
        return int(epoch)
    return None


def _fmt_drive_clock(seconds: int) -> str:
    s = max(0, int(seconds))
    m, sec = divmod(s, 60)
    return f"{m}:{sec:02d}"


def _drive_detail_line(
    plays: List[ActualPlayResult],
    *,
    seconds_per_play: int = 38,
) -> str:
    from playcaller.play_event_segment import counts_as_offensive_snap, play_net_yards_for_drive

    if not plays:
        return "0 plays, 0 yards, 0:00"
    snap_plays = [p for p in plays if counts_as_offensive_snap(p)]
    n = len(snap_plays)
    net = sum(play_net_yards_for_drive(p) for p in plays)
    elapsed_sec = max(0, int(seconds_per_play) * n)
    return f"{n} play{'s' if n != 1 else ''}, {net} yards, {_fmt_drive_clock(elapsed_sec)}"


def drive_result_for_kind(
    kind: str,
    plays: List[ActualPlayResult],
    *,
    seconds_per_play: int = 38,
) -> DriveResult:
    """Build a ``DriveResult`` for a known ``kind`` with the usual stats line."""
    k = str(kind)
    if k not in DRIVE_END_OVERRIDE_KINDS:
        k = DRIVE_END_UNKNOWN
    detail = _drive_detail_line(plays, seconds_per_play=seconds_per_play)
    headline = _DRIVE_END_HEADLINE.get(k, _DRIVE_END_HEADLINE[DRIVE_END_UNKNOWN])
    return DriveResult(kind=k, headline=headline, detail_line=detail)


def classify_drive_end(
    plays: List[ActualPlayResult],
    *,
    last_snap_touchdown: bool = False,
    last_snap_turnover_on_downs: bool = False,
    seconds_per_play: int = 38,
    end_kind_override: Optional[str] = None,
) -> DriveResult:
    """
    Determine drive end headline from the last play + last advancement snapshot flags.

    ``last_snap_*`` should reflect the situation **after** the final logged play.

    If ``end_kind_override`` is a valid ``DRIVE_END_*`` key in ``DRIVE_END_OVERRIDE_KINDS``, that outcome wins (explicit user classification).
    """
    override = (end_kind_override or "").strip()
    if override in DRIVE_END_OVERRIDE_KINDS:
        if not plays and override == DRIVE_END_UNKNOWN:
            return DriveResult(
                kind=DRIVE_END_UNKNOWN,
                headline="Empty drive",
                detail_line="0 plays, 0 yards, 0:00",
            )
        return drive_result_for_kind(override, plays, seconds_per_play=seconds_per_play)

    if not plays:
        return DriveResult(
            kind=DRIVE_END_UNKNOWN,
            headline="Empty drive",
            detail_line="0 plays, 0 yards, 0:00",
        )

    last = plays[-1]
    rt = (last.result_type or "").lower()
    tk = (last.turnover_kind or "").lower()
    pr = (last.pass_result or "").lower()

    detail = _drive_detail_line(plays, seconds_per_play=seconds_per_play)

    td = bool(last.touchdown) or bool(last_snap_touchdown)
    if td:
        return DriveResult(kind=DRIVE_END_TOUCHDOWN, headline="Touchdown", detail_line=detail)

    if rt == "interception" or tk == "interception" or pr == "intercepted":
        return DriveResult(
            kind=DRIVE_END_TURNOVER_INT,
            headline="Interception",
            detail_line=detail,
        )

    if tk == "fumble" or rt == "fumble":
        return DriveResult(
            kind=DRIVE_END_TURNOVER_FUMBLE,
            headline="Fumble",
            detail_line=detail,
        )

    if last_snap_turnover_on_downs:
        return DriveResult(
            kind=DRIVE_END_TURNOVER_ON_DOWNS,
            headline="Turnover on downs",
            detail_line=detail,
        )

    if rt == "field_goal_miss":
        return DriveResult(
            kind=DRIVE_END_FIELD_GOAL_MISS,
            headline="Missed field goal",
            detail_line=detail,
        )

    if rt == "field_goal" or (
        "field goal" in (last.concept_name or "").lower() and "miss" not in (last.concept_name or "").lower()
    ):
        return DriveResult(kind=DRIVE_END_FIELD_GOAL, headline="Field goal", detail_line=detail)

    if rt == "punt" or "punt" in (last.description or "").lower():
        return DriveResult(kind=DRIVE_END_PUNT, headline="Punt", detail_line=detail)

    if rt == "turnover_on_downs" or "turnover on downs" in (last.description or "").lower():
        return DriveResult(
            kind=DRIVE_END_TURNOVER_ON_DOWNS,
            headline="Turnover on downs",
            detail_line=detail,
        )

    # Honest unresolved end — never invent a punt when the last play does not say so.
    return DriveResult(kind=DRIVE_END_UNKNOWN, headline="Drive ended", detail_line=detail)


def _norm_possessing_team(raw: Optional[str]) -> str:
    """
    Coerce a drive's side to ``offense`` | ``defense``.

    ``Drive.possessing_team`` is not optional while ``Game.possession`` is, so an unset board
    still lands on ``offense`` here. Every UI path into this fallback is gated
    (:func:`playcaller.possession.end_drive_blocked_reason`), so a warning means either a
    non-UI caller or a regression in that gate.
    """
    t = (raw or "").strip().lower()
    if t in ("offense", "defense"):
        return t
    logger.warning(
        "playcaller: Drive.possessing_team coerced %r -> 'offense'; "
        "End drive should be blocked while Game.possession is unset.",
        raw,
    )
    return "offense"


def complete_drive_from_plays(
    plays: List[ActualPlayResult],
    *,
    last_snap_touchdown: bool = False,
    last_snap_turnover_on_downs: bool = False,
    seconds_per_play: int = 38,
    end_kind_override: Optional[str] = None,
    possessing_team: Optional[str] = "offense",
    feed_team_espn_id: str = "",
    feed_team_abbr: str = "",
    feed_team_display_name: str = "",
    feed_audit: Optional[DriveFeedAuditSnapshot] = None,
) -> Drive:
    """Build a finished ``Drive`` with stats + ``DriveResult``.

    When ``feed_audit`` carries an ESPN drive result, that outcome wins (completed-drive
    import). Explicit ``end_kind_override`` still wins over ESPN. Play inference is the
    fallback when ESPN is absent or unmapped. ``inferred_kind`` always stores the
    play-inferred shadow for audit (never the exported primary when ESPN wins).
    """
    base = Drive(
        plays=list(plays),
        possessing_team=_norm_possessing_team(possessing_team),
        feed_team_espn_id=str(feed_team_espn_id or ""),
        feed_team_abbr=str(feed_team_abbr or ""),
        feed_team_display_name=str(feed_team_display_name or ""),
        feed_audit=feed_audit,
    )
    play_inferred = classify_drive_end(
        base.plays,
        last_snap_touchdown=last_snap_touchdown,
        last_snap_turnover_on_downs=last_snap_turnover_on_downs,
        seconds_per_play=seconds_per_play,
        end_kind_override=None,
    )
    override = (end_kind_override or "").strip()
    if override in DRIVE_END_OVERRIDE_KINDS:
        res = classify_drive_end(
            base.plays,
            last_snap_touchdown=last_snap_touchdown,
            last_snap_turnover_on_downs=last_snap_turnover_on_downs,
            seconds_per_play=seconds_per_play,
            end_kind_override=override,
        )
        outcome_source = (
            OUTCOME_SOURCE_UNKNOWN if res.kind == DRIVE_END_UNKNOWN else OUTCOME_SOURCE_INFERRED
        )
        shadow_kind = play_inferred.kind
    else:
        from playcaller.espn_drive_outcome import drive_result_kind_from_espn_audit

        espn_kind, _bucket = drive_result_kind_from_espn_audit(feed_audit)
        if espn_kind is not None:
            res = drive_result_for_kind(espn_kind, base.plays, seconds_per_play=seconds_per_play)
            outcome_source = OUTCOME_SOURCE_ESPN
            shadow_kind = play_inferred.kind
        else:
            res = play_inferred
            outcome_source = (
                OUTCOME_SOURCE_UNKNOWN if res.kind == DRIVE_END_UNKNOWN else OUTCOME_SOURCE_INFERRED
            )
            shadow_kind = play_inferred.kind
    finished = base.with_computed_stats(seconds_per_play=seconds_per_play, result=res)
    return replace(finished, outcome_source=outcome_source, inferred_kind=str(shadow_kind))


def clock_seconds_after_drive_elapsed(current_clock_seconds: int, drive: Drive) -> int:
    """Subtract ESPN drive duration from the game clock (non-negative).

    When ``time_elapsed_seconds`` is missing, leave the clock unchanged — never
    subtract the per-play estimate.
    """
    elapsed = drive.time_elapsed_seconds
    if elapsed is None:
        return max(0, int(current_clock_seconds))
    return max(0, int(current_clock_seconds) - int(elapsed))


def flip_possession_after_drive(game: Game, drive: Drive) -> None:
    """Flip ``game.possession`` after a drive that changes who has the ball (unknown stays unknown)."""
    if drive.result is None or drive.result.kind == DRIVE_END_UNKNOWN:
        return
    if drive.result.kind not in DRIVE_END_CHANGE_OF_POSSESSION_KINDS:
        return
    game.possession = flipped_possession(game.possession)


def _actual_play_from_dict(d: Dict[str, Any]) -> ActualPlayResult:
    names = {f.name for f in fields(ActualPlayResult)}
    return ActualPlayResult(**{k: v for k, v in d.items() if k in names})


def _drive_result_from_dict(d: Optional[Dict[str, Any]]) -> Optional[DriveResult]:
    if not d:
        return None
    return DriveResult(
        kind=str(d.get("kind", DRIVE_END_UNKNOWN)),
        headline=str(d.get("headline", "")),
        detail_line=str(d.get("detail_line", "")),
    )


def _drive_feed_audit_from_dict(d: Optional[Dict[str, Any]]) -> Optional[DriveFeedAuditSnapshot]:
    if not d or not isinstance(d, dict):
        return None
    names = {f.name for f in fields(DriveFeedAuditSnapshot)}
    return DriveFeedAuditSnapshot(**{k: v for k, v in d.items() if k in names})


def _drive_from_dict(d: Dict[str, Any]) -> Drive:
    plays = [_actual_play_from_dict(p) for p in (d.get("plays") or [])]
    dr = _drive_result_from_dict(d.get("result"))
    out = Drive(
        plays=plays,
        total_yards=int(d.get("total_yards", 0)),
        play_count=int(d.get("play_count", 0)),
        time_elapsed_seconds=_json_opt_int(d.get("time_elapsed_seconds")),
        result=dr,
        possessing_team=_norm_possessing_team(str(d.get("possessing_team", "offense"))),
        feed_import_tag=(str(ftag) if (ftag := d.get("feed_import_tag")) else None),
        feed_team_espn_id=str(d.get("feed_team_espn_id") or ""),
        feed_team_abbr=str(d.get("feed_team_abbr") or ""),
        feed_team_display_name=str(d.get("feed_team_display_name") or ""),
        feed_audit=_drive_feed_audit_from_dict(d.get("feed_audit")),
        session_drive_epoch=_json_opt_session_epoch(d.get("session_drive_epoch")),
        outcome_source=_json_opt_outcome_source(d.get("outcome_source")),
        computed_yards=_json_opt_int(d.get("computed_yards")),
        yards_source=_json_opt_yards_source(d.get("yards_source")),
        inferred_kind=_json_opt_inferred_kind(d.get("inferred_kind")),
        time_source=_json_opt_time_source(d.get("time_source")),
        inferred_time_seconds=_json_opt_int(d.get("inferred_time_seconds")),
    )
    return out


def _json_opt_time_source(raw: Any) -> Optional[str]:
    s = str(raw or "").strip().lower()
    if s == TIME_SOURCE_ESPN:
        return s
    return None


def _json_opt_inferred_kind(raw: Any) -> Optional[str]:
    s = str(raw or "").strip()
    return s or None


def _json_opt_int(raw: Any) -> Optional[int]:
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _json_opt_yards_source(raw: Any) -> Optional[str]:
    s = str(raw or "").strip().lower()
    if s in (YARDS_SOURCE_ESPN, YARDS_SOURCE_COMPUTED):
        return s
    return None


def _json_opt_outcome_source(raw: Any) -> Optional[str]:
    s = str(raw or "").strip().lower()
    if s in (OUTCOME_SOURCE_ESPN, OUTCOME_SOURCE_INFERRED, OUTCOME_SOURCE_UNKNOWN):
        return s
    return None


def _json_opt_session_epoch(raw: Any) -> Optional[int]:
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def game_to_dict(game: Game) -> Dict[str, Any]:
    """Structured dict suitable for JSON (``game_to_json``)."""
    from playcaller.review.snap_review import SNAP_REVIEW_LOG_EXPORT_KEY

    audit_list = list(game.recommendation_audit or [])
    payload: Dict[str, Any] = {
        "schema_version": _GAME_JSON_VERSION,
        "game_id": game.game_id,
    }
    if game.session_metadata:
        payload["session_metadata"] = dict(game.session_metadata)
    # Primary review timeline key first; legacy ``recommendation_audit`` mirrors the same list.
    payload.update(
        {
            "offense_points": game.offense_points,
            "defense_points": game.defense_points,
            "possession": game.possession,
            "quarter": game.quarter,
            "clock_seconds_remaining": game.clock_seconds_remaining,
            SNAP_REVIEW_LOG_EXPORT_KEY: list(audit_list),
            "recommendation_audit": audit_list,
            "drives": [],
        }
    )
    for dr in game.drives:
        res = dr.result
        row = {
            "plays": [asdict(p) for p in dr.plays],
            "total_yards": dr.total_yards,
            "play_count": dr.play_count,
            "time_elapsed_seconds": dr.time_elapsed_seconds,
            "possessing_team": dr.possessing_team,
            "result": asdict(res) if res else None,
        }
        if dr.feed_import_tag:
            row["feed_import_tag"] = dr.feed_import_tag
        if dr.feed_team_espn_id:
            row["feed_team_espn_id"] = dr.feed_team_espn_id
        if dr.feed_team_abbr:
            row["feed_team_abbr"] = dr.feed_team_abbr
        if dr.feed_team_display_name:
            row["feed_team_display_name"] = dr.feed_team_display_name
        if dr.feed_audit:
            row["feed_audit"] = asdict(dr.feed_audit)
        if dr.session_drive_epoch is not None:
            row["session_drive_epoch"] = int(dr.session_drive_epoch)
        if dr.outcome_source:
            row["outcome_source"] = str(dr.outcome_source)
        if dr.computed_yards is not None:
            row["computed_yards"] = int(dr.computed_yards)
        if dr.yards_source:
            row["yards_source"] = str(dr.yards_source)
        if dr.inferred_kind:
            row["inferred_kind"] = str(dr.inferred_kind)
        payload["drives"].append(row)
    return payload


def _possession_from_export(data: Dict[str, Any]) -> Optional[str]:
    """Legacy saves omit the key (treat as offense). Explicit null is unset."""
    # Key absent = pre-``Optional[possession]`` file whose app default was always offense;
    # explicit ``null`` = a board the operator (or a fresh game) left unset.
    if "possession" not in data:
        return "offense"
    raw = data.get("possession")
    if raw is None or str(raw).strip() == "":
        return None
    return str(raw)


def game_from_dict(data: Dict[str, Any]) -> Game:
    """Restore a ``Game`` from ``game_to_dict`` output."""
    from playcaller.review.snap_review import snap_review_rows_from_export

    drives_raw = data.get("drives") or []
    drives = [_drive_from_dict(x) for x in drives_raw]
    audit: List[Dict[str, Any]] = snap_review_rows_from_export(data)
    sm_raw = data.get("session_metadata")
    session_metadata: Optional[Dict[str, Any]] = dict(sm_raw) if isinstance(sm_raw, dict) else None
    return Game(
        game_id=str(data.get("game_id") or str(uuid.uuid4())[:8]),
        drives=drives,
        offense_points=int(data.get("offense_points", 0)),
        defense_points=int(data.get("defense_points", 0)),
        possession=_possession_from_export(data),
        quarter=int(data.get("quarter", 1)),
        clock_seconds_remaining=data.get("clock_seconds_remaining"),
        recommendation_audit=audit,
        session_metadata=session_metadata,
    )


def game_to_json(game: Game, *, indent: int = 2) -> str:
    return json.dumps(game_to_dict(game), indent=indent)


def game_from_json(s: str) -> Game:
    return game_from_dict(json.loads(s))


def apply_scoring_after_drive(game: Game, drive: Drive) -> None:
    """Apply TD (+6) or made FG (+3) to the team that possessed the ball on this drive."""
    if drive.result is None:
        return
    team = _norm_possessing_team(getattr(drive, "possessing_team", "offense"))
    rk = drive.result.kind
    if rk == DRIVE_END_TOUCHDOWN:
        if team == "offense":
            game.offense_points += 6
        else:
            game.defense_points += 6
    elif rk == DRIVE_END_FIELD_GOAL:
        if team == "offense":
            game.offense_points += 3
        else:
            game.defense_points += 3


__all__ = [
    "DRIVE_END_CHANGE_OF_POSSESSION_KINDS",
    "DRIVE_END_FIELD_GOAL",
    "DRIVE_END_FIELD_GOAL_MISS",
    "DRIVE_END_OVERRIDE_KINDS",
    "DRIVE_END_UI_AUTO",
    "DRIVE_END_UI_LABELS",
    "DRIVE_END_UI_OPTIONS",
    "DRIVE_END_PUNT",
    "DRIVE_END_TOUCHDOWN",
    "DRIVE_END_TURNOVER_FUMBLE",
    "DRIVE_END_TURNOVER_INT",
    "DRIVE_END_TURNOVER_ON_DOWNS",
    "DRIVE_END_END_OF_HALF",
    "DRIVE_END_END_OF_GAME",
    "DRIVE_END_UNKNOWN",
    "OUTCOME_SOURCE_ESPN",
    "OUTCOME_SOURCE_INFERRED",
    "OUTCOME_SOURCE_UNKNOWN",
    "YARDS_SOURCE_COMPUTED",
    "YARDS_SOURCE_ESPN",
    "TIME_SOURCE_ESPN",
    "Drive",
    "DriveFeedAuditSnapshot",
    "DriveResult",
    "Game",
    "apply_scoring_after_drive",
    "classify_drive_end",
    "clock_seconds_after_drive_elapsed",
    "complete_drive_from_plays",
    "flip_possession_after_drive",
    "drive_result_for_kind",
    "game_from_dict",
    "game_from_json",
    "game_to_dict",
    "game_to_json",
]
