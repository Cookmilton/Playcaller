"""Historical game JSON corpus: load, normalize, and error handling (no engine wiring)."""

from __future__ import annotations

import json

from playcaller.domain import ActualPlayResult
from playcaller.game import Game, complete_drive_from_plays, game_to_dict, game_to_json
from playcaller.history import (
    GameJsonLoadError,
    HistoryCorpus,
    NormalizedHistoricalPlay,
    build_normalized_plays,
    linked_actual_matches_play,
    load_game_json_path,
    load_history_directory,
    parse_game_dict,
)
from playcaller.history.normalize import (
    derive_distance_bucket,
    derive_explosive,
    derive_field_zone,
    derive_play_success,
    derive_yardline_100,
)


def test_parse_game_dict_matches_game_from_dict() -> None:
    g = Game.new_game()
    d = game_to_dict(g)
    g2 = parse_game_dict(d)
    assert g2.game_id == g.game_id
    assert len(g2.drives) == len(g.drives)


def test_build_normalized_plays_carries_session_metadata() -> None:
    g = Game.new_game()
    assert g.session_metadata is not None
    g.session_metadata["team_name"] = "Tigers"
    g.session_metadata["is_simulated"] = True
    g.drives = [
        complete_drive_from_plays(
            [ActualPlayResult(yards_gained=3, family="inside_zone", play_type="run")],
            possessing_team="offense",
        )
    ]
    row = build_normalized_plays(g, source_path="p.json")[0]
    assert row.session_team_name == "Tigers"
    assert row.session_is_simulated is True
    assert row.session_game_id == str(g.session_metadata.get("session_game_id"))


def test_build_normalized_plays_orders_and_provenance() -> None:
    g = Game.new_game()
    d = complete_drive_from_plays(
        [
            ActualPlayResult(yards_gained=4, family="inside_zone", play_type="run"),
            ActualPlayResult(yards_gained=12, family="quick_game", play_type="pass", first_down=True),
        ],
        possessing_team="offense",
    )
    g.drives = [d]
    rows = build_normalized_plays(g, source_path="/tmp/x.json", schema_version=1, game_label="Week 1")
    assert len(rows) == 2
    assert rows[0].drive_index == 0 and rows[0].play_index == 0
    assert rows[0].absolute_snap_index == 0
    assert rows[1].absolute_snap_index == 1
    assert rows[0].possessing_team == "offense"
    assert rows[0].actual.family == "inside_zone"
    assert rows[0].source_path == "/tmp/x.json"
    assert rows[0].schema_version == 1
    assert rows[0].game_label == "Week 1"
    assert rows[0].recommended_family is None
    assert "x.json" in rows[0].record_key


def test_build_normalized_plays_joins_closed_audit() -> None:
    g = Game.new_game()
    play = ActualPlayResult(
        concept_name="Test play",
        family="inside_zone",
        play_type="run",
        yards_gained=5,
        result_type="short",
    )
    g.drives = [complete_drive_from_plays([play], possessing_team="offense")]
    g.recommendation_audit = [
        {
            "snap_id": "snap1",
            "status": "closed",
            "drive_epoch": 3,
            "plays_at_recommend": 0,
            "selected_family": "inside_zone",
            "selected_play_name": "IZ strong",
            "bucket": "medium_yardage",
            "pre_snap": {
                "down": 1,
                "distance": 10,
                "yardline": 30,
                "territory": "own",
                "quarter": 2,
                "seconds_remaining": 900,
                "score_diff": 0,
            },
            "linked_actual": {
                "concept_name": "Test play",
                "family": "inside_zone",
                "yards_gained": 5,
                "result_type": "short",
            },
        }
    ]
    rows = build_normalized_plays(g, source_path="f.json")
    assert len(rows) == 1
    r = rows[0]
    assert r.recommended_family == "inside_zone"
    assert r.recommended_play_name == "IZ strong"
    assert r.recommendation_bucket == "medium_yardage"
    assert r.quarter == 2
    assert r.down == 1
    assert r.distance == 10
    assert r.territory == "own"
    assert r.yardline == 30
    assert r.yardline_100 == 30
    assert r.field_zone == "open_field"
    assert r.situation_bucket is not None
    assert r.distance_bucket == "long"
    assert r.family_match is True
    assert r.audit_snap_id == "snap1"
    assert r.raw_audit_ref is not None
    assert r.raw_audit_ref.get("drive_epoch") == 3


