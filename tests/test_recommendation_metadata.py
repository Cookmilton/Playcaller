"""Structured historical metadata for recommendation dicts."""

from __future__ import annotations

from playcaller.history.recommendation_metadata import build_historical_metadata_for_recommendation


def test_empty_debug_is_unavailable() -> None:
    m = build_historical_metadata_for_recommendation({})
    assert m["status"] == "unavailable"
    assert m["corpus_supplied"] is False


def test_no_corpus_headline() -> None:
    m = build_historical_metadata_for_recommendation(
        {"applied": False, "reason": "no_corpus_for_call", "corpus_supplied": False}
    )
    assert m["status"] == "unavailable"
    assert m["corpus_supplied"] is False
    assert "Heuristic only" in m["headline"]


def test_applied_includes_context_and_lanes() -> None:
    m = build_historical_metadata_for_recommendation(
        {
            "applied": True,
            "corpus_supplied": True,
            "overall_matches": 24,
            "similarity_tier": "strict",
            "overall_scale": 1.0,
            "query_buckets": {"down": 1, "distance_bucket": "medium", "field_zone": "own_territory"},
            "run_lane": {
                "lane": "run_family",
                "n": 12,
                "adjustment": 0.04,
                "success_rate": 0.58,
                "turnover_rate": 0.02,
                "gated": False,
            },
            "pass_lane": {
                "lane": "pass_family",
                "n": 12,
                "adjustment": -0.02,
                "success_rate": 0.45,
                "turnover_rate": 0.08,
                "gated": False,
            },
            "per_family": {},
        }
    )
    assert m["status"] == "applied"
    assert m["corpus_supplied"] is True
    assert m["overall_matches"] == 24
    assert m["similarity_widened"] is False
    assert m["context_blurb"] and "down 1" in m["context_blurb"].lower()
    assert m["run_lane"] and m["run_lane"]["role"] == "boost"
    assert m["pass_lane"] and m["pass_lane"]["role"] == "caution"
    assert "Historical note" in m["headline"]


def test_widened_tier_flag() -> None:
    m = build_historical_metadata_for_recommendation(
        {
            "applied": True,
            "corpus_supplied": True,
            "overall_matches": 20,
            "similarity_tier": "relax_distance",
            "similarity_tier_strength": 0.72,
            "run_lane": {"n": 15, "adjustment": 0.01, "success_rate": 0.55, "turnover_rate": 0.0, "gated": False},
            "pass_lane": {"n": 5, "adjustment": 0.0, "success_rate": 0.5, "turnover_rate": 0.0, "gated": False},
        }
    )
    assert m["similarity_widened"] is True
    assert "0.72×" in (m.get("summary") or "")


def test_similarity_widened_false_when_tier_missing() -> None:
    m = build_historical_metadata_for_recommendation(
        {
            "applied": True,
            "corpus_supplied": True,
            "overall_matches": 20,
            "similarity_tier": None,
            "run_lane": {"n": 10, "adjustment": 0.02, "success_rate": 0.5, "turnover_rate": 0.0, "gated": False},
            "pass_lane": {"n": 10, "adjustment": 0.0, "success_rate": 0.5, "turnover_rate": 0.0, "gated": False},
        }
    )
    assert m["similarity_widened"] is False
