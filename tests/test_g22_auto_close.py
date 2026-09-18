"""G2.2 auto-close leftover DriveLogger when ESPN current drive id moves on.

Derived payloads are copied from ``tests/fixtures/espn_summary_mnf_401872931.json``
(real MNF capture). Drive ``4018729311`` (DEN INT) is re-labelled as ``drives.current``,
then completed with a new current id.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from playcaller.game import Game, OUTCOME_SOURCE_ESPN, YARDS_SOURCE_ESPN
from playcaller.live_data.drive_boundaries import PREVIOUS_FEED_DRIVE_OPEN, espn_play_ids_from_plays
from playcaller.live_data.espn_football import parse_espn_summary
from playcaller.live_data.sync import SyncOptions, apply_snapshot
from playcaller.state import DriveLogger
from playcaller.streamlit_state.keys import (
    LIVE_FEED_AUTO_CLOSE_SUPPRESS_KEYS,
    LIVE_FEED_COACHED_TEAM_ESPN_ID,
    LIVE_FEED_LAST_AUDIT,
    LIVE_FEED_MERGED_ESPN_DRIVE_KEYS,
    LIVE_FEED_SEEN_PLAY_IDS,
    LIVE_FEED_TEAM_SCOPE,
)

ROOT = Path(__file__).resolve().parents[1]
MNF = ROOT / "tests/fixtures/espn_summary_mnf_401872931.json"
DEN_ID = "7"
EVENT_ID = "401872931"
# Source: espn_summary_mnf_401872931.json drives.previous[0]
DEN_DRIVE_ID = "4018729311"
DEN_STABLE_KEY = f"{EVENT_ID}|drive:{DEN_DRIVE_ID}"


def _mnf() -> dict:
    return json.loads(MNF.read_text(encoding="utf-8"))


def _derived_open_den_current() -> dict:
    """*_derived_*: MNF previous[0] (DEN INT) becomes drives.current; no previous."""
    raw = _mnf()
    den0 = copy.deepcopy(raw["drives"]["previous"][0])
    out = copy.deepcopy(raw)
    out["drives"]["previous"] = []
    out["drives"]["current"] = den0
    return out


def _derived_den_completed_new_current(*, include_result: bool = True) -> dict:
    """*_derived_*: DEN INT is completed; current is a stub of the next (KC) drive."""
    raw = _mnf()
    den0 = copy.deepcopy(raw["drives"]["previous"][0])
    kc1 = copy.deepcopy(raw["drives"]["previous"][1])
    if not include_result:
        den0["result"] = None
        den0["displayResult"] = None
        den0["shortDisplayResult"] = None
    out = copy.deepcopy(raw)
    out["drives"]["previous"] = [den0]
    plays = list(kc1.get("plays") or [])[:2]
    out["drives"]["current"] = {
        "id": str(kc1.get("id") or "4018729312") + "-open",
        "team": dict(kc1.get("team") or {}),
        "plays": plays,
    }
    return out


def _session(*, possession: str | None = "offense") -> dict:
    g = Game.new_game()
    g.possession = possession
    return {
        "game": g,
        "drive_log": DriveLogger(),
        LIVE_FEED_TEAM_SCOPE: "both",
        LIVE_FEED_COACHED_TEAM_ESPN_ID: DEN_ID,
        LIVE_FEED_MERGED_ESPN_DRIVE_KEYS: [],
        LIVE_FEED_SEEN_PLAY_IDS: [],
        "eval_drive_epoch": 0,
        "ui_drive_end_on_new": "auto",
    }


def _snap(payload: dict):
    return parse_espn_summary(payload, sport="nfl", our_team_id=DEN_ID)


def _apply(ss: dict, payload: dict):
    return apply_snapshot(
        game=ss["game"],
        session=ss,
        drive_log=ss["drive_log"],
        snapshot=_snap(payload),
        options=SyncOptions(),
    )


def test_g22_auto_close_archives_once_across_double_sync() -> None:
    ss = _session()
    _apply(ss, _derived_open_den_current())
    assert ss["drive_log"].results
    n_open = len(ss["drive_log"].results)
    assert n_open >= 1
    r1 = _apply(ss, _derived_den_completed_new_current())
    assert "auto_closed_leftover_drive" in r1.applied_fields
    assert PREVIOUS_FEED_DRIVE_OPEN not in r1.skipped_reasons
    assert ss["drive_log"].results == []
    assert len(ss["game"].drives) == 1
    assert DEN_STABLE_KEY in (ss.get(LIVE_FEED_MERGED_ESPN_DRIVE_KEYS) or [])
    r2 = _apply(ss, _derived_den_completed_new_current())
    assert "auto_closed_leftover_drive" not in r2.applied_fields
    assert len(ss["game"].drives) == 1


def _derived_new_current_den_not_yet_completed() -> dict:
    """*_derived_*: current id moved on; DEN INT is not in ``drives.previous`` yet."""
    raw = _mnf()
    kc1 = copy.deepcopy(raw["drives"]["previous"][1])
    out = copy.deepcopy(raw)
    out["drives"]["previous"] = []
    plays = list(kc1.get("plays") or [])[:2]
    out["drives"]["current"] = {
        "id": str(kc1.get("id") or "4018729312") + "-open",
        "team": dict(kc1.get("team") or {}),
        "plays": plays,
    }
    return out


def test_g22_hold_when_old_drive_not_yet_completed() -> None:
    ss = _session()
    _apply(ss, _derived_open_den_current())
    r = _apply(ss, _derived_new_current_den_not_yet_completed())
    assert "auto_closed_leftover_drive" not in r.applied_fields
    assert PREVIOUS_FEED_DRIVE_OPEN in r.skipped_reasons
    assert ss["drive_log"].results
    assert ss["game"].drives == []


def test_g22_hold_when_completed_drive_has_no_result() -> None:
    ss = _session()
    _apply(ss, _derived_open_den_current())
    r = _apply(ss, _derived_den_completed_new_current(include_result=False))
    assert "auto_closed_leftover_drive" not in r.applied_fields
    assert PREVIOUS_FEED_DRIVE_OPEN in r.skipped_reasons
    assert ss["drive_log"].results
    assert ss["game"].drives == []


def test_g22_hold_when_possession_unset() -> None:
    ss = _session(possession=None)
    _apply(ss, _derived_open_den_current())
    ss["game"].possession = None
    r = _apply(ss, _derived_den_completed_new_current())
    assert "auto_closed_leftover_drive" not in r.applied_fields
    assert PREVIOUS_FEED_DRIVE_OPEN in r.skipped_reasons
    assert ss["drive_log"].results


def test_g22_hold_when_auto_close_suppressed() -> None:
    ss = _session()
    ss[LIVE_FEED_AUTO_CLOSE_SUPPRESS_KEYS] = [DEN_STABLE_KEY]
    _apply(ss, _derived_open_den_current())
    r = _apply(ss, _derived_den_completed_new_current())
    assert "auto_closed_leftover_drive" not in r.applied_fields
    assert PREVIOUS_FEED_DRIVE_OPEN in r.skipped_reasons


def test_g22_no_duplicate_play_ids_after_auto_close_and_import() -> None:
    ss = _session()
    _apply(ss, _derived_open_den_current())
    _apply(ss, _derived_den_completed_new_current())
    ids = [str(p.external_play_id) for d in ss["game"].drives for p in d.plays if p.external_play_id]
    ids += [str(p.external_play_id) for p in ss["drive_log"].results if p.external_play_id]
    assert ids
    assert len(ids) == len(set(ids))
    aud = ss[LIVE_FEED_LAST_AUDIT]
    assert aud.get("drives_imported", 0) == 0 or DEN_STABLE_KEY in (ss.get(LIVE_FEED_MERGED_ESPN_DRIVE_KEYS) or [])


def test_g22_possessing_team_from_feed_ids() -> None:
    ss = _session(possession="defense")
    _apply(ss, _derived_open_den_current())
    _apply(ss, _derived_den_completed_new_current())
    assert len(ss["game"].drives) == 1
    dr = ss["game"].drives[0]
    assert dr.possessing_team == "offense"
    assert dr.outcome_source == OUTCOME_SOURCE_ESPN
    assert dr.yards_source == YARDS_SOURCE_ESPN
    assert espn_play_ids_from_plays(dr.plays)
