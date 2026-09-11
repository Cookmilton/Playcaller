"""Possession mapping, Generate/Log gating, and ``None`` propagation (non-UI)."""

import json

from playcaller.domain import ActualPlayResult
from playcaller.game import (
    DRIVE_END_PUNT,
    Game,
    complete_drive_from_plays,
    flip_possession_after_drive,
    game_from_dict,
    game_from_json,
    game_to_dict,
    game_to_json,
)
from playcaller.streamlit_state.possession import (
    GENERATE_OPPONENT_REASON,
    GENERATE_UNSET_POSSESSION_REASON,
    LOG_RESULT_UNSET_POSSESSION_REASON,
    apply_possession_from_ui,
    end_drive_blocked_reason,
    flipped_possession,
    generate_blocked_reason_for_possession,
    generate_skip_debug_reason,
    log_result_blocked_reason,
    possession_from_ui_label,
    possession_is_opponent,
    possession_is_unset,
    possession_side_radio_label,
    UI_POSSESSION_UNSET,
)
from playcaller.streamlit_state.ui_defaults import new_game_ui_values
from playcaller.ui.recommendations import recommendation_card_distance
from playcaller.domain import GameContext
from playcaller.heuristic_predictor import HeuristicPredictor


def test_fresh_game_possession_is_none() -> None:
    g = Game.new_game()
    assert g.possession is None
    assert new_game_ui_values()["ui_possession_side"] == UI_POSSESSION_UNSET


def test_possession_is_opponent_false_when_unset() -> None:
    assert possession_is_opponent(None) is False
    assert possession_is_opponent("offense") is False
    assert possession_is_opponent("defense") is True
    assert possession_is_unset(None) is True
    assert possession_is_unset("offense") is False


def test_generate_blocked_reason_unset_and_opponent() -> None:
    assert generate_blocked_reason_for_possession(None) == GENERATE_UNSET_POSSESSION_REASON
    assert generate_blocked_reason_for_possession("defense") == GENERATE_OPPONENT_REASON
    assert generate_blocked_reason_for_possession("offense") is None
    assert generate_skip_debug_reason(None) == "possession_unset"
    assert generate_skip_debug_reason("defense") == "opponent_possession"
    assert generate_skip_debug_reason("offense") is None


def test_ui_label_roundtrip() -> None:
    assert possession_from_ui_label("Our team") == "offense"
    assert possession_from_ui_label("Opponent") == "defense"
    assert possession_from_ui_label(None) is None
    assert possession_from_ui_label("Not set") is None
    assert possession_side_radio_label(possession=None) == UI_POSSESSION_UNSET
    assert possession_side_radio_label(possession="offense") == "Our team"


def test_apply_possession_from_ui_does_not_invent_our_team() -> None:
    g = Game.new_game()
    apply_possession_from_ui(g, {})
    assert g.possession is None
    apply_possession_from_ui(g, {"ui_possession_side": "Our team"})
    assert g.possession == "offense"
    apply_possession_from_ui(g, {"ui_possession_side": UI_POSSESSION_UNSET})
    assert g.possession is None


def test_export_null_possession_roundtrips() -> None:
    g = Game.new_game()
    payload = game_to_dict(g)
    assert payload["possession"] is None
    g2 = game_from_dict(payload)
    assert g2.possession is None
    legacy = game_from_dict({"game_id": "x", "drives": []})
    assert legacy.possession == "offense"


# --------------------------------------------------------------------------- flip


def _punt_drive():
    return complete_drive_from_plays(
        [ActualPlayResult(yards_gained=3, family="inside_zone", play_type="run")],
        end_kind_override=DRIVE_END_PUNT,
        possessing_team="offense",
    )


def test_flip_of_none_stays_none() -> None:
    assert flipped_possession(None) is None
    assert flipped_possession("") is None
    assert flipped_possession("offense") == "defense"
    assert flipped_possession("defense") == "offense"


def test_flip_after_drive_never_invents_defense_from_unset() -> None:
    g = Game.new_game()
    assert g.possession is None
    flip_possession_after_drive(g, _punt_drive())
    assert g.possession is None, "unknown possession must not become 'defense' on a change of possession"


def test_flip_after_drive_still_flips_known_sides() -> None:
    g = Game.new_game()
    g.possession = "offense"
    flip_possession_after_drive(g, _punt_drive())
    assert g.possession == "defense"
    flip_possession_after_drive(g, _punt_drive())
    assert g.possession == "offense"


