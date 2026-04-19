"""Session game metadata: identity, JSON linkage, audit context."""

from __future__ import annotations

import uuid

from playcaller.domain import GameContext
from playcaller.evaluation.audit import audit_record_from_recommendation
from playcaller.game import Game, game_from_dict, game_to_dict
from playcaller.session_game_metadata import (
    SessionGameMetadata,
    audit_context_from_game_metadata,
    compact_session_summary_line,
    format_session_metadata_markdown,
    fresh_session_metadata_dict,
    session_audit_identity_warning,
    session_metadata_is_identified,
    session_metadata_warnings,
    session_flat_for_normalize,
)
from playcaller.streamlit_state.session_setup import apply_session_setup_widgets_to_game
from playcaller.streamlit_state.keys import (
    SESSION_SETUP_GAME_DATE,
    SESSION_SETUP_GAME_LABEL,
    SESSION_SETUP_IS_SIMULATED,
    SESSION_SETUP_NOTES,
    SESSION_SETUP_OPPONENT,
    SESSION_SETUP_ROSTER_VERSION,
    SESSION_SETUP_SEASON,
    SESSION_SETUP_TEAM_NAME,
)


def test_new_game_has_session_metadata() -> None:
    g = Game.new_game()
    assert isinstance(g.session_metadata, dict)
    assert g.session_metadata.get("session_game_id")
    assert "is_simulated" in g.session_metadata


def test_game_json_round_trip_session_metadata() -> None:
    g = Game.new_game()
    assert g.session_metadata is not None
    g.session_metadata["team_name"] = "Alpha"
    g.session_metadata["opponent"] = "Beta"
    g.session_metadata["game_date"] = "2026-09-18"
    g.session_metadata["is_simulated"] = True
    d = game_to_dict(g)
    assert d.get("session_metadata", {}).get("team_name") == "Alpha"
    g2 = game_from_dict(d)
    assert g2.session_metadata is not None
    assert g2.session_metadata.get("team_name") == "Alpha"
    assert g2.session_metadata.get("is_simulated") is True


def test_identified_requires_team_date_and_sim_flag_in_raw_dict() -> None:
    sid = str(uuid.uuid4())
    assert not session_metadata_is_identified(None)
    assert not session_metadata_is_identified(
        {"session_game_id": sid, "team_name": "A", "game_date": "2026-01-01"}
    )
    assert session_metadata_is_identified(
        {"session_game_id": sid, "team_name": "A", "game_date": "2026-01-01", "is_simulated": False}
    )


def test_warnings_partial_meta() -> None:
    w = session_metadata_warnings({"session_game_id": "x", "is_simulated": False})
    assert w
    assert any("team" in x.lower() for x in w)
    assert any("date" in x.lower() for x in w)


def test_audit_context_from_metadata() -> None:
    g = Game.new_game()
    assert g.session_metadata is not None
    g.session_metadata["team_name"] = "T"
    g.session_metadata["game_date"] = "2026-01-02"
    g.session_metadata["is_simulated"] = True
    ctx = audit_context_from_game_metadata(g.session_metadata)
    assert ctx is not None
    assert ctx["team_name"] == "T"
    assert ctx["is_simulated"] is True
    assert ctx["session_game_id"] == g.session_metadata.get("session_game_id")


def test_audit_record_accepts_session_context() -> None:
    g = Game.new_game()
    ctx = audit_context_from_game_metadata(g.session_metadata)
    res = {
        "ctx": GameContext(
            down=1,
            distance=10,
            yardline=25,
            territory="own",
            def_personnel="nickel",
            box_count=7,
            coverage_shell="cover_3",
            blitz_likely=False,
            safeties="single_high",
        ),
        "scores": {},
        "play": {"name": "Test"},
        "play_family": "inside_zone",
        "bucket": "medium_yardage",
        "model": {},
        "fourth_down": {},
    }
    rec = audit_record_from_recommendation(
        result=res,
        plays_at_recommend=0,
        drive_epoch=0,
        game_id=g.game_id,
        session_context=ctx,
    )
    assert rec.get("session_context", {}).get("session_game_id") == ctx.get("session_game_id")


def test_apply_widgets_preserves_session_game_id() -> None:
    g = Game.new_game()
    sid = str(g.session_metadata.get("session_game_id"))
    ss = {
        SESSION_SETUP_TEAM_NAME: "Wildcats",
        SESSION_SETUP_OPPONENT: "",
        SESSION_SETUP_GAME_DATE: "2026-08-01",
        SESSION_SETUP_GAME_LABEL: "",
        SESSION_SETUP_SEASON: "",
        SESSION_SETUP_ROSTER_VERSION: "",
        SESSION_SETUP_NOTES: "",
        SESSION_SETUP_IS_SIMULATED: False,
    }
    apply_session_setup_widgets_to_game(g, ss)
    assert g.session_metadata.get("session_game_id") == sid
    assert g.session_metadata.get("team_name") == "Wildcats"


