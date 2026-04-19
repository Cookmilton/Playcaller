"""ModelInput game-flow features from ``Game`` + ``DriveLogger``."""

from __future__ import annotations

from playcaller.domain import ActualPlayResult, GameContext
from playcaller.features import extract_model_input, plays_for_possessing_team, prior_possessing_team_drive_stats
from playcaller.game import Game, complete_drive_from_plays
from playcaller.state import DriveLogger


def _ctx() -> GameContext:
    return GameContext(down=2, distance=6, yardline=45, territory="opponents")


def test_extract_without_game_matches_drive_log_only() -> None:
    log = DriveLogger()
    log.log(ActualPlayResult(family="inside_zone", play_type="run"))
    log.log(ActualPlayResult(family="inside_zone", play_type="run"))
    m = extract_model_input(_ctx(), log, game=None)
    assert m.features["game_flow_prior_plays"] == 0
    assert m.features["game_flow_prior_drives"] == 0
    assert m.features["game_flow_seq_len"] == 2
    assert m.features["weighted_run_share"] == 1.0
    assert m.features["game_flow_weighted_run_share"] == 1.0


def test_prior_archived_drives_feed_game_flow() -> None:
    g = Game.new_game()
    d1 = complete_drive_from_plays(
        [
            ActualPlayResult(family="inside_zone", play_type="run"),
            ActualPlayResult(family="inside_zone", play_type="run"),
            ActualPlayResult(family="inside_zone", play_type="run"),
        ],
        possessing_team="offense",
    )
    g.drives.append(d1)
    g.possession = "offense"
    log = DriveLogger()
    log.log(ActualPlayResult(family="quick_game", play_type="pass"))
    ctx = _ctx()
    ctx.plays_this_drive = len(log.results)
    ctx.run_plays_this_drive = log.run_count()
    m = extract_model_input(ctx, log, game=g)
    assert m.features["game_flow_prior_drives"] == 1
    assert m.features["game_flow_prior_plays"] == 3
    assert m.features["game_flow_seq_len"] == 4
    assert m.features["plays_this_drive"] == 1
    assert "gf_w_family__inside_zone" in m.features
    assert "gf_w_family__quick_game" in m.features


def test_opponent_drives_excluded_from_flow() -> None:
    g = Game.new_game()
    g.drives.append(
        complete_drive_from_plays(
            [ActualPlayResult(family="dropback_pass", play_type="pass")],
            possessing_team="defense",
        )
    )
    g.possession = "offense"
    log = DriveLogger()
    log.log(ActualPlayResult(family="inside_zone", play_type="run"))
    plays = plays_for_possessing_team(g, log)
    assert len(plays) == 1
    assert plays[0].family == "inside_zone"
    pr_dr, pr_pl = prior_possessing_team_drive_stats(g)
    assert pr_dr == 0
    assert pr_pl == 0