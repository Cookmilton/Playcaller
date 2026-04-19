"""ESPN ``participants`` extraction and description enrichment."""

from playcaller.live_data.espn_play_normalize import espn_play_to_actual
from playcaller.live_data.espn_play_participants import (
    EspnPlayPeople,
    enrich_espn_actual_with_participants,
    extract_espn_play_people,
)


def test_extract_players_prefers_display_name() -> None:
    play = {
        "id": "p1",
        "participants": [
            {"athlete": {"displayName": "Justin Jefferson", "jersey": "18"}, "type": "receiver"},
            {"athlete": {"fullName": "Kirk Cousins"}, "type": "passer"},
        ],
    }
    p = extract_espn_play_people(play)
    assert p.receiver == "Justin Jefferson"
    assert p.passer == "Kirk Cousins"


def test_extract_falls_back_to_jersey_only() -> None:
    play = {
        "participants": [{"athlete": {"jersey": "23"}, "type": "rusher"}],
    }
    p = extract_espn_play_people(play)
    assert p.rusher == "#23"


def test_extract_empty_when_no_participants() -> None:
    assert extract_espn_play_people({}) == EspnPlayPeople()
    assert extract_espn_play_people({"participants": None}) == EspnPlayPeople()


def test_extract_pass_rush_phrase_not_treated_as_ball_carrier() -> None:
    play = {
        "participants": [
            {"athlete": {"displayName": "Edge Player"}, "type": "pass rush"},
        ],
    }
    p = extract_espn_play_people(play)
    assert p.rusher == ""


def test_extract_participant_type_dict_with_text() -> None:
    play = {
        "participants": [
            {"athlete": {"displayName": "Z.Wideout"}, "type": {"text": "Receiver", "id": "3"}},
        ],
    }
    p = extract_espn_play_people(play)
    assert p.receiver == "Z.Wideout"


def test_extract_sacked_by_maps_to_sacker_and_enriches() -> None:
    play = {
        "id": "sack1",
        "type": {"text": "Sack", "id": "7"},
        "text": "Sack for -8 yards",
        "statYardage": -8,
        "participants": [
            {"athlete": {"displayName": "Q.B."}, "type": "passer"},
            {"athlete": {"displayName": "D.Lineman"}, "type": "sackedBy"},
        ],
    }
    p = extract_espn_play_people(play)
    assert p.sacker == "D.Lineman"
    ap = espn_play_to_actual(play)
    assert ap is not None
    assert ap.sack is True
    ap2 = enrich_espn_actual_with_participants(ap, play)
    assert "D.Lineman" in (ap2.description or "")


def test_enrich_pass_complete_from_fixture_shape() -> None:
    play = {
        "id": "x2",
        "type": {"text": "Pass Reception", "id": "24"},
        "text": "Pass complete to wide receiver for 12 yards",
        "statYardage": 12,
        "participants": [
            {"athlete": {"displayName": "Daniel Jones", "jersey": "8"}, "type": "passer"},
            {"athlete": {"displayName": "Darius Slayton", "jersey": "18"}, "type": "receiver"},
        ],
    }
    ap = espn_play_to_actual(play)
    assert ap is not None
    assert "Darius Slayton" in (ap.description or "")
    assert "Daniel Jones" in (ap.description or "")
    assert "pass complete" in (ap.description or "")
    assert ap.feed_receiver_label == "Darius Slayton"
    assert ap.feed_receiver_jersey == "18"
    assert ap.feed_passer_jersey == "8"


def test_enrich_no_participants_preserves_base_description() -> None:
    play = {
        "id": "z1",
        "type": {"text": "Rush", "id": "5"},
        "text": "(10:00) 3 Yd Rush",
        "statYardage": 3,
    }
    ap = espn_play_to_actual(play)
    assert ap is not None
    assert "[ESPN] RB run" in (ap.description or "")
    assert ap.feed_rusher_label == ""


def test_enrich_manual_actual_without_play_dict_is_noop() -> None:
    from playcaller.domain import ActualPlayResult

    ap = ActualPlayResult(description="x", play_type="pass", result_type="complete", yards_gained=5)
    out = enrich_espn_actual_with_participants(ap, {})
    assert out.description == "x"
