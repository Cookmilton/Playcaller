"""ESPN per-play feed metadata on ``ActualPlayResult`` (quarter, clock, scores)."""

from __future__ import annotations

import json
from pathlib import Path

from dataclasses import replace

import pytest

from playcaller.domain import ActualPlayResult
from playcaller.live_data.espn_play_normalize import (
    apply_espn_feed_presnap_fields,
    espn_play_to_actual,
    parse_espn_down_distance_from_text,
)

FIXTURE_PACKERS = Path(__file__).resolve().parent / "fixtures" / "espn_summary_packers_lions_401772891.json"


def _find_q4_play_with_clock() -> dict:
    d = json.loads(FIXTURE_PACKERS.read_text(encoding="utf-8"))
    prev = (d.get("drives") or {}).get("previous") or []
    for drv in prev:
        for pl in drv.get("plays") or []:
            per = (pl.get("period") or {}).get("number")
            clk = (pl.get("clock") or {}).get("displayValue") or ""
            if per == 4 and "12:56" in str(clk):
                return pl
    pytest.fail("fixture missing expected Q4 play with 12:56 clock")


def test_packers_fixture_q4_play_has_feed_metadata() -> None:
    raw = _find_q4_play_with_clock()
    ap = espn_play_to_actual(raw)
    assert ap is not None
    assert ap.feed_period_number == 4
    assert ap.feed_clock_display == "12:56"
    assert ap.feed_presnap_down == 1
    assert ap.feed_presnap_distance == 10
    assert ap.feed_home_score is not None and ap.feed_away_score is not None
    assert ap.feed_home_score == raw.get("homeScore")
    assert ap.feed_away_score == raw.get("awayScore")


def test_apply_presnap_never_invents_defaults() -> None:
    ap = replace(ActualPlayResult(), description="x")
    ap2 = apply_espn_feed_presnap_fields(ap, {})
    assert ap2.feed_period_number is None
    assert ap2.feed_clock_display is None


def test_parse_down_distance_text_variants() -> None:
    assert parse_espn_down_distance_from_text("3rd & 1", "") == (3, 1, False)
    assert parse_espn_down_distance_from_text("1st & Goal", "") == (1, None, True)
    assert parse_espn_down_distance_from_text("", "2nd & 7 at GB 41") == (2, 7, False)


def test_packers_scrimmage_canonical_field_position() -> None:
    d = json.loads(FIXTURE_PACKERS.read_text(encoding="utf-8"))
    plays = (d.get("drives") or {}).get("previous", [])[0].get("plays") or []
    assert len(plays) > 6
    ap_own = espn_play_to_actual(plays[1])
    assert ap_own is not None
    assert ap_own.feed_presnap_territory == "own"
    assert ap_own.feed_presnap_yardline == 17
    assert ap_own.feed_yards_to_endzone == 83
    ap_opp = espn_play_to_actual(plays[6])
    assert ap_opp is not None
    assert ap_opp.feed_presnap_territory == "opponents"
    assert ap_opp.feed_presnap_yardline == 40
