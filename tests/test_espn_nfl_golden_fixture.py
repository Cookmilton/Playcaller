"""
Golden coverage for ESPN NFL summary shapes (event 401772988, trimmed).

The site summary ``drives.*.plays[]`` rows in this capture omit ``participants``; names
appear only in ``text``. A final synthetic drive appends plays that keep the historical
``participants`` schema so ``extract_espn_play_people`` stays regression-tested against
real API field shapes (``type`` as a dict on the play, scalar roles on participants).
"""

from __future__ import annotations

import json
from pathlib import Path

from playcaller.live_data.espn_completed_drives import extract_completed_drives_from_espn_payload
from playcaller.live_data.espn_football import parse_espn_summary
from playcaller.live_data.espn_play_participants import extract_espn_play_people
from playcaller.live_data.espn_summary_teams import team_labels_from_espn_summary

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "espn_summary_nfl_golden.json"


def _load() -> dict:
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


def test_team_labels_from_golden_summary() -> None:
    payload = _load()
    labels = team_labels_from_espn_summary(payload)
    assert labels["17"][0] == "NE"
    assert "Patriot" in labels["17"][1]
    assert labels["26"][0] == "SEA"
    assert "Seahawk" in labels["26"][1]


def test_completed_drives_team_mapping_matches_competition() -> None:
    payload = _load()
    labels = team_labels_from_espn_summary(payload)
    drives = extract_completed_drives_from_espn_payload(payload, event_id="401772988")
    assert len(drives) >= 4
    for fd in drives:
        assert fd.team_espn_id
        assert fd.team_espn_id in labels
        assert fd.team_abbreviation == labels[fd.team_espn_id][0]
        assert fd.team_display_name == labels[fd.team_espn_id][1]


def test_completed_drives_attach_feed_audit_metadata() -> None:
    payload = _load()
    drives = extract_completed_drives_from_espn_payload(payload, event_id="401772988")
    assert drives[0].feed_audit is not None
    a = drives[0].feed_audit
    assert a.espn_result_code == "TD"
    assert a.start_period == 4
    assert a.start_clock_display == "4:27"
    assert "NE 35" in (a.start_field_text or "")
    assert a.first_play_clock_display == "4:27"
    assert a.end_clock_display == "2:21"


def test_real_trimmed_play_without_participants_yields_empty_people() -> None:
    payload = _load()
    play_id = "4017729884626"
    play = None
    for drv in (payload.get("drives") or {}).get("previous") or []:
        if not isinstance(drv, dict):
            continue
        for pl in drv.get("plays") or []:
            if isinstance(pl, dict) and str(pl.get("id")) == play_id:
                play = pl
                break
        if play is not None:
            break
    assert play is not None
    assert not play.get("participants")
    assert extract_espn_play_people(play) == extract_espn_play_people({})


def test_grafted_participant_corpus_on_golden() -> None:
    payload = _load()
    corpus = None
    for drv in (payload.get("drives") or {}).get("previous") or []:
        if isinstance(drv, dict) and str(drv.get("id", "")).endswith("fixture-participant-corpus"):
            corpus = drv
            break
    assert corpus is not None
    by_id = {str(p["id"]): p for p in corpus["plays"] if isinstance(p, dict)}
    rush = extract_espn_play_people(by_id["401test001x1"])
    assert rush.rusher == "Devin Singletary"
    rec = extract_espn_play_people(by_id["401test001x2"])
    assert rec.passer == "Daniel Jones"
    assert rec.receiver == "Darius Slayton"
    pen = extract_espn_play_people(by_id["401772988fx-pen"])
    assert pen == extract_espn_play_people({})
    sk = extract_espn_play_people(by_id["401772988fx-sack"])
    assert sk.passer == "Q.B. Passer"
    assert sk.sacker == "D.Lineman"


def test_parse_golden_no_feed_team_warnings() -> None:
    payload = _load()
    snap = parse_espn_summary(payload, sport="nfl", our_team_id="26")
    joined = " ".join(snap.debug_notes)
    assert "no team label index" not in joined
    assert "lack drive.team.id" not in joined
    assert "not in competition list" not in joined


def test_parse_debug_note_when_team_label_index_missing() -> None:
    payload = {
        "header": {"competitions": [{"id": "e1", "competitors": [], "status": {"type": {}}, "situation": None}]},
        "drives": {"previous": []},
    }
    snap = parse_espn_summary(payload, sport="nfl", our_team_id="1")
    assert any("no team label index" in n for n in snap.debug_notes)


def test_parse_debug_note_when_drive_team_id_missing() -> None:
    payload = {
        "header": {
            "competitions": [
                {
                    "id": "e1",
                    "competitors": [
                        {
                            "id": "1",
                            "homeAway": "home",
                            "team": {"id": "1", "abbreviation": "AA", "displayName": "Team A"},
                        },
                        {
                            "id": "2",
                            "homeAway": "away",
                            "team": {"id": "2", "abbreviation": "BB", "displayName": "Team B"},
                        },
                    ],
                    "status": {"type": {"completed": True}},
                    "situation": {
                        "down": 1,
                        "distance": 10,
                        "yardsToEndzone": 50,
                        "possession": "1",
                    },
                }
            ]
        },
        "drives": {"previous": [{"id": "d1", "plays": []}]},
    }
    snap = parse_espn_summary(payload, sport="nfl", our_team_id="1")
    assert any("lack drive.team.id" in n for n in snap.debug_notes)


def test_parse_debug_note_when_drive_team_not_in_competition() -> None:
    payload = {
        "header": {
            "competitions": [
                {
                    "id": "e1",
                    "competitors": [
                        {
                            "id": "1",
                            "homeAway": "home",
                            "team": {"id": "1", "abbreviation": "AA", "displayName": "Team A"},
                        },
                        {
                            "id": "2",
                            "homeAway": "away",
                            "team": {"id": "2", "abbreviation": "BB", "displayName": "Team B"},
                        },
                    ],
                    "status": {"type": {"completed": True}},
                    "situation": {
                        "down": 1,
                        "distance": 10,
                        "yardsToEndzone": 50,
                        "possession": "1",
                    },
                }
            ]
        },
        "drives": {"previous": [{"id": "d1", "team": {"id": "99"}, "plays": []}]},
    }
    snap = parse_espn_summary(payload, sport="nfl", our_team_id="1")
    assert any("not in competition list" in n and "99" in n for n in snap.debug_notes)
