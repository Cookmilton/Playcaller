"""ESPN competition → team label index."""

import json
from pathlib import Path

from playcaller.live_data.espn_summary_teams import team_label_pair, team_labels_from_espn_summary

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "espn_summary_live_synthetic.json"


def test_team_labels_from_fixture() -> None:
    with open(FIXTURE, encoding="utf-8") as f:
        payload = json.load(f)
    labels = team_labels_from_espn_summary(payload)
    assert labels["10"][0] == "NYG"
    assert "Giants" in labels["10"][1]
    assert labels["14"][0] == "LAR"
    assert "Rams" in labels["14"][1]


def test_team_label_pair_unknown_id() -> None:
    ab, disp = team_label_pair({}, "99")
    assert ab == "?"
    assert "99" in disp