def test_game_module_has_no_second_flip_implementation() -> None:
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "playcaller" / "game.py"
    text = src.read_text(encoding="utf-8")
    assert "flipped_possession" in text
    assert 'game.possession = "defense"' not in text
    assert 'game.possession = "offense"' not in text


def test_game_imports_possession_rules_at_module_level() -> None:
    """No deferred import: ``playcaller.possession`` is a leaf, so the cycle is gone."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "playcaller"
    game_src = (root / "game.py").read_text(encoding="utf-8")
    assert "from .possession import flipped_possession" in game_src
    body = game_src.split("def flip_possession_after_drive(", 1)[1]
    assert "import" not in body.split("\n\n", 1)[0]

    rules_src = (root / "possession.py").read_text(encoding="utf-8")
    assert "import streamlit" not in rules_src
    assert "from playcaller" not in rules_src


# --------------------------------------------------------------------------- end drive


def test_end_drive_blocked_reason_matches_generate_and_log() -> None:
    assert end_drive_blocked_reason(None) == GENERATE_UNSET_POSSESSION_REASON
    assert end_drive_blocked_reason(None) == LOG_RESULT_UNSET_POSSESSION_REASON
    assert end_drive_blocked_reason("offense") is None
    assert end_drive_blocked_reason("defense") is None, "ending the opponent's drive is normal"


def test_end_drive_guard_runs_before_any_archive_work() -> None:
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "playcaller" / "services" / "game_controller.py"
    body = src.read_text(encoding="utf-8").split("def archive_current_drive_and_reset_session(", 1)[1]
    guard = body.index("end_drive_blocked_reason(")
    assert guard < body.index("complete_drive_from_plays(")
    assert guard < body.index("flip_possession_after_drive(")
    assert guard < body.index("dl.reset()")


def test_every_end_drive_button_goes_through_the_single_choke_point() -> None:
    """One-tap End buttons must not archive on their own, and must be disabled when unset."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "playcaller" / "ui" / "sidebar.py"
    text = src.read_text(encoding="utf-8")
    call_sites = text.count("archive_current_drive_and_reset_session(")
    assert call_sites == 9
    assert text.count("disabled=bool(end_block)") == call_sites
    assert "complete_drive_from_plays(" not in text


def _captured_game_log_warnings(monkeypatch) -> list[str]:
    """Capture ``playcaller.game`` warnings directly (caplog can miss them in a full run)."""
    import playcaller.game as game_mod

    lines: list[str] = []
    real = game_mod.logger.warning

    def _wrap(msg, *args, **kwargs):
        lines.append(msg % args if args else str(msg))
        real(msg, *args, **kwargs)

    monkeypatch.setattr(game_mod.logger, "warning", _wrap)
    return lines


def test_end_drive_cannot_reach_possessing_team_coercion_with_unset_possession(monkeypatch) -> None:
    import playcaller.services.game_controller as gc
    from playcaller.state import DriveLogger

    game = Game.new_game()
    assert game.possession is None
    drive_log = DriveLogger()
    drive_log.log(ActualPlayResult(yards_gained=4, family="inside_zone", play_type="run"))

    warnings: list[str] = []

    class _SessionState(dict):
        def __getattr__(self, name: str):
            return self[name]

    class _StubStreamlit:
        session_state = _SessionState(game=game, drive_log=drive_log)

        @staticmethod
        def warning(msg: str) -> None:
            warnings.append(str(msg))

    monkeypatch.setattr(gc, "st", _StubStreamlit)
    coercions = _captured_game_log_warnings(monkeypatch)
    gc.archive_current_drive_and_reset_session()

    assert warnings == [GENERATE_UNSET_POSSESSION_REASON]
    assert game.drives == [], "an unset board must not archive a drive"
    assert len(drive_log.results) == 1, "the in-progress drive must survive a blocked End drive"
    assert coercions == [], "End drive must not reach the possessing_team coercion"


def test_possessing_team_coercion_is_audited(monkeypatch) -> None:
    from playcaller.game import _norm_possessing_team

    logged = _captured_game_log_warnings(monkeypatch)
    assert _norm_possessing_team(None) == "offense"
    assert len(logged) == 1
    assert "coerced" in logged[0]

    logged.clear()
    assert _norm_possessing_team("defense") == "defense"
    assert _norm_possessing_team("offense") == "offense"
    assert logged == []


# --------------------------------------------------------------------------- legacy JSON


def test_legacy_json_values_load_unchanged() -> None:
    for value in ("offense", "defense"):
        raw = json.dumps({"game_id": "legacy", "possession": value, "drives": []})
        assert game_from_json(raw).possession == value


