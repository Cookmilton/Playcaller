"""Aggregate validation + quality audit over on-disk processed JSON (schema v2).

Single entry point for CLI and Streamlit: scan ``data/processed/{season}/week_*/*.json``,
run :func:`~warehouse.validation.validate_play_sequence` and
:func:`~warehouse.quality.check_quality`, return deterministic summaries.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from warehouse.quality import check_quality
from warehouse.review_loader import parse_processed_payload
from warehouse.validation import validate_play_sequence

# Rule names sourced from warehouse/validation.py and warehouse/quality.py (do not modify those files).
_VALIDATION_RULE_NAMES: tuple[str, ...] = (
    "sequence_monotonic",
    "quarter_progression",
    "clock_monotonic",
    "down_reset_on_first_down",
    "score_only_on_scoring_play",
    "possession_change_explained",
    "yardline_range",
)
_QUALITY_RULE_NAMES: tuple[str, ...] = (
    "duplicate_play_sequence",
    "missing_situation",
    "yardline_out_of_range",
    "unexplained_score_jump",
    "unexplained_possession_change",
    "impossible_down",
    "negative_yards_on_incomplete",
)

_REQUIRED_COMPLETENESS_FIELDS: tuple[tuple[str, str], ...] = (
    ("down", "down"),
    ("distance", "distance"),
    ("yardline_100", "yardline"),
    ("play_type", "play_type"),
    ("quarter", "quarter"),
)
_OPTIONAL_COMPLETENESS_ATTRS: tuple[tuple[str, str], ...] = (
    ("clock_seconds", "clock"),
    ("offense_personnel", "personnel"),
    ("air_yards", "air_yards"),
    ("run_location", "run_location"),
    ("xpass", "xpass"),
)

_REPO_ROOT: Path = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class IssueCount:
    """One rule's total occurrences after a scan."""

    rule_name: str
    category: str  # "validation" | "quality"
    count: int


@dataclass(frozen=True, slots=True)
class AffectedFile:
    """Per-file issue rollup for triage."""

    path: Path
    season: int | None
    week: int | None
    game_id: str | None
    external_game_id: str | None
    validation_count: int
    quality_count: int
    issue_counts_by_rule: dict[str, int]


@dataclass(frozen=True)
class DistributionStats:
    n: int
    min: float
    p25: float
    median: float
    mean: float
    p75: float
    p95: float
    max: float
    stdev: float | None


@dataclass(frozen=True)
class OutlierGame:
    game_id: str
    path: Path
    season: int | None
    week: int | None
    metric: str
    value: float
    threshold_low: float | None
    threshold_high: float | None
    direction: str


@dataclass(frozen=True)
class CompletenessGap:
    field: str
    required: bool
    total_rows: int
    missing_rows: int
    pct_missing: float
    affected_games: int


@dataclass(frozen=True)
class SuspiciousGame:
    game_id: str
    path: Path
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RuleHygiene:
    rule_name: str
    category: str
    classification: str
    games_fired_in: int
    total_games: int
    pct_games: float


@dataclass(frozen=True)
class SuppressionFinding:
    rule_name: str
    silent: bool
    recently_modified: bool
    last_modified_sha: str | None
    last_modified_date: str | None
    note: str


@dataclass(frozen=True)
class Diagnostics:
    plays_per_game: DistributionStats
    drives_per_game: DistributionStats
    yards_gained: DistributionStats
    play_type_counts: tuple[tuple[str, int], ...]
    outliers: tuple[OutlierGame, ...]
    completeness: tuple[CompletenessGap, ...]
    rule_hygiene: tuple[RuleHygiene, ...]
    suppression_findings: tuple[SuppressionFinding, ...]
    top_suspicious: tuple[SuspiciousGame, ...]
    health_signal: str
    health_summary: str