def test_linked_actual_matches_play_partial_keys() -> None:
    p = ActualPlayResult(concept_name="A", family="power", yards_gained=2, result_type="short")
    assert linked_actual_matches_play({"family": "power"}, p)
    assert not linked_actual_matches_play({"family": "draw"}, p)


def test_load_history_directory_skips_bad_files(tmp_path) -> None:
    good = Game.new_game()
    good.drives = [
        complete_drive_from_plays(
            [ActualPlayResult(yards_gained=1, family="power", play_type="run")],
            possessing_team="offense",
        )
    ]
    (tmp_path / "a.json").write_text(game_to_json(good), encoding="utf-8")
    (tmp_path / "bad.json").write_text("not json", encoding="utf-8")
    (tmp_path / "bad2.json").write_text(json.dumps(["list"]), encoding="utf-8")

    corpus = load_history_directory(tmp_path)
    assert len(corpus.games) == 1
    assert len(corpus.plays) == 1
    assert isinstance(corpus.plays[0], NormalizedHistoricalPlay)
    assert len(corpus.errors) == 2
    assert all(isinstance(e, GameJsonLoadError) for e in corpus.errors)


def test_load_history_directory_game_label_in_snapshot(tmp_path) -> None:
    g = Game.new_game()
    g.drives = [
        complete_drive_from_plays(
            [ActualPlayResult(yards_gained=3, family="inside_zone", play_type="run")],
            possessing_team="offense",
        )
    ]
    payload = json.loads(game_to_json(g))
    payload["game_label"] = "Scrimmage A"
    (tmp_path / "x.json").write_text(json.dumps(payload), encoding="utf-8")
    corpus = load_history_directory(tmp_path)
    assert corpus.games[0].game_label == "Scrimmage A"
    assert corpus.plays[0].game_label == "Scrimmage A"


def test_load_history_directory_recursive(tmp_path) -> None:
    sub = tmp_path / "nested"
    sub.mkdir()
    g = Game.new_game()
    (sub / "deep.json").write_text(game_to_json(g), encoding="utf-8")

    flat = load_history_directory(tmp_path, recursive=False)
    assert len(flat.games) == 0

    deep = load_history_directory(tmp_path, recursive=True)
    assert len(deep.games) == 1


def test_load_game_json_path_round_trip(tmp_path) -> None:
    g = Game.new_game()
    p = tmp_path / "one.json"
    p.write_text(game_to_json(g), encoding="utf-8")
    g2 = load_game_json_path(p)
    assert g2.game_id == g.game_id


def test_missing_directory_returns_error() -> None:
    corpus = load_history_directory("/nonexistent/path/abc123")
    assert len(corpus.errors) == 1
    assert corpus.plays == []


def test_empty_directory_is_valid_history_corpus(tmp_path) -> None:
    corpus = load_history_directory(tmp_path)
    assert corpus.plays == []
    assert corpus.games == []
    assert corpus.errors == []
    assert corpus.notes == []


def test_load_history_directory_max_json_files(tmp_path) -> None:
    for i in range(5):
        g = Game.new_game()
        (tmp_path / f"g{i}.json").write_text(game_to_json(g), encoding="utf-8")
    corpus = load_history_directory(tmp_path, max_json_files=2)
    assert len(corpus.games) == 2
    assert len(corpus.notes) == 1


def test_derive_helpers_red_zone_and_success() -> None:
    assert derive_field_zone(territory="opponents", yardline=15) == "red_zone"
    assert derive_yardline_100(territory="opponents", yardline=40) == 60
    assert derive_distance_bucket(down=4, distance=1) == "fourth_down"
    p = ActualPlayResult(yards_gained=10, first_down=False, touchdown=False)
    assert derive_play_success(p, down=1, distance=10) is True
    assert derive_explosive(ActualPlayResult(yards_gained=20)) is True


def test_preserving_game_from_dict_without_history_module() -> None:
    """Repository package must not alter core JSON parsing."""
    g = Game.new_game()
    d = game_to_dict(g)
    g2 = parse_game_dict(d)
    assert isinstance(g2, Game)
    assert g2.game_id == g.game_id
    assert g2.session_metadata is not None
    assert g2.session_metadata.get("session_game_id") == g.session_metadata.get("session_game_id")


def test_game_label_from_session_metadata() -> None:
    from playcaller.history.loader import _game_label_from_payload

    assert (
        _game_label_from_payload(
            {
                "session_metadata": {
                    "team_name": "A",
                    "opponent": "B",
                    "game_date": "2026-09-18",
                }
            }
        )
        == "A vs B (2026-09-18)"
    )
