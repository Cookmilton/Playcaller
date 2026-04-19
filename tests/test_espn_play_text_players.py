"""Tier-2 ESPN play text parsing (no structured ``participants``)."""

from __future__ import annotations

import json
from pathlib import Path

from playcaller.live_data.espn_play_normalize import espn_play_to_actual
from playcaller.live_data.espn_play_text_players import (
    parse_espn_play_text_players,
    strip_leading_parenthetical_segments,
)


def test_strip_preamble_parentheticals() -> None:
    raw = "(No Huddle, Shotgun) D.Maye pass short right to T.Henderson for 24 yards."
    assert strip_leading_parenthetical_segments(raw).startswith("D.Maye")


def test_parse_pass_initial_last_names() -> None:
    t = parse_espn_play_text_players(
        "(No Huddle, Shotgun) D.Maye pass short right to T.Henderson to SEA 29 for 24 yards (J.Love)."
    )
    assert t.passer == "D.Maye"
    assert t.receiver == "T.Henderson"


def test_parse_sack_by() -> None:
    t = parse_espn_play_text_players("M.Stafford sacked by A.Donald for -7 yards")
    assert t.passer == "M.Stafford"
    assert t.sacked_by == "A.Donald"


def test_parse_scramble() -> None:
    t = parse_espn_play_text_players("J.Hurts scrambles left end for 12 yards")
    assert t.passer == "J.Hurts"


def test_parse_rush_direction() -> None:
    t = parse_espn_play_text_players("K.Walker left tackle for 6 yards")
    assert t.rusher == "K.Walker"


def test_parse_generic_wide_receiver_jersey_only() -> None:
    t = parse_espn_play_text_players("Pass complete to wide receiver #18 for 7 yards")
    assert t.receiver == ""
    assert t.receiver_role == "WR"
    assert t.receiver_jersey == "18"


def test_parse_skips_interception_wording() -> None:
    t = parse_espn_play_text_players("J.Allen pass short middle intercepted at BUF 40")
    assert t.passer == ""
    assert t.receiver == ""


def test_golden_current_play_text_enriches_end_to_end() -> None:
    """Real NFL summary row shape: names only in ``text`` (see espn_summary_nfl_golden.json)."""
    fixture = Path(__file__).resolve().parent / "fixtures" / "espn_summary_nfl_golden.json"
    with open(fixture, encoding="utf-8") as f:
        payload = json.load(f)
    play = None
    cur = (payload.get("drives") or {}).get("current") or {}
    for pl in cur.get("plays") or []:
        if isinstance(pl, dict) and str(pl.get("id")) == "4017729884626":
            play = pl
            break
    assert play is not None
    ap = espn_play_to_actual(play)
    assert ap is not None
    assert "D.Maye" in (ap.description or "") or "Maye" in (ap.description or "")
    assert "Henderson" in (ap.description or "") or "T.Henderson" in (ap.description or "")


def test_completed_drive_same_enrichment_as_normalize_path() -> None:
    """``espn_play_to_actual`` is shared by completed + current drive import."""
    play = {
        "id": "tx1",
        "type": {"text": "Pass Reception", "id": "24"},
        "text": "(12:00) A.Rodgers pass deep left to D.Adams for 22 yards",
        "statYardage": 22,
    }
    ap = espn_play_to_actual(play)
    assert ap is not None
    assert "Rodgers" in (ap.feed_passer_label or "") or "A.Rodgers" in (ap.description or "")
    assert "Adams" in (ap.feed_receiver_label or "") or "Adams" in (ap.description or "")
