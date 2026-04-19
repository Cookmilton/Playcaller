"""
Structured rows for archived-drive **model replay** vs **actual** — safe for JSON and future Review Session use.

These objects describe **retroactive** replay only; they are not stored historical model output.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class PreSnapContextRecord:
    """Reconstructed (or overlay) pre-snap situation for one archived play."""

    territory: str
    yardline: int
    down: int
    distance: int
    quarter: int
    seconds_remaining: int
    score_diff: int
    own_timeouts: int
    opp_timeouts: int
    plays_this_drive_before_snap: int
    reconstruction_anchor: str
    reconstruction_notes: str = ""
    # Overlay fields copied from live session (approximate for history)
    def_personnel: str = ""
    coverage_shell: str = ""
    weather: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModelReplayStructuredResult:
    """Subset of ``predictor.recommend`` output — interpretable, JSON-safe."""

    play_family: str
    play_call_name: str
    bucket: str
    run_pass: Optional[str]
    confidence: Optional[float]
    summary_bucket: str = ""
    model_name: str = ""
    model_version: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ActualVsReplayComparisonRow:
    """
    One play in an archived drive: actual truth vs **current-model** replay.

    Use :meth:`to_dict` for analysis pipelines; do not treat ``model_replay_structured`` as audit history.
    """

    play_index: int
    pre_snap_context: PreSnapContextRecord
    actual_play_summary_primary: str
    actual_play_summary_detail: str
    actual_structured_result: Dict[str, Any]
    model_replay_summary: str
    model_replay_structured: Optional[ModelReplayStructuredResult]
    actual_run_pass: Optional[str]
    model_run_pass: Optional[str]
    run_pass_match: Optional[bool]
    family_match: Optional[bool]
    actual_summary_bucket: str = ""
    replay_summary_bucket: str = ""
    coarse_bucket_match: Optional[bool] = None
    chain_error: Optional[str] = None
    replay_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "play_index": self.play_index,
            "pre_snap_context": self.pre_snap_context.to_dict(),
            "actual_play_summary_primary": self.actual_play_summary_primary,
            "actual_play_summary_detail": self.actual_play_summary_detail,
            "actual_structured_result": dict(self.actual_structured_result),
            "actual_summary_bucket": self.actual_summary_bucket,
            "replay_summary_bucket": self.replay_summary_bucket,
            "coarse_bucket_match": self.coarse_bucket_match,
            "model_replay_summary": self.model_replay_summary,
            "model_replay_structured": self.model_replay_structured.to_dict()
            if self.model_replay_structured
            else None,
            "actual_run_pass": self.actual_run_pass,
            "model_run_pass": self.model_run_pass,
            "run_pass_match": self.run_pass_match,
            "family_match": self.family_match,
            "chain_error": self.chain_error,
            "replay_error": self.replay_error,
        }


def comparison_table_to_dicts(rows: List[ActualVsReplayComparisonRow]) -> List[Dict[str, Any]]:
    return [r.to_dict() for r in rows]