def test_legacy_json_without_possession_key_loads_as_offense() -> None:
    """Pre-C.1 exports always had a side; absence means an old writer, not an unset board."""
    raw = json.dumps({"game_id": "legacy", "offense_points": 7, "drives": []})
    g = game_from_json(raw)
    assert g.possession == "offense"
    assert g.offense_points == 7


def test_explicit_null_possession_loads_as_unset() -> None:
    raw = json.dumps({"game_id": "fresh", "possession": None, "drives": []})
    assert game_from_json(raw).possession is None


def test_export_serializes_unset_possession_as_json_null_not_the_string_none() -> None:
    g = Game.new_game()
    raw = game_to_json(g)
    assert '"possession": null' in raw
    assert '"None"' not in raw
    assert json.loads(raw)["possession"] is None
    assert game_from_json(raw).possession is None


def test_snap_review_rows_omit_possession_when_unset() -> None:
    from playcaller.evaluation.audit import audit_record_from_recommendation

    ctx = GameContext(down=1, distance=10, yardline=25, territory="own")
    result = {"ctx": ctx, "scores": {}, "play": {}, "model_input": None, "model": {}}
    row_unset = audit_record_from_recommendation(
        result=result, plays_at_recommend=0, drive_epoch=0, game_id="g", team_possession=None
    )
    assert "team_possession" not in row_unset
    assert "None" not in json.dumps(row_unset)

    row_set = audit_record_from_recommendation(
        result=result, plays_at_recommend=0, drive_epoch=0, game_id="g", team_possession="offense"
    )
    assert row_set["team_possession"] == "offense"


# --------------------------------------------------------------------------- log result


def test_log_result_blocked_only_when_possession_unset() -> None:
    assert log_result_blocked_reason(None) == LOG_RESULT_UNSET_POSSESSION_REASON
    assert log_result_blocked_reason(None) == GENERATE_UNSET_POSSESSION_REASON
    assert log_result_blocked_reason("offense") is None
    assert log_result_blocked_reason("defense") is None


def test_log_play_checks_the_block_before_mutating_state() -> None:
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "playcaller" / "ui" / "recommendations.py"
    body = src.read_text(encoding="utf-8").split("def _log_play(", 1)[1]
    guard = body.index("log_result_blocked_reason(")
    assert guard < body.index("UNDO_BUNDLE")
    assert guard < body.index("drive_log.log(")


# --------------------------------------------------------------------------- downstream readers


def test_review_overview_possession_note_is_unknown_not_opponent() -> None:
    from playcaller.ui.review_helpers import compute_review_overview

    g = Game.new_game()
    assert compute_review_overview(g, [], {})["possession_note"] == "Possession not set"
    g.possession = "defense"
    assert compute_review_overview(g, [], {})["possession_note"] == "Opponent offense (session)"
    g.possession = "offense"
    assert compute_review_overview(g, [], {})["possession_note"] == "Our offense"


def test_warehouse_advisory_never_stringifies_none_possession() -> None:
    from pathlib import Path

    import playcaller.warehouse.advisory as advisory_mod

    src = Path(advisory_mod.__file__).read_text(encoding="utf-8")
    assert "str(game.possession)" not in src
    line = advisory_mod._situation_line(
        GameContext(down=1, distance=10, yardline=25, territory="own"), possession="offense"
    )
    assert "None" not in line


def test_team_history_lookups_are_empty_when_possession_unset() -> None:
    from playcaller.features import plays_for_possessing_team, prior_possessing_team_drive_stats

    g = Game.new_game()
    g.drives.append(_punt_drive())
    assert plays_for_possessing_team(g, None) == []
    assert prior_possessing_team_drive_stats(g) == (0, 0)
    g.possession = "offense"
    assert len(plays_for_possessing_team(g, None)) == 1
    assert prior_possessing_team_drive_stats(g) == (1, 1)


def test_recommendation_card_keeps_board_distance_not_clamp() -> None:
    board = GameContext(down=1, distance=31, yardline=25, territory="own")
    normalized = HeuristicPredictor().normalize_context(board, None)
    assert normalized.distance == 25
    assert board.distance == 31
    assert recommendation_card_distance(board) == 31
    assert recommendation_card_distance(board) != normalized.distance


def test_game_controller_does_not_import_playcaller_ui() -> None:
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "playcaller" / "services" / "game_controller.py"
    text = src.read_text(encoding="utf-8")
    assert "from playcaller.ui" not in text
    assert "import playcaller.ui" not in text
    assert "from playcaller.streamlit_state.possession import" in text
    assert "generate_blocked_reason_for_possession" in text
    assert "generate_skip_debug_reason" in text
