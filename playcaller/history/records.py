"""
Types for offline historical game data (no live session, no recommendation engine wiring).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict, List, Optional

from playcaller.domain import ActualPlayResult


_ACTUAL_FIELD_NAMES = {f.name for f in fields(ActualPlayResult)}


@dataclass(frozen=True)
class NormalizedHistoricalPlay:
    """
    One logged play with optional recommendation + pre-snap context from ``recommendation_audit``.

    Fields are flat for later similarity search. ``None`` means unknown or not present in source JSON.
    """

    # --- Provenance ---
    source_path: str
    game_id: str
    game_label: Optional[str]
    schema_version: Optional[int]
    drive_index: int
    play_index: int
    absolute_snap_index: int
    possessing_team: str

    # --- Pre-snap context (from audit ``pre_snap`` / ``GameContext`` export) ---
    quarter: Optional[int]
    clock_seconds_remaining: Optional[int]
    down: Optional[int]
    distance: Optional[int]
    territory: Optional[str]
    yardline: Optional[int]
    yardline_100: Optional[int]
    field_zone: Optional[str]
    score_diff: Optional[int]
    situation_bucket: Optional[str]
    distance_bucket: Optional[str]

    # --- Recommendation (from audit row when matched to this play) ---
    audit_snap_id: Optional[str]
    audit_drive_epoch: Optional[int]
    audit_plays_at_recommend: Optional[int]
    recommendation_status: Optional[str]
    recommended_family: Optional[str]
    recommended_play_name: Optional[str]
    recommendation_bucket: Optional[str]
    family_match: Optional[bool]

    # --- Actual result (always from drive ``plays[]``) ---
    actual: ActualPlayResult

    # --- Derived flags (deterministic; see ``normalize.py``) ---
    play_success: Optional[bool]
    explosive_play: bool

    # --- Debug / audit trail ---
    raw_audit_ref: Optional[Dict[str, Any]] = None

    # --- Session game identity (from ``Game.session_metadata`` on export) ---
    session_game_id: Optional[str] = None
    session_team_name: Optional[str] = None
    session_opponent: Optional[str] = None
    session_game_date: Optional[str] = None
    session_game_label: Optional[str] = None
    session_season: Optional[str] = None
    session_roster_version: Optional[str] = None
    session_is_simulated: Optional[bool] = None

    # Set when rows are materialized from the on-disk history repository.
    repository_game_id: Optional[str] = None

    @property
    def record_key(self) -> str:
        return f"{self.source_path}::{self.game_id}::{self.drive_index}:{self.play_index}"

    def to_flat_dict(self) -> Dict[str, Any]:
        """Row dict for Parquet/CSV/export."""
        out: Dict[str, Any] = {
            "record_key": self.record_key,
            "source_path": self.source_path,
            "repository_game_id": self.repository_game_id,
            "game_id": self.game_id,
            "game_label": self.game_label,
            "schema_version": self.schema_version,
            "drive_index": self.drive_index,
            "play_index": self.play_index,
            "absolute_snap_index": self.absolute_snap_index,
            "possessing_team": self.possessing_team,
            "quarter": self.quarter,
            "clock_seconds_remaining": self.clock_seconds_remaining,
            "down": self.down,
            "distance": self.distance,
            "territory": self.territory,
            "yardline": self.yardline,
            "yardline_100": self.yardline_100,
            "field_zone": self.field_zone,
            "score_diff": self.score_diff,
            "situation_bucket": self.situation_bucket,
            "distance_bucket": self.distance_bucket,
            "audit_snap_id": self.audit_snap_id,
            "audit_drive_epoch": self.audit_drive_epoch,
            "audit_plays_at_recommend": self.audit_plays_at_recommend,
            "recommendation_status": self.recommendation_status,
            "recommended_family": self.recommended_family,
            "recommended_play_name": self.recommended_play_name,
            "recommendation_bucket": self.recommendation_bucket,
            "family_match": self.family_match,
            "play_success": self.play_success,
            "explosive_play": self.explosive_play,
            "session_game_id": self.session_game_id,
            "session_team_name": self.session_team_name,
            "session_opponent": self.session_opponent,
            "session_game_date": self.session_game_date,
            "session_game_label": self.session_game_label,
            "session_season": self.session_season,
            "session_roster_version": self.session_roster_version,
            "session_is_simulated": self.session_is_simulated,
        }
        out.update({f"actual_{k}": v for k, v in asdict(self.actual).items()})
        return out


def normalized_historical_play_to_json_dict(row: NormalizedHistoricalPlay) -> Dict[str, Any]:
    """Lossless JSON object for one normalized row (e.g. JSONL in the repository)."""
    return {
        "source_path": row.source_path,
        "repository_game_id": row.repository_game_id,
        "game_id": row.game_id,
        "game_label": row.game_label,
        "schema_version": row.schema_version,
        "drive_index": row.drive_index,
        "play_index": row.play_index,
        "absolute_snap_index": row.absolute_snap_index,
        "possessing_team": row.possessing_team,
        "quarter": row.quarter,
        "clock_seconds_remaining": row.clock_seconds_remaining,
        "down": row.down,
        "distance": row.distance,
        "territory": row.territory,
        "yardline": row.yardline,
        "yardline_100": row.yardline_100,
        "field_zone": row.field_zone,
        "score_diff": row.score_diff,
        "situation_bucket": row.situation_bucket,
        "distance_bucket": row.distance_bucket,
        "audit_snap_id": row.audit_snap_id,
        "audit_drive_epoch": row.audit_drive_epoch,
        "audit_plays_at_recommend": row.audit_plays_at_recommend,
        "recommendation_status": row.recommendation_status,
        "recommended_family": row.recommended_family,
        "recommended_play_name": row.recommended_play_name,
        "recommendation_bucket": row.recommendation_bucket,
        "family_match": row.family_match,
        "play_success": row.play_success,
        "explosive_play": row.explosive_play,
        "session_game_id": row.session_game_id,
        "session_team_name": row.session_team_name,
        "session_opponent": row.session_opponent,
        "session_game_date": row.session_game_date,
        "session_game_label": row.session_game_label,
        "session_season": row.session_season,
        "session_roster_version": row.session_roster_version,
        "session_is_simulated": row.session_is_simulated,
        "actual": asdict(row.actual),
        "raw_audit_ref": row.raw_audit_ref,
    }


def _json_opt_int(x: Any) -> Optional[int]:
    if x is None:
        return None
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def normalized_historical_play_from_json_dict(d: Dict[str, Any]) -> NormalizedHistoricalPlay:
    """Inverse of ``normalized_historical_play_to_json_dict``."""
    ad = d.get("actual")
    if not isinstance(ad, dict):
        ad = {}
    actual = ActualPlayResult(**{k: v for k, v in ad.items() if k in _ACTUAL_FIELD_NAMES})
    raw_ref = d.get("raw_audit_ref")
    if raw_ref is not None and not isinstance(raw_ref, dict):
        raw_ref = None
    rid = d.get("repository_game_id")
    return NormalizedHistoricalPlay(
        source_path=str(d.get("source_path") or ""),
        game_id=str(d.get("game_id") or ""),
        game_label=d.get("game_label"),
        schema_version=_json_opt_int(d.get("schema_version")),
        drive_index=int(d.get("drive_index", 0) or 0),
        play_index=int(d.get("play_index", 0) or 0),
        absolute_snap_index=int(d.get("absolute_snap_index", 0) or 0),
        possessing_team=str(d.get("possessing_team") or "offense"),
        quarter=_json_opt_int(d.get("quarter")),
        clock_seconds_remaining=_json_opt_int(d.get("clock_seconds_remaining")),
        down=_json_opt_int(d.get("down")),
        distance=_json_opt_int(d.get("distance")),
        territory=d.get("territory") if d.get("territory") is None else str(d.get("territory")),
        yardline=_json_opt_int(d.get("yardline")),
        yardline_100=_json_opt_int(d.get("yardline_100")),
        field_zone=d.get("field_zone") if d.get("field_zone") is None else str(d.get("field_zone")),
        score_diff=_json_opt_int(d.get("score_diff")),
        situation_bucket=d.get("situation_bucket"),
        distance_bucket=d.get("distance_bucket"),
        audit_snap_id=d.get("audit_snap_id") if d.get("audit_snap_id") is None else str(d.get("audit_snap_id")),
        audit_drive_epoch=_json_opt_int(d.get("audit_drive_epoch")),
        audit_plays_at_recommend=_json_opt_int(d.get("audit_plays_at_recommend")),
        recommendation_status=d.get("recommendation_status"),
        recommended_family=d.get("recommended_family"),
        recommended_play_name=d.get("recommended_play_name"),
        recommendation_bucket=d.get("recommendation_bucket"),
        family_match=(None if d.get("family_match") is None else bool(d.get("family_match"))),
        actual=actual,
        play_success=(None if d.get("play_success") is None else bool(d.get("play_success"))),
        explosive_play=bool(d.get("explosive_play", False)),
        raw_audit_ref=raw_ref,
        session_game_id=(
            None
            if d.get("session_game_id") is None
            else (str(d.get("session_game_id")).strip() or None)
        ),
        session_team_name=(
            None if d.get("session_team_name") is None else str(d.get("session_team_name"))
        ),
        session_opponent=(
            None if d.get("session_opponent") is None else str(d.get("session_opponent"))
        ),
        session_game_date=(
            None if d.get("session_game_date") is None else str(d.get("session_game_date"))
        ),
        session_game_label=(
            None if d.get("session_game_label") is None else str(d.get("session_game_label"))
        ),
        session_season=None if d.get("session_season") is None else str(d.get("session_season")),
        session_roster_version=(
            None if d.get("session_roster_version") is None else str(d.get("session_roster_version"))
        ),
        session_is_simulated=(
            None if d.get("session_is_simulated") is None else bool(d.get("session_is_simulated"))
        ),
        repository_game_id=str(rid) if rid is not None and str(rid).strip() else None,
    )


@dataclass(frozen=True)
class HistoricalGameSnapshot:
    """One successfully parsed game file."""

    game_id: str
    source_path: str
    schema_version: Optional[int]
    game_label: Optional[str]
    offense_points: int
    defense_points: int
    drive_count: int
    play_count: int
    audit_row_count: int
    session_game_id: Optional[str] = None
    session_is_simulated: Optional[bool] = None


@dataclass(frozen=True)
class GameJsonLoadError:
    path: str
    message: str


@dataclass
class HistoryCorpus:
    """Scan result: normalized plays, per-file summaries, and non-fatal load errors."""

    plays: List[NormalizedHistoricalPlay] = field(default_factory=list)
    games: List[HistoricalGameSnapshot] = field(default_factory=list)
    errors: List[GameJsonLoadError] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
