"""Processed JSON → tiered similarity → advisory play-type frequencies (parallel to rule-based)."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, Optional

from warehouse.debug import _parse_feature, _parse_play
from warehouse.features import _distance_bucket, _field_zone, _score_diff_bucket
from warehouse.models import DerivedPlayFeatures, Play
from warehouse.storage import processed_data_dir
from warehouse.taxonomy import PlayType

_log = logging.getLogger(__name__)
_CACHED_POOL: Optional["PlayPool"] = None
_CACHED_POOL_ROOT: Optional[Path] = None

FLAG_ENV_VAR: Final = "WAREHOUSE_RECOMMENDER_ENABLED"
N_TOP: Final = 5
N_THRESHOLD: Final = 10
EXCLUDE_PLAY_TYPES: Final[frozenset[PlayType]] = frozenset(
    {
        PlayType.KICKOFF,
        PlayType.PUNT,
        PlayType.EXTRA_POINT,
        PlayType.TWO_POINT,
        PlayType.PENALTY_NO_PLAY,
    }
)


def is_enabled() -> bool:
    return os.environ.get(FLAG_ENV_VAR, "").strip().lower() in ("1", "true", "yes")


def get_cached_pool(root: Path | None = None) -> "PlayPool":
    """Return a shared PlayPool, loading once per process. Different ``root`` forces reload (tests)."""
    global _CACHED_POOL, _CACHED_POOL_ROOT
    effective = root if root is not None else processed_data_dir()
    if _CACHED_POOL is None or _CACHED_POOL_ROOT != effective:
        _CACHED_POOL = PlayPool.from_processed_dir(effective, seasons=None)
        _CACHED_POOL_ROOT = effective
    return _CACHED_POOL


def clear_cached_pool() -> None:
    global _CACHED_POOL, _CACHED_POOL_ROOT
    _CACHED_POOL = None
    _CACHED_POOL_ROOT = None


@dataclass(slots=True)
class Situation:
    down: int
    distance_bucket: str
    field_zone: str
    score_diff_bucket: str
    game_script: str


def situation_from_game_context(ctx: object) -> Situation:
    y100 = _territory_yardline_100(str(getattr(ctx, "territory")), int(getattr(ctx, "yardline")))
    if y100 is None:
        raise ValueError("territory/yardline must yield yardline_100")
    sd = int(getattr(ctx, "score_diff"))
    return Situation(
        int(getattr(ctx, "down")),
        _distance_bucket(int(getattr(ctx, "distance"))),
        _field_zone(y100),
        _score_diff_bucket(sd),
        _game_script_for_situation(sd, int(getattr(ctx, "quarter")), int(getattr(ctx, "seconds_remaining"))),
    )


def _territory_yardline_100(territory: str, yardline: int) -> int | None:
    t = territory.strip().lower()
    y = max(1, min(50, int(yardline)))
    if t == "opponents":
        return y
    if t == "own":
        return 100 - y
    return None


def _game_script_for_situation(score_diff: int, quarter: int, clock_seconds: int) -> str:
    raw_remaining = (4 - quarter) * 900 + clock_seconds
    gsr = max(0, raw_remaining)
    if score_diff >= 14 and gsr <= 900 and quarter == 4:
        return "protect_lead"
    if score_diff <= -14 and gsr <= 900:
        return "desperate"
    if score_diff <= -8:
        return "catch_up"
    if score_diff >= 8:
        return "protect_lead"
    return "neutral"


@dataclass(slots=True)
class CandidatePlay:
    play_type: PlayType
    frequency: float
    success_rate: float
    avg_epa: float
    sample_count: int


@dataclass(slots=True)
class HistoricalRecommendation:
    situation: Situation
    status: Literal["confident", "fallback", "insufficient"]
    tier_used: int
    sample_size: int
    candidates: list[CandidatePlay]
    note: str


def _log_safe_key(s: Situation) -> str:
    return (
        f"down={s.down},dist={s.distance_bucket},zone={s.field_zone},"
        f"score={s.score_diff_bucket},script={s.game_script}"
    )


def _log_match_outcome(situation: Situation, result: HistoricalRecommendation) -> None:
    _log.info(
        "recommender_match status=%s tier=%d sample_size=%d key=%s",
        result.status,
        result.tier_used,
        result.sample_size,
        _log_safe_key(situation),
    )


class PlayPool:
    __slots__ = ("_root", "_seasons", "_rows")

    def __init__(self, root: Path, seasons: list[int] | None = None) -> None:
        self._root = root
        self._seasons = seasons
        self._rows: list[tuple[Play, DerivedPlayFeatures]] | None = None

    @classmethod
    def from_processed_dir(cls, root: Path, seasons: list[int] | None = None) -> PlayPool:
        return cls(root, seasons)

    def _ensure_loaded(self) -> None:
        if self._rows is not None:
            return
        out: list[tuple[Play, DerivedPlayFeatures]] = []
        for path in self._iter_json_files():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            for pr, fr in zip(data.get("plays") or [], data.get("features") or []):
                try:
                    pl, fe = _parse_play(pr), _parse_feature(fr)
                except (KeyError, TypeError, ValueError):
                    continue
                if pl.play_type in EXCLUDE_PLAY_TYPES or pl.down is None:
                    continue
                out.append((pl, fe))
        self._rows = out

    def _iter_json_files(self) -> list[Path]:
        if not self._root.is_dir():
            return []
        if self._seasons is None:
            return sorted(self._root.rglob("*.json"))
        files: list[Path] = []
        for s in self._seasons:
            bd = self._root / str(s)
            if bd.is_dir():
                files.extend(sorted(bd.rglob("*.json")))
        return files


def _row_matches_tier(row: tuple[Play, DerivedPlayFeatures], s: Situation, tier: int) -> bool:
    p, f = row
    if int(p.down) != s.down:
        return False
    if tier >= 5:
        return True
    if tier == 4:
        return f.field_zone == s.field_zone and f.distance_bucket != "short"
    if tier == 3:
        return f.distance_bucket == s.distance_bucket and f.field_zone == s.field_zone
    if tier == 2:
        return (
            f.distance_bucket == s.distance_bucket
            and f.field_zone == s.field_zone
            and f.score_diff_bucket == s.score_diff_bucket
        )
    return (
        f.distance_bucket == s.distance_bucket
        and f.field_zone == s.field_zone
        and f.score_diff_bucket == s.score_diff_bucket
        and f.game_script == s.game_script
    )


def match(situation: Situation, pool: PlayPool) -> HistoricalRecommendation:
    pool._ensure_loaded()
    rows = pool._rows or []
    best_fb: tuple[int, int, list[tuple[Play, DerivedPlayFeatures]]] | None = None
    for ti in range(1, 6):
        got = [x for x in rows if _row_matches_tier(x, situation, ti)]
        n = len(got)
        if n >= N_THRESHOLD:
            result = _finalize(situation, "confident", ti, got, relaxed=False)
            _log_match_outcome(situation, result)
            return result
        if 1 <= n < N_THRESHOLD:
            if best_fb is None or n > best_fb[1] or (n == best_fb[1] and ti > best_fb[0]):
                best_fb = (ti, n, got)
    if best_fb is not None:
        ti, _, got = best_fb
        result = _finalize(situation, "fallback", ti, got, relaxed=True)
        _log_match_outcome(situation, result)
        return result
    result = HistoricalRecommendation(
        situation=situation,
        status="insufficient",
        tier_used=0,
        sample_size=0,
        candidates=[],
        note="No similar processed plays in the corpus for this situation.",
    )
    _log_match_outcome(situation, result)
    return result


def _finalize(
    situation: Situation,
    status: Literal["confident", "fallback"],
    tier: int,
    play_rows: list[tuple[Play, DerivedPlayFeatures]],
    *,
    relaxed: bool,
) -> HistoricalRecommendation:
    by_type: dict[PlayType, list[Play]] = {}
    for p, _f in play_rows:
        by_type.setdefault(p.play_type, []).append(p)
    cand: list[CandidatePlay] = []
    ntot = len(play_rows)
    for pt, plist in by_type.items():
        m = len(plist)
        succ = [p for p in plist if p.success is not None]
        sr = sum(1 for p in succ if p.success is True) / len(succ) if succ else 0.0
        epas = [p.epa for p in plist if p.epa is not None]
        avge = sum(epas) / len(epas) if epas else 0.0
        cand.append(
            CandidatePlay(play_type=pt, frequency=m / ntot, success_rate=sr, avg_epa=avge, sample_count=m)
        )
    cand.sort(key=lambda c: (-c.frequency, c.play_type.value))
    cand = cand[:N_TOP]
    rel = " (relaxed)" if relaxed else ""
    note = (
        f"Based on {ntot} plays{rel}: down {situation.down}, {situation.distance_bucket}, "
        f"{situation.field_zone}, {situation.score_diff_bucket}, {situation.game_script}."
    )
    return HistoricalRecommendation(
        situation=situation,
        status=status,
        tier_used=tier,
        sample_size=ntot,
        candidates=cand,
        note=note,
    )