@dataclass(frozen=True, slots=True)
class AuditSummary:
    """Full scan result; lists are pre-sorted for stable output."""

    root: Path
    total_files: int
    total_games: int
    total_plays: int
    total_drives: int | None
    validation_issue_total: int
    quality_issue_total: int
    counts_by_rule: tuple[IssueCount, ...]
    affected_files: tuple[AffectedFile, ...]
    scanned_paths: tuple[Path, ...]
    load_errors: tuple[tuple[str, str], ...]
    diagnostics: Diagnostics | None = None


def _season_week_from_processed_path(root: Path, path: Path) -> tuple[int | None, int | None]:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return None, None
    parts = rel.parts
    if len(parts) < 3:
        return None, None
    se_s, wk_s, _fname = parts[0], parts[1], parts[2]
    if not se_s.isdigit():
        return None, None
    if not (wk_s.startswith("week_") and wk_s[5:].isdigit()):
        return None, None
    return int(se_s), int(wk_s[5:])


def discover_processed_json_paths(
    root: Path,
    *,
    season: int | None = None,
    week: int | None = None,
) -> list[Path]:
    """Return sorted JSON paths under *root* using directory conventions only."""
    if not root.is_dir():
        return []
    paths: list[Path] = []
    if season is not None:
        base = root / str(season)
        if week is not None:
            wd = base / f"week_{week:02d}"
            if wd.is_dir():
                paths.extend(sorted(wd.glob("*.json")))
        elif base.is_dir():
            for wd in sorted(base.glob("week_*")):
                if wd.is_dir():
                    paths.extend(sorted(wd.glob("*.json")))
    else:
        for sd in sorted(root.iterdir()):
            if not sd.is_dir() or not sd.name.isdigit():
                continue
            for wd in sorted(sd.glob("week_*")):
                if wd.is_dir():
                    paths.extend(sorted(wd.glob("*.json")))
    paths.sort(key=lambda p: str(p.resolve()))
    return paths


def _round_pct(x: float) -> float:
    return round(float(x) + 0.0, 2)


def compute_distribution_stats(values: list[float]) -> DistributionStats:
    """Build :class:`DistributionStats` per §10.1 (``statistics.quantiles``)."""
    n = len(values)
    if n == 0:
        return DistributionStats(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, None)
    s = sorted(values)
    lo = float(s[0])
    hi = float(s[-1])
    mean = float(statistics.mean(s))
    stv: float | None
    stv = float(statistics.stdev(s)) if n >= 2 else None
    if n < 4:
        med = float(statistics.median(s))
        return DistributionStats(n, lo, med, med, mean, med, med, hi, stv)
    qs = statistics.quantiles(s, n=100, method="inclusive")
    p25 = float(qs[24])
    p75 = float(qs[74])
    p95 = float(qs[94])
    med = float(statistics.median(s))
    return DistributionStats(n, lo, p25, med, mean, p75, p95, hi, stv)


def _iqr_fences(values: list[float]) -> tuple[float, float, float, bool]:
    """Return (low, high, iqr, degenerate) using 1.5×IQR. Degenerate if n<4 or IQR=0."""
    n = len(values)
    if n < 4:
        return 0.0, 0.0, 0.0, True
    s = sorted(values)
    qs = statistics.quantiles(s, n=100, method="inclusive")
    q1 = float(qs[24])
    q3 = float(qs[74])
    iqr = q3 - q1
    if iqr == 0.0:
        return q1, q3, 0.0, True
    return q1 - 1.5 * iqr, q3 + 1.5 * iqr, iqr, False


def _field_missing(play: Any, key: str) -> bool:
    if key == "down":
        return play.down is None
    if key == "distance":
        return play.distance is None
    if key == "yardline_100":
        return play.yardline_100 is None
    if key == "play_type":
        return False
    if key == "quarter":
        return False
    if key == "clock_seconds":
        return play.clock_seconds is None
    if key == "offense_personnel":
        return play.offense_personnel is None
    if key == "air_yards":
        return play.air_yards is None
    if key == "run_location":
        return play.run_location is None
    if key == "xpass":
        return play.xpass is None
    return False


