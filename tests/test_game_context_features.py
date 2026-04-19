"""Aggregated game-context feature extraction (no logging pipeline)."""

from __future__ import annotations

from playcaller.domain import ActualPlayResult, GameContext
from playcaller.features import extract_model_input
from playcaller.game import Game, complete_drive_from_plays
from playcaller.game_context_features import build_game_context_features
from playcaller.state import DriveLogger


def test_build_gcf_synthetic_late_down_split() -> None:
    g = Game.new_game()
    # One archived drive: several plays without first downs then a first down
    plays = [
        ActualPlayResult(family="inside_zone", play_type="run", yards_gained=2, first_down=False),
        ActualPlayResult(family="inside_zone", play_type="run", yards_gained=3, first_down=False),
        ActualPlayResult(family="quick_game", play_type="pass", yards_gained=8, first_down=True),
    ]
    d = complete_drive_from_plays(plays, possessing_team="offense")
    g.drives.append(d)
    g.possession = "offense"
    log = DriveLogger()
    log.log(ActualPlayResult(family="dropback_pass", play_type="pass", yards_gained=12, first_down=False))
    gcf = build_game_context_features(g, log, last_n=5)
    assert gcf["sample_size_plays"] == 4
    late = gcf["by_synthetic_down"]["late_3_4"]
    assert late["n"] >= 1
    assert gcf["last_archived_drive_result_kind"]


def test_gcf_target_role_share() -> None:
    log = DriveLogger()
    log.log(
        ActualPlayResult(
            family="quick_game",
            play_type="pass",
            target_role_label="Z",
            yards_gained=6,
            first_down=True,
        )
    )
    log.log(
        ActualPlayResult(
            family="dropback_pass",
            play_type="pass",
            target_role_label="Z",
            yards_gained=4,
            first_down=False,
        )
    )
    gcf = build_game_context_features(None, log, last_n=5)
    assert gcf["target_role_share"].get("Z", 0) >= 0.9


def test_extract_model_input_embeds_game_context_features_meta() -> None:
    ctx = GameContext(down=1, distance=10, yardline=25, territory="own")
    m = extract_model_input(ctx, DriveLogger(), game=Game.new_game())
    assert "game_context_features" in m.meta
    assert "gcf_overall_run_share" in m.features
