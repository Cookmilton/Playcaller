"""
Structured, UI-friendly historical influence metadata for recommendation dicts.

Built from the technical ``historical_influence`` debug blob; keeps prose concise and defers full structure to ``technical`` for expanders / audits.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

from .influence import lane_slice_for_historical_metadata


def _fmt_pct(x: Optional[float]) -> str:
    if x is None:
        return "—"
    return f"{100.0 * float(x):.0f}%"


def _lane_slice_for_headline(sl: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Omit lanes from the main headline when success is unknown and n is still small (avoid ``—%`` noise)."""
    if sl is None:
        return None
    n = int(sl.get("n") or 0)
    if n <= 0:
        return None
    if sl.get("success_rate") is None and n < 15:
        return None
    return sl


def _not_applied_copy(reason: Optional[str], n: Optional[int], debug: Mapping[str, Any]) -> Tuple[str, str]:
    r = str(reason or "unknown")
    n_txt = f"{int(n)}" if n is not None else "few"
    if r == "no_corpus_for_call":
        return (
            "Heuristic only — no historical sample was loaded for this call.",
            "Enable **Historical nudge** in the sidebar after loading games on the **Game library** page.",
        )
    if r == "empty_plays":
        return ("Heuristic only — historical corpus was empty.", "Reload your history folder or check JSON exports.")
    if r == "no_outcome_summary_or_zero_matches":
        return (
            "No similar historical plays matched this situation.",
            "Try a larger corpus or a less strict filter; scores follow the usual engine.",
        )
    if r == "overall_below_soft_gate":
        return (
            f"Too few similar plays to trust history here (n={n_txt}).",
            "Scores follow the usual engine until the sample grows.",
        )
    if r == "zero_lane_adjustments":
        return (
            "Similar plays found, but not enough **run** or **pass** outcomes to nudge scores.",
            "Scores follow the usual engine.",
        )
    return (
        "Historical data did not change scores this time.",
        f"Reason: {r.replace('_', ' ')}.",
    )


def _applied_headline(
    *,
    n_overall: int,
    tier: Optional[str],
    run_s: Optional[Dict[str, Any]],
    pass_s: Optional[Dict[str, Any]],
) -> str:
    bits = []
    if run_s:
        sr = _fmt_pct(run_s.get("success_rate"))
        if run_s["role"] == "boost":
            bits.append(f"**Run** outcomes looked strong (~{sr} success, n={run_s['n']})")
        elif run_s["role"] == "caution":
            bits.append(
                f"**Run** outcomes were shaky (~{sr} success, {100 * run_s['turnover_rate']:.0f}% turnovers, n={run_s['n']})"
            )
        else:
            bits.append(f"**Run** lane mixed (~{sr} success, n={run_s['n']})")
    if pass_s:
        sr = _fmt_pct(pass_s.get("success_rate"))
        if pass_s["role"] == "boost":
            bits.append(f"**Pass** outcomes looked strong (~{sr} success, n={pass_s['n']})")
        elif pass_s["role"] == "caution":
            bits.append(
                f"**Pass** showed turnover risk (~{sr} success, {100 * pass_s['turnover_rate']:.0f}% turnovers, n={pass_s['n']})"
            )
        else:
            bits.append(f"**Pass** lane mixed (~{sr} success, n={pass_s['n']})")
    if not bits:
        return f"History from **{n_overall}** similar plays nudged scores slightly."
    widened = tier not in (None, "", "strict")
    suffix = " (wider similarity match)." if widened else "."
    return "Historical note: " + "; ".join(bits) + f" across **{n_overall}** similar plays" + suffix


def _context_blurb(qb: Mapping[str, Any], tier: Optional[str]) -> Optional[str]:
    if not qb or qb.get("down") is None:
        return None
    db = str(qb.get("distance_bucket") or "").replace("_", " ")
    fz = str(qb.get("field_zone") or "").replace("_", " ")
    tier_l = str(tier or "")
    tier_note = "" if tier_l in ("strict", "") else f" · match: **{tier_l.replace('_', ' ')}**"
    return f"Compared to past plays in **down {qb.get('down')} · {db} · {fz}**{tier_note}"


def build_historical_metadata_for_recommendation(debug: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """
    Return a stable dict for ``result['historical_metadata']``.

    ``technical`` mirrors the influence debug payload for engineers; safe when empty.
    """
    if not debug:
        return {
            "status": "unavailable",
            "corpus_supplied": False,
            "headline": "Heuristic only — no historical metadata for this call.",
            "summary": "",
            "context_blurb": None,
            "overall_matches": None,
            "similarity_tier": None,
            "similarity_widened": False,
            "run_lane": None,
            "pass_lane": None,
            "technical": {},
        }

    d = dict(debug)
    corpus = bool(d.get("corpus_supplied"))
    applied = d.get("applied") is True
    tier = d.get("similarity_tier")
    widened = isinstance(tier, str) and tier != "strict"
    qb = d.get("query_buckets") or {}
    n_overall = d.get("overall_matches")
    run_s = lane_slice_for_historical_metadata(d.get("run_lane") or {})
    pass_s = lane_slice_for_historical_metadata(d.get("pass_lane") or {})

    if not corpus:
        return {
            "status": "unavailable",
            "corpus_supplied": False,
            "headline": "Heuristic only — no historical sample was used for this call.",
            "summary": "Turn on **Historical nudge** in the sidebar after loading a corpus on **Game library**.",
            "context_blurb": None,
            "overall_matches": None,
            "similarity_tier": None,
            "similarity_widened": False,
            "run_lane": None,
            "pass_lane": None,
            "technical": d,
        }

    if not applied:
        h, s = _not_applied_copy(d.get("reason"), int(n_overall) if n_overall is not None else None, d)
        return {
            "status": "not_applied",
            "corpus_supplied": True,
            "headline": h,
            "summary": s,
            "context_blurb": _context_blurb(qb, tier if isinstance(tier, str) else None),
            "overall_matches": int(n_overall) if n_overall is not None else None,
            "similarity_tier": tier,
            "similarity_widened": widened,
            "run_lane": run_s,
            "pass_lane": pass_s,
            "technical": d,
        }

    headline = _applied_headline(
        n_overall=int(n_overall or 0),
        tier=tier if isinstance(tier, str) else None,
        run_s=_lane_slice_for_headline(run_s),
        pass_s=_lane_slice_for_headline(pass_s),
    )
    tier_strength = d.get("similarity_tier_strength")
    summary_parts = [
        "Scores were nudged **after** the main engine, using **actual** run vs pass outcomes from similar situations.",
        "Caps stay small so the call stays heuristic-first.",
    ]
    if widened:
        wide_extra = ""
        if isinstance(tier_strength, (int, float)) and float(tier_strength) < 0.999:
            wide_extra = (
                f" Historical weight for this wider match was scaled to **{float(tier_strength):.2f}×** "
                "(see technical detail)."
            )
        summary_parts.insert(
            1,
            "Similar situations used a **widened** field/distance match — treat this as a hint, not a fact."
            + wide_extra,
        )

    return {
        "status": "applied",
        "corpus_supplied": True,
        "headline": headline,
        "summary": " ".join(summary_parts),
        "context_blurb": _context_blurb(qb, tier if isinstance(tier, str) else None),
        "overall_matches": int(n_overall) if n_overall is not None else None,
        "similarity_tier": tier,
        "similarity_widened": widened,
        "run_lane": run_s,
        "pass_lane": pass_s,
        "technical": d,
    }