def test_game_to_dict_lists_session_metadata_before_scoring_block() -> None:
    g = Game.new_game()
    d = game_to_dict(g)
    keys = list(d.keys())
    assert keys.index("session_metadata") < keys.index("offense_points")
    assert keys.index("session_metadata") < keys.index("drives")


def test_smoke_session_setup_audit_export_round_trip_ids_align() -> None:
    """Operator smoke: session widgets → audit (as after generate) → JSON matches session_game_id."""
    g = Game.new_game()
    sid = str(g.session_metadata.get("session_game_id"))
    ss = {
        SESSION_SETUP_TEAM_NAME: "Wildcats",
        SESSION_SETUP_OPPONENT: "Bears",
        SESSION_SETUP_GAME_DATE: "2026-08-01",
        SESSION_SETUP_GAME_LABEL: "Week 1",
        SESSION_SETUP_SEASON: "2026",
        SESSION_SETUP_ROSTER_VERSION: "v1",
        SESSION_SETUP_NOTES: "smoke",
        SESSION_SETUP_IS_SIMULATED: False,
    }
    apply_session_setup_widgets_to_game(g, ss)
    assert g.session_metadata.get("session_game_id") == sid

    ctx = audit_context_from_game_metadata(g.session_metadata)
    res = {
        "ctx": GameContext(
            down=1,
            distance=10,
            yardline=25,
            territory="own",
            def_personnel="nickel",
            box_count=7,
            coverage_shell="cover_3",
            blitz_likely=False,
            safeties="single_high",
        ),
        "scores": {},
        "play": {"name": "Smoke"},
        "play_family": "inside_zone",
        "bucket": "medium_yardage",
        "model": {},
        "fourth_down": {},
    }
    rec = audit_record_from_recommendation(
        result=res,
        plays_at_recommend=0,
        drive_epoch=0,
        game_id=g.game_id,
        session_context=ctx,
    )
    g.recommendation_audit.append(rec)

    d = game_to_dict(g)
    sm = d.get("session_metadata") or {}
    assert sm.get("session_game_id") == sid
    assert sm.get("team_name") == "Wildcats"
    audit_rows = d.get("recommendation_audit") or []
    assert len(audit_rows) == 1
    sc = (audit_rows[0].get("session_context") or {}) if isinstance(audit_rows[0], dict) else {}
    assert sc.get("session_game_id") == sid
    assert sc.get("team_name") == "Wildcats"

    g2 = game_from_dict(d)
    assert (g2.session_metadata or {}).get("session_game_id") == sid
    row0 = g2.recommendation_audit[0]
    assert (row0.get("session_context") or {}).get("session_game_id") == sid


def test_compact_summary_contains_simulated() -> None:
    m = fresh_session_metadata_dict()
    m["team_name"] = "A"
    m["opponent"] = "B"
    m["game_date"] = "2026-09-18"
    m["is_simulated"] = True
    s = compact_session_summary_line(m)
    assert "Simulated" in s


def test_from_storage_dict_generates_id_when_missing() -> None:
    m = SessionGameMetadata.from_storage_dict({"team_name": "x"})
    assert m.session_game_id


def test_format_session_metadata_markdown_lists_operator_fields() -> None:
    g = Game.new_game()
    assert g.session_metadata is not None
    g.session_metadata["team_name"] = "Owls"
    g.session_metadata["opponent"] = "Sharks"
    g.session_metadata["game_date"] = "2026-09-07"
    g.session_metadata["is_simulated"] = True
    md = format_session_metadata_markdown(g.session_metadata)
    assert "Owls" in md
    assert "Sharks" in md
    assert "Simulated" in md


def test_session_audit_identity_warning_on_mismatch() -> None:
    g = Game.new_game()
    sid = str(g.session_metadata.get("session_game_id"))
    audit = [
        {
            "session_context": {
                "session_game_id": "00000000-0000-0000-0000-000000000099",
                "team_name": "X",
            }
        }
    ]
    msg = session_audit_identity_warning(g.session_metadata, audit)
    assert msg is not None
    assert sid[:8] in msg or "does not match" in msg


def test_session_flat_for_normalize_matches_game_metadata() -> None:
    g = Game.new_game()
    assert g.session_metadata is not None
    g.session_metadata["team_name"] = "A"
    g.session_metadata["opponent"] = "B"
    g.session_metadata["game_date"] = "2026-01-05"
    g.session_metadata["game_label"] = "Scrimmage"
    g.session_metadata["season"] = "2026"
    g.session_metadata["roster_version"] = "v2"
    g.session_metadata["is_simulated"] = False
    flat = session_flat_for_normalize(g)
    assert flat["session_team_name"] == "A"
    assert flat["session_opponent"] == "B"
    assert flat["session_game_date"] == "2026-01-05"
    assert flat["session_game_label"] == "Scrimmage"
    assert flat["session_season"] == "2026"
    assert flat["session_roster_version"] == "v2"
    assert flat["session_is_simulated"] is False
    assert flat["session_game_id"] == str(g.session_metadata.get("session_game_id"))
