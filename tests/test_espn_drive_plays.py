"""G2.1: one helper lists ESPN plays for a drive id from current or previous."""

from __future__ import annotations

import json
from pathlib import Path

from playcaller.live_data.espn_completed_drives import extract_completed_drives_from_espn_payload
from playcaller.live_data.espn_drive_plays import feed_drive_plays
from playcaller.live_data.espn_football import parse_espn_summary

ROOT = Path(__file__).resolve().parent
LIVE = ROOT / "fixtures" / "espn_summary_live_401872657.json"


def _payload() -> dict:
    return json.loads(LIVE.read_text(encoding="utf-8"))


def test_feed_drive_plays_current_drive_ordered() -> None:
    payload = _payload()
    plays = feed_drive_plays(payload, "4018726573")
    ids = [str(p.get("id")) for p in plays]
    assert ids == ["401872657543", "401872657573"]
    seqs = [int(p["sequenceNumber"]) for p in plays]
    assert seqs == sorted(seqs)


def test_feed_drive_plays_previous_drive() -> None:
    payload = _payload()
    plays = feed_drive_plays(payload, "4018726571")
    assert plays
    assert all(isinstance(p, dict) for p in plays)
    assert str(plays[0].get("id") or "")


def test_feed_drive_plays_unknown_id_is_empty() -> None:
    assert feed_drive_plays(_payload(), "no-such-drive") == []
    assert feed_drive_plays(_payload(), "") == []


def test_completed_import_and_current_merge_use_helper() -> None:
    payload = _payload()
    completed = extract_completed_drives_from_espn_payload(payload, event_id="401872657")
    kick = next(fd for fd in completed if fd.stable_key.endswith("drive:4018726571"))
    helper_ids = [str(p.get("id")) for p in feed_drive_plays(payload, "4018726571")]
    raw_ids = [str(p.get("id")) for p in kick.raw_plays]
    assert raw_ids == helper_ids
    snap = parse_espn_summary(payload, sport="nfl", our_team_id="14")
    assert [p.get("id") for p in snap.current_feed_drive_plays] == [
        p.get("id") for p in feed_drive_plays(payload, "4018726573")
    ]


def test_helper_sorts_out_of_order_sequence_numbers() -> None:
    payload = {
        "drives": {
            "current": {
                "id": "d1",
                "plays": [
                    {"id": "b", "sequenceNumber": "20"},
                    {"id": "a", "sequenceNumber": "10"},
                ],
            }
        }
    }
    assert [p["id"] for p in feed_drive_plays(payload, "d1")] == ["a", "b"]