def _build_completeness(
    play_total_rows: int,
    missing: dict[str, int],
    affected: dict[str, set[str]],
) -> list[CompletenessGap]:
    rows: list[CompletenessGap] = []
    for key, display in _REQUIRED_COMPLETENESS_FIELDS + _OPTIONAL_COMPLETENESS_ATTRS:
        req = key in {k for k, _ in _REQUIRED_COMPLETENESS_FIELDS}
        m = int(missing.get(key, 0))
        ag = len(affected.get(key, ()))
        pt = play_total_rows
        pct = _round_pct((100.0 * m / pt) if pt else 0.0)
        rows.append(
            CompletenessGap(
                field=display,
                required=req,
                total_rows=pt,
                missing_rows=m,
                pct_missing=pct,
                affected_games=ag,
            )
        )
    rows.sort(key=lambda g: (not g.required, -g.pct_missing, g.field))
    return rows


def _rule_hygiene_rows(
    total_games: int,
    games_with_rule: dict[str, set[str]],
) -> list[RuleHygiene]:
    out: list[RuleHygiene] = []
    for r in _VALIDATION_RULE_NAMES:
        gs = games_with_rule.get(f"v:{r}", set())
        ng = len(gs)
        pg = (100.0 * ng / total_games) if total_games else 0.0
        if ng == 0:
            c = "silent"
        elif pg < 5.0:
            c = "rare"
        else:
            c = "high_signal"
        out.append(
            RuleHygiene(
                rule_name=r,
                category="validation",
                classification=c,
                games_fired_in=ng,
                total_games=total_games,
                pct_games=_round_pct(pg),
            )
        )
    for r in _QUALITY_RULE_NAMES:
        gs = games_with_rule.get(f"q:{r}", set())
        ng = len(gs)
        pg = (100.0 * ng / total_games) if total_games else 0.0
        if ng == 0:
            c = "silent"
        elif pg < 5.0:
            c = "rare"
        else:
            c = "high_signal"
        out.append(
            RuleHygiene(
                rule_name=r,
                category="quality",
                classification=c,
                games_fired_in=ng,
                total_games=total_games,
                pct_games=_round_pct(pg),
            )
        )
    out.sort(key=lambda h: (h.category, h.rule_name))
    return out


