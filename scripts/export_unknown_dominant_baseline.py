#!/usr/bin/env python3
"""
Freeze implied-score failure-mode baseline: UNKNOWN-dominant games + corpus metrics.

Usage (from repo root, with processed JSON under e.g. data/processed)::

    python3 scripts/export_unknown_dominant_baseline.py data/processed \\
        -o baselines/unknown_dominant_reference.json

``classify_corpus`` uses the same path rules as ``python3 -m warehouse.implied_score_audit --summary``.
Default: no posteam inference (matches product implied-scoring audit).

Optional §10.4-style checks vs a previously saved JSON::

    python3 scripts/export_unknown_dominant_baseline.py data/processed \\
        -o /tmp/now.json --gates-against baselines/unknown_dominant_reference.json

Gates (soft; print only — adjust targets in script if product changes):
  - UNKNOWN-dominant count should drop by at least 25% vs reference.
  - Sum of ``game_error_magnitude`` over games listed in reference’s
    ``unknown_dominant_games`` should drop by at least 20% vs reference snapshot.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from warehouse.implied_score_audit import (
    UNKNOWN,
    GameClassification,
    classify_corpus,
    expand_summary_paths,
    summarize_classifications,
)


def _iso_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _prune_corpus_paths(paths: list[Path]) -> list[Path]:
    """Drop VCS/editor noise (e.g. ``.git/cursor/.../metadata.json``) from directory walks."""
    skip = {".git", "node_modules", "__pycache__"}
    out: list[Path] = []
    for p in paths:
        try:
            rel = p.resolve().parts
        except OSError:
            continue
        if any(part in skip for part in rel):
            continue
        out.append(p)
    return out


def build_payload(
    paths: list[Path],
    *,
    with_posteam_inference: bool,
    summary_root: str,
) -> tuple[dict[str, Any], list[GameClassification]]:
    cs: list[GameClassification] = classify_corpus(
        paths, with_posteam_inference=with_posteam_inference
    )
    summary = summarize_classifications(cs, root=summary_root, top_n=5000)
    mags = [c.game_error_magnitude for c in cs if c.game_error_magnitude is not None]
    total_mag = sum(int(m) for m in mags)
    unknown_dom = [
        c
        for c in cs
        if not c.classification_error and c.dominant_failure_mode == UNKNOWN
    ]
    games_out: list[dict[str, Any]] = []
    for c in sorted(unknown_dom, key=lambda x: (-(x.game_error_magnitude or 0), x.game_id)):
        games_out.append(
            {
                "game_id": c.game_id,
                "error_home": c.error_home,
                "error_away": c.error_away,
                "game_error_magnitude": c.game_error_magnitude,
                "applied_labels": list(c.applied_labels),
                "explanation": c.explanation,
            }
        )
    load_failures = sum(1 for c in cs if c.classification_error)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "generated_utc": _iso_utc(),
        "with_posteam_inference": with_posteam_inference,
        "corpus": {
            "root": summary["root"],
            "games_analyzed": summary["games_analyzed"],
            "load_failures": load_failures,
            "sum_game_error_magnitude": total_mag,
            "unknown_dominant_count": len(games_out),
            "dominant_counts": dict(summary["dominant_counts"]),
        },
        "unknown_dominant_games": games_out,
    }
    return payload, cs


def _gates(
    ref: dict[str, Any], new: dict[str, Any], new_classifications: list[GameClassification]
) -> list[str]:
    """Return human-readable gate results (empty = all passed)."""
    lines: list[str] = []
    rc = ref.get("corpus") or {}
    nc = new.get("corpus") or {}
    r_n = int(rc.get("unknown_dominant_count") or 0)
    n_n = int(nc.get("unknown_dominant_count") or 0)
    if r_n > 0:
        drop = (r_n - n_n) / float(r_n)
        ok = drop >= 0.25
        lines.append(
            f"Gate UNKNOWN-dominant drop: ref={r_n} now={n_n} "
            f"drop={drop * 100:.1f}%  (need >= 25%)  {'PASS' if ok else 'FAIL'}"
        )
    r_games: list[dict[str, Any]] = list(ref.get("unknown_dominant_games") or [])
    if not r_games:
        lines.append("Gate error-mass on ref game set: SKIPPED (no games in reference JSON)")
        return lines
    by_id = {g["game_id"]: int(g.get("game_error_magnitude") or 0) for g in r_games}
    ref_ids = set(by_id)
    new_mag: dict[str, int] = {}
    for c in new_classifications:
        if c.classification_error or c.game_error_magnitude is None:
            continue
        new_mag[c.game_id] = int(c.game_error_magnitude)
    before = sum(by_id[gid] for gid in ref_ids)
    after = sum(new_mag.get(gid, 0) for gid in ref_ids)
    if before > 0:
        edrop = (before - after) / float(before)
        ok2 = edrop >= 0.20
        lines.append(
            f"Gate error mass on {len(ref_ids)} ref UNKNOWN-dominant games: "
            f"ref_snapshot_sum={before}  now_sum={after}  "
            f"improvement={edrop * 100:.1f}%  (need >= 20%)  "
            f"{'PASS' if ok2 else 'FAIL'}"
        )
    return lines


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "corpus_path",
        type=Path,
        help="Directory of processed JSON (e.g. data/processed) or explicit .json file(s).",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        help="Write baseline JSON here.",
    )
    p.add_argument(
        "--with-inference",
        action="store_true",
        help="Classify with posteam inference (default: off).",
    )
    p.add_argument(
        "--gates-against",
        type=Path,
        metavar="REF_JSON",
        default=None,
        help="After writing, print soft gates vs this reference JSON.",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    root = args.corpus_path.expanduser()
    paths = _prune_corpus_paths(expand_summary_paths([root]))
    if not paths:
        print(f"error: no JSON files under {root} (after pruning .git / node_modules)", file=sys.stderr)
        return 1
    root_display = str(root.resolve()) if root.exists() else str(root)
    payload, classifications = build_payload(
        paths,
        with_posteam_inference=bool(args.with_inference),
        summary_root=root_display,
    )
    out = args.output.expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(f"wrote {out}  (UNKNOWN-dominant: {payload['corpus']['unknown_dominant_count']})")
    if args.gates_against is not None:
        ref = json.loads(args.gates_against.read_text(encoding="utf-8"))
        for line in _gates(ref, payload, classifications):
            print(line)
    return 0 if payload["corpus"]["load_failures"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