def _git_suppression_hits(rule_names: Iterable[str]) -> list[SuppressionFinding]:
    """Best-effort: one git read; match silent rule substrings in recent history (§10.7)."""
    log_blob = ""
    try:
        p = subprocess.run(
            [
                "git",
                "-C",
                str(_REPO_ROOT),
                "log",
                "-p",
                "--since=6 months ago",
                "--",
                "warehouse/validation.py",
                "warehouse/quality.py",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        log_blob = p.stdout or ""
    except (OSError, subprocess.TimeoutExpired):
        log_blob = ""
    out: list[SuppressionFinding] = []
    for r in sorted(set(rule_names)):
        mod = r in log_blob
        out.append(
            SuppressionFinding(
                rule_name=r,
                silent=True,
                recently_modified=mod,
                last_modified_sha=None,
                last_modified_date=None,
                note="rule id appears in 6m git -p for validation/quality" if mod else "not seen in 6m git -p for validation/quality",
            )
        )
    return out


def _compute_diagnostics(
    root: Path,
    *,
    games_ok: int,
    val_total: int,
    qual_total: int,
    game_snaps: list[dict[str, Any]],
    play_type_counter: Counter[str],
    games_fired: dict[str, set[str]],
) -> Diagnostics:
    """Build diagnostics (single pass of aggregates already collected)."""
    _ = root
    ppg = [float(x["n_plays"]) for x in game_snaps]
    dpg: list[float] = []
    for x in game_snaps:
        if x["skip_drives_dist"]:
            continue
        dpg.append(float(x["n_drives"]))

    plays_ds = compute_distribution_stats(ppg)
    drives_ds = compute_distribution_stats(dpg)
    yds_list: list[float] = []
    for x in game_snaps:
        yds_list.extend(x["yard_vals"])
    yards_ds = compute_distribution_stats(yds_list)

    pt_counts = tuple(
        sorted(
            ((str(name), c) for name, c in play_type_counter.items()),
            key=lambda t: (-t[1], t[0]),
        )
    )

    low_p, high_p, _, degen_p = _iqr_fences(ppg) if ppg else (0.0, 0.0, 0.0, True)
    low_d, high_d, _, degen_d = _iqr_fences(dpg) if dpg else (0.0, 0.0, 0.0, True)
    degen = degen_p or degen_d
    outlier_rows: list[OutlierGame] = []
    for x in game_snaps:
        gid = str(x["game_id"])
        path = x["path"]
        se, wk = x["season"], x["week"]
        np = float(x["n_plays"])
        if not degen_p:
            if np < low_p or np > high_p:
                dr = "low" if np < low_p else "high"
                outlier_rows.append(
                    OutlierGame(
                        game_id=gid,
                        path=path,
                        season=se,
                        week=wk,
                        metric="plays_per_game",
                        value=np,
                        threshold_low=low_p,
                        threshold_high=high_p,
                        direction=dr,
                    )
                )
        if not degen_d and not x["skip_drives_dist"]:
            nd = float(x["n_drives"])
            if nd < low_d or nd > high_d:
                dr = "low" if nd < low_d else "high"
                outlier_rows.append(
                    OutlierGame(
                        game_id=gid,
                        path=path,
                        season=se,
                        week=wk,
                        metric="drives_per_game",
                        value=nd,
                        threshold_low=low_d,
                        threshold_high=high_d,
                        direction=dr,
                    )
                )
        invc = int(x["invalid_yards_count"])
        if invc > 0:
            outlier_rows.append(
                OutlierGame(
                    game_id=gid,
                    path=path,
                    season=se,
                    week=wk,
                    metric="invalid_yards",
                    value=float(invc),
                    threshold_low=None,
                    threshold_high=None,
                    direction="invalid",
                )
            )
    outlier_rows.sort(
        key=lambda o: (o.direction, o.metric, str(o.path.resolve()), o.game_id)
    )
    out_tup = tuple(outlier_rows)

    missing: dict[str, int] = defaultdict(int)
    affected: dict[str, set[str]] = defaultdict(set)
    play_total_rows = 0
    for x in game_snaps:
        gid = str(x["game_id"])
        play_total_rows += int(x["n_plays"])
        for key, nmiss in x["per_field_missed_plays"].items():
            if nmiss > 0:
                missing[key] += int(nmiss)
                affected[key].add(gid)

    comp_list = _build_completeness(play_total_rows, missing, affected)
    comp_tup = tuple(comp_list)
    high_optional = {
        c.field
        for c in comp_list
        if (not c.required) and c.pct_missing > 25.0
    }
    rhy = tuple(_rule_hygiene_rows(games_ok, games_fired))

    silent_for_git = (h.rule_name for h in rhy if h.classification == "silent")
    sup = tuple(_git_suppression_hits(silent_for_git))

    outlier_gameset = {o.game_id for o in out_tup}
    games_flagged = len(outlier_gameset)
    o_frac = (games_flagged / games_ok) if games_ok else 0.0
    req_has_bad = any(
        c.required and c.pct_missing >= 5.0 and play_total_rows for c in comp_list
    )
    rule_silence_degraded = games_ok > 0 and (val_total + qual_total) == 0
    degraded = req_has_bad or o_frac > 0.10 or rule_silence_degraded
    n_out = len(out_tup)

    if degraded:
        hs = "degraded"
        parts: list[str] = []
        if req_has_bad:
            parts.append("one or more required fields are ≥5% missing corpus-wide")
        if o_frac > 0.10:
            parts.append("more than 10% of games have at least one outlier flag")
        if rule_silence_degraded:
            parts.append(
                "0 validation/quality issues while games are present; "
                "rules reported no issues (review warehouse/validation.py and quality.py for over-suppression)"
            )
        if degen and n_out and not (degen_p and degen_d):
            parts.append("IQR bounds degenerate; only invalid-yard stat-outliers for extremes")
        summ = f"Degraded: {'; '.join(parts) if parts else 'see diagnostics'}."
    elif games_ok == 0:
        hs = "healthy"
        summ = "No games loaded; empty scan range or only load errors."
    else:
        hs = "mixed"
        p2: list[str] = []
        if (val_total + qual_total) > 0:
            p2.append("validation/quality issues present")
        if n_out:
            p2.append(f"{games_flagged} game(s) with at least one outlier row")
        if not p2:
            p2.append("no rule or outlier issues detected in this range")
        summ = f"Mixed: {'; '.join(p2)}."

    score_rows: list[tuple[float, int, int, str, Path, list[str]]] = []
    for x in game_snaps:
        gid = str(x["game_id"])
        o_hit = len([o for o in out_tup if o.game_id == gid])
        rgap = 0
        o_opt = 0
        for key, _disp in _REQUIRED_COMPLETENESS_FIELDS:
            if x["per_field_missed_plays"].get(key, 0) > 0:
                rgap += 1
        for key, disp in _OPTIONAL_COMPLETENESS_ATTRS:
            if disp in high_optional and x["per_field_missed_plays"].get(key, 0) > 0:
                o_opt += 1
        v_n = int(x["v_n"])
        q_n = int(x["q_n"])
        sc = 1.0 * v_n + 1.0 * q_n + 0.5 * o_hit + 0.3 * rgap + 0.1 * o_opt
        reasons: list[str] = []
        if v_n:
            reasons.append(f"{v_n} validation issue(s)")
        if q_n:
            reasons.append(f"{q_n} quality issue(s)")
        if o_hit:
            reasons.append(f"{o_hit} outlier metric flag(s)")
        if rgap:
            reasons.append(f"{rgap} required field gap(s) in this game")
        if o_opt:
            reasons.append("optional field gaps in high-missingness fields")
        if not reasons:
            reasons.append("low diagnostic signal in this game")
        rs = sorted(set(reasons))
        score_rows.append((sc, v_n, q_n, gid, x["path"], rs))
    score_rows.sort(key=lambda t: (-t[0], -t[1], -t[2], str(t[4].resolve())))
    top3 = tuple(
        SuspiciousGame(game_id=sg[3], path=sg[4], score=sg[0], reasons=tuple(sg[5])) for sg in score_rows[:3]
    )

    return Diagnostics(
        plays_per_game=plays_ds,
        drives_per_game=drives_ds,
        yards_gained=yards_ds,
        play_type_counts=pt_counts,
        outliers=out_tup,
        completeness=comp_tup,
        rule_hygiene=rhy,
        suppression_findings=sup,
        top_suspicious=top3,
        health_signal=hs,
        health_summary=summ,
    )


def audit_processed(
    root: Path,
    *,
    season: int | None = None,
    week: int | None = None,
    compute_diagnostics: bool = True,
) -> AuditSummary:
    """Scan processed JSON, run validation + quality, return structured summary.

    Does not raise on per-file load or parse errors — records them in ``load_errors``
    and continues. ``affected_files`` lists every file with ≥1 issue, sorted by
    issue count desc then path.
    """
    t_scan = time.perf_counter()
    paths = discover_processed_json_paths(root, season=season, week=week)
    scanned = tuple(paths)

    load_errors: list[tuple[str, str]] = []
    val_total = 0
    qual_total = 0
    rule_counter: Counter[tuple[str, str]] = Counter()
    play_total = 0
    drive_sum = 0
    games_ok = 0
    affected: list[AffectedFile] = []
    game_snaps: list[dict[str, Any]] = []
    play_type_all: Counter[str] = Counter()
    games_fired: dict[str, set[str]] = defaultdict(set)
    for path in paths:
        try:
            raw_text = path.read_text(encoding="utf-8")
        except OSError as e:
            load_errors.append((str(path.resolve()), f"read error: {e}"))
            continue
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as e:
            load_errors.append((str(path.resolve()), f"invalid JSON: {e}"))
            continue
        try:
            game, plays, feats = parse_processed_payload(data)
        except (KeyError, TypeError, ValueError) as e:
            load_errors.append((str(path.resolve()), f"payload: {e}"))
            continue

        games_ok += 1
        play_total += len(plays)
        drive_sum += max((f.drive_number for f in feats), default=0)

        v_report = validate_play_sequence(game, plays)
        q_issues = check_quality(game, plays)

        v_n = len(v_report.issues)
        q_n = len(q_issues)
        val_total += v_n
        qual_total += q_n

        per_file_rules: Counter[str] = Counter()
        for i in v_report.issues:
            rule_counter[("validation", i.rule)] += 1
            per_file_rules[i.rule] += 1
            games_fired[f"v:{i.rule}"].add(game.id)
        for i in q_issues:
            rule_counter[("quality", i.rule)] += 1
            per_file_rules[i.rule] += 1
            games_fired[f"q:{i.rule}"].add(game.id)

        se, wk = _season_week_from_processed_path(root, path)
        if v_n or q_n:
            affected.append(
                AffectedFile(
                    path=path,
                    season=se,
                    week=wk,
                    game_id=game.id,
                    external_game_id=game.external_game_id,
                    validation_count=v_n,
                    quality_count=q_n,
                    issue_counts_by_rule=dict(sorted(per_file_rules.items())),
                )
            )

        if compute_diagnostics:
            dnums: set[int] = {f.drive_number for f in feats}
            n_plays = len(plays)
            skip_d = n_plays == 0 or (len(dnums) == 0)
            n_drives = 0 if skip_d else len(dnums)
            inv_y = 0
            yard_vals: list[float] = []
            per_field: dict[str, int] = defaultdict(int)
            for p in plays:
                play_type_all[str(p.play_type.value)] += 1
                yg = p.yards_gained
                if yg is not None:
                    yard_vals.append(float(yg))
                    if abs(int(yg)) > 99:
                        inv_y += 1
                for key, _ in _REQUIRED_COMPLETENESS_FIELDS + _OPTIONAL_COMPLETENESS_ATTRS:
                    if _field_missing(p, key):
                        per_field[key] += 1
            game_snaps.append(
                {
                    "path": path,
                    "game_id": game.id,
                    "season": se,
                    "week": wk,
                    "n_plays": n_plays,
                    "n_drives": n_drives,
                    "skip_drives_dist": skip_d,
                    "invalid_yards_count": inv_y,
                    "yard_vals": yard_vals,
                    "per_field_missed_plays": dict(per_field),
                    "v_n": v_n,
                    "q_n": q_n,
                }
            )

    counts_list = [
        IssueCount(rule_name=r, category=c, count=n)
        for (c, r), n in rule_counter.items()
    ]
    counts_list.sort(key=lambda ic: (ic.category, -ic.count, ic.rule_name))

    affected.sort(
        key=lambda a: (-(a.validation_count + a.quality_count), str(a.path.resolve())),
    )

    load_err_t = tuple(sorted(load_errors, key=lambda t: t[0]))
    diag: Diagnostics | None
    if compute_diagnostics:
        diag = _compute_diagnostics(
            root,
            games_ok=games_ok,
            val_total=val_total,
            qual_total=qual_total,
            game_snaps=game_snaps,
            play_type_counter=play_type_all,
            games_fired=dict(games_fired),
        )
    else:
        diag = None
    _ = time.perf_counter() - t_scan

    return AuditSummary(
        root=root,
        total_files=len(paths),
        total_games=games_ok,
        total_plays=play_total,
        total_drives=(drive_sum if games_ok > 0 else None),
        validation_issue_total=val_total,
        quality_issue_total=qual_total,
        counts_by_rule=tuple(counts_list),
        affected_files=tuple(affected),
        scanned_paths=scanned,
        load_errors=load_err_t,
        diagnostics=diag,
    )


def filtered_issue_totals(
    summary: AuditSummary,
    *,
    rule_filter: frozenset[str] | None,
) -> tuple[int, int]:
    """Return (validation, quality) issue counts restricted to *rule_filter* rules.

    If *rule_filter* is empty or None, returns summary validation and quality totals.
    """
    if not rule_filter:
        return summary.validation_issue_total, summary.quality_issue_total
    v = 0
    q = 0
    for ic in summary.counts_by_rule:
        if ic.rule_name not in rule_filter:
            continue
        if ic.category == "validation":
            v += ic.count
        else:
            q += ic.count
    return v, q


def filter_affected_files(
    summary: AuditSummary,
    *,
    rule_filter: frozenset[str] | None,
    search_text: str,
) -> list[AffectedFile]:
    """Filter ``affected_files`` by rule subset and case-insensitive substring match."""
    needle = search_text.strip().lower()
    out: list[AffectedFile] = []
    for af in summary.affected_files:
        if needle:
            hay = " ".join(
                [
                    str(af.path),
                    af.game_id or "",
                    af.external_game_id or "",
                ]
            ).lower()
            if needle not in hay:
                continue
        if rule_filter:
            if not any(af.issue_counts_by_rule.get(r, 0) > 0 for r in rule_filter):
                continue
        out.append(af)
    return out


def _dist_dict(ds: DistributionStats) -> dict[str, Any]:
    return {
        "n": ds.n,
        "min": ds.min,
        "p25": ds.p25,
        "median": ds.median,
        "mean": ds.mean,
        "p75": ds.p75,
        "p95": ds.p95,
        "max": ds.max,
        "stdev": ds.stdev,
    }


def _diagnostics_to_dict(d: Diagnostics) -> dict[str, Any]:
    return {
        "plays_per_game": _dist_dict(d.plays_per_game),
        "drives_per_game": _dist_dict(d.drives_per_game),
        "yards_gained": _dist_dict(d.yards_gained),
        "play_type_counts": [[n, c] for n, c in d.play_type_counts],
        "outliers": [
            {
                "game_id": o.game_id,
                "path": str(o.path.resolve()),
                "season": o.season,
                "week": o.week,
                "metric": o.metric,
                "value": o.value,
                "threshold_low": o.threshold_low,
                "threshold_high": o.threshold_high,
                "direction": o.direction,
            }
            for o in d.outliers
        ],
        "completeness": [
            {
                "field": c.field,
                "required": c.required,
                "total_rows": c.total_rows,
                "missing_rows": c.missing_rows,
                "pct_missing": c.pct_missing,
                "affected_games": c.affected_games,
            }
            for c in d.completeness
        ],
        "rule_hygiene": [
            {
                "rule_name": h.rule_name,
                "category": h.category,
                "classification": h.classification,
                "games_fired_in": h.games_fired_in,
                "total_games": h.total_games,
                "pct_games": h.pct_games,
            }
            for h in d.rule_hygiene
        ],
        "suppression_findings": [
            {
                "rule_name": s.rule_name,
                "silent": s.silent,
                "recently_modified": s.recently_modified,
                "last_modified_sha": s.last_modified_sha,
                "last_modified_date": s.last_modified_date,
                "note": s.note,
            }
            for s in d.suppression_findings
        ],
        "top_suspicious": [
            {
                "game_id": t.game_id,
                "path": str(t.path.resolve()),
                "score": t.score,
                "reasons": list(t.reasons),
            }
            for t in d.top_suspicious
        ],
        "health_signal": d.health_signal,
        "health_summary": d.health_summary,
    }


def audit_summary_to_json_dict(summary: AuditSummary) -> dict:
    """JSON-serializable dict (paths as strings, tuples as lists)."""

    def file_dict(af: AffectedFile) -> dict:
        return {
            "path": str(af.path.resolve()),
            "season": af.season,
            "week": af.week,
            "game_id": af.game_id,
            "external_game_id": af.external_game_id,
            "validation_count": af.validation_count,
            "quality_count": af.quality_count,
            "issue_counts_by_rule": af.issue_counts_by_rule,
        }

    out: dict[str, Any] = {
        "root": str(summary.root.resolve()),
        "total_files": summary.total_files,
        "total_games": summary.total_games,
        "total_plays": summary.total_plays,
        "total_drives": summary.total_drives,
        "validation_issue_total": summary.validation_issue_total,
        "quality_issue_total": summary.quality_issue_total,
        "counts_by_rule": [
            {"rule_name": ic.rule_name, "category": ic.category, "count": ic.count}
            for ic in summary.counts_by_rule
        ],
        "affected_files": [file_dict(af) for af in summary.affected_files],
        "scanned_paths": [str(p.resolve()) for p in summary.scanned_paths],
        "load_errors": [{"path": p, "message": m} for p, m in summary.load_errors],
    }
    if summary.diagnostics is not None:
        out["diagnostics"] = _diagnostics_to_dict(summary.diagnostics)
    return out


def _print_human_report(summary: AuditSummary, *, top_n: int) -> None:
    print(f"Processed JSON audit — root: {summary.root.resolve()}")
    print(f"Files scanned: {summary.total_files} | games loaded OK: {summary.total_games} | plays: {summary.total_plays}")
    if summary.total_drives is not None:
        print(f"Σ max(drive_number) per game: {summary.total_drives}")
    print(
        f"Validation issues: {summary.validation_issue_total} | "
        f"Quality issues: {summary.quality_issue_total}"
    )
    if summary.load_errors:
        print(f"Load errors: {len(summary.load_errors)}")
        for p, msg in summary.load_errors[:20]:
            print(f"  {p}: {msg}")
        if len(summary.load_errors) > 20:
            print("  ...")
    print()
    print("Counts by rule (category / rule / count)")
    for ic in summary.counts_by_rule:
        print(f"  {ic.category:10} {ic.rule_name:32} {ic.count}")
    print()
    print(f"Top affected files (max {top_n})")
    for af in summary.affected_files[:top_n]:
        print(
            f"  {af.validation_count + af.quality_count:4}  "
            f"{af.path.name}  ({af.external_game_id or af.game_id})"
        )
    d = summary.diagnostics
    if d is not None:
        print()
        print(f"Data health: {d.health_signal}")
        print(f"  {d.health_summary}")
        silent_n = sum(1 for h in d.rule_hygiene if h.classification == "silent")
        rare_n = sum(1 for h in d.rule_hygiene if h.classification == "rare")
        hs_n = sum(1 for h in d.rule_hygiene if h.classification == "high_signal")
        print(f"Rule hygiene: {silent_n} silent, {rare_n} rare, {hs_n} high-signal")
        o_g = len({o.game_id for o in d.outliers})
        print(f"Outliers: {o_g} game(s) flagged (rows: {len(d.outliers)})")
        c_bad = sum(1 for c in d.completeness if c.required and c.pct_missing > 1.0)
        print(f"Completeness issues: {c_bad} required field(s) above 1% missing")
        print("Top suspicious games:")
        for i, t in enumerate(d.top_suspicious, 1):
            first = t.reasons[0] if t.reasons else "—"
            print(
                f"  {i}. {t.game_id}  score={t.score:.2f}  — {first}"
            )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Audit processed warehouse JSON (validation + quality).")
    p.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Processed root (default: repo data/processed)",
    )
    p.add_argument("--season", type=int, default=None)
    p.add_argument("--week", type=int, default=None)
    p.add_argument("--top", type=int, default=10, help="Max rows in human 'top affected' table")
    p.add_argument(
        "--no-diagnostics",
        action="store_true",
        help="Skip Data health / distribution scan (faster; diagnostics omitted from JSON).",
    )
    p.add_argument("--json", action="store_true", help="Emit JSON to stdout")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.week is not None and args.season is None:
        print("error: --week requires --season", file=sys.stderr)
        return 2
    from warehouse.storage import processed_data_dir

    root = args.root if args.root is not None else processed_data_dir()
    if not root.exists() or not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 2
    summary = audit_processed(
        root,
        season=args.season,
        week=args.week,
        compute_diagnostics=not args.no_diagnostics,
    )
    if args.json:
        print(json.dumps(audit_summary_to_json_dict(summary), indent=2))
    else:
        _print_human_report(summary, top_n=max(1, args.top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
