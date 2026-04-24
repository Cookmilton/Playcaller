from __future__ import annotations

import hashlib
import json
import logging
import math
from dataclasses import fields
from datetime import date
from typing import Any

from warehouse.models import DataSource, Game, GameStatus, GameType, Play
from warehouse.storage import _make_game_id
from warehouse.taxonomy import PlayResult, PlayType, normalize_play_result

logger = logging.getLogger(__name__)


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    if isinstance(value, float):
        if math.isnan(value):
            return None
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _str_or_none(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    s = str(value).strip()
    return s if s else None


def _bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value == 0:
            return False
        if value == 1:
            return True
        return None
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("", "nan", "none"):
            return None
        if s in ("true", "1", "t", "yes"):
            return True
        if s in ("false", "0", "f", "no"):
            return False
        return None
    return None


def _truthy(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, float) and math.isnan(value):
        return False
    if value in (False, 0, "0", ""):
        return False
    if isinstance(value, str) and value.strip().lower() in ("false", "nan", "none"):
        return False
    return bool(value)


def _team_abbr_or_none(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    s = str(value).strip()
    return s if s else None


def _is_missing_play_type(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return False


def _desc_text(row: dict[str, Any]) -> str:
    d = row.get("desc")
    if d is None or (isinstance(d, float) and math.isnan(d)):
        return ""
    return str(d).strip()


def _should_skip_row(row: dict[str, Any]) -> bool:
    if not _is_missing_play_type(row.get("play_type")):
        return False
    return _desc_text(row) == ""


def _float_for_order(pid: Any) -> float | None:
    if pid is None or (isinstance(pid, float) and math.isnan(pid)):
        return None
    try:
        return float(pid)
    except (TypeError, ValueError):
        return None


def _play_ids_strictly_increasing(rows: list[dict[str, Any]]) -> bool:
    prev: float | None = None
    for r in rows:
        cur = _float_for_order(r.get("play_id"))
        if cur is None:
            return False
        if prev is not None and cur <= prev:
            return False
        prev = cur
    return True


def _sort_key(row: dict[str, Any]) -> tuple[int, float, float]:
    q = _int_or_none(row.get("qtr"))
    if q is None or q < 1:
        q = 1
    if q > 5:
        q = 5
    sec = _int_or_none(row.get("quarter_seconds_remaining"))
    if sec is None:
        sec = 0
    pid = _float_for_order(row.get("play_id"))
    if pid is None:
        pid = float("inf")
    return (q, -float(sec), pid)


def _ordered_rows(plays: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for r in plays:
        if _should_skip_row(r):
            logger.debug("Skipping play with empty play_type and desc")
            continue
        rows.append(r)
    if not rows:
        return []
    if not _play_ids_strictly_increasing(rows):
        rows = sorted(rows, key=_sort_key)
    return rows


def _normalize_play_type_token(raw: str | None) -> PlayType:
    if raw is None:
        return PlayType.UNKNOWN
    token = raw.strip().lower()
    mapping: dict[str, PlayType] = {
        "run": PlayType.RUN,
        "rushing": PlayType.RUN,
        "pass": PlayType.PASS,
        "punt": PlayType.PUNT,
        "kickoff": PlayType.KICKOFF,
        "field_goal": PlayType.FIELD_GOAL,
        "extra_point": PlayType.EXTRA_POINT,
        "no_play": PlayType.PENALTY_NO_PLAY,
        "qb_spike": PlayType.SPIKE,
        "qb_kneel": PlayType.KNEEL,
        "timeout": PlayType.TIMEOUT,
        "two_point": PlayType.TWO_POINT,
    }
    return mapping.get(token, PlayType.UNKNOWN)


def _map_play_type(row: dict[str, Any]) -> PlayType:
    raw_pt = row.get("play_type")
    if _is_missing_play_type(raw_pt):
        return PlayType.UNKNOWN
    token = str(raw_pt).strip().lower()
    if token == "pass":
        if _truthy(row.get("sack")):
            return PlayType.SACK
        if _truthy(row.get("qb_scramble")):
            return PlayType.SCRAMBLE
        return PlayType.PASS
    return _normalize_play_type_token(token)


def _quarter_for_play(row: dict[str, Any]) -> int:
    q = _int_or_none(row.get("qtr"))
    if q is None or q < 1:
        return 1
    if q > 5:
        return 5
    return q


def _parse_game_date(meta: dict[str, Any]) -> date:
    raw = meta.get("game_date")
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        raise ValueError("game_date missing from meta")
    if isinstance(raw, date):
        return raw
    if hasattr(raw, "date") and callable(getattr(raw, "date", None)):
        try:
            d = raw.date()
            if isinstance(d, date):
                return d
        except (TypeError, ValueError, AttributeError):
            pass
    text = str(raw).strip()
    if "T" in text:
        text = text.split("T", 1)[0]
    return date.fromisoformat(text[:10])


def _game_type_from_meta(meta: dict[str, Any]) -> GameType:
    gt = meta.get("game_type")
    if gt is None:
        return GameType.REG
    try:
        return GameType(str(gt).strip().upper())
    except ValueError:
        return GameType.REG


def _infer_game_status(rows: list[dict[str, Any]]) -> GameStatus:
    if not rows:
        return GameStatus.FINAL
    for r in rows:
        res = r.get("result")
        if res is None or (isinstance(res, float) and math.isnan(res)):
            continue
        if str(res).strip() == "":
            continue
        if _int_or_none(r.get("home_score")) is not None:
            return GameStatus.FINAL
    return GameStatus.IN_PROGRESS


def _play_row_id(game_id: str, external_play_id: str) -> str:
    return hashlib.sha1(f"{game_id}-{external_play_id}".encode("utf-8")).hexdigest()[:16]


def _play_to_dict(p: Play) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in fields(Play):
        val = getattr(p, f.name)
        if isinstance(val, (PlayType, PlayResult)):
            out[f.name] = val.value
        else:
            out[f.name] = val
    return out


def normalize_game(game_payload: dict[str, Any]) -> tuple[Game, list[Play]]:
    """Build :class:`Game` and :class:`Play` rows from one Phase 3 game dict."""
    meta = game_payload["meta"]
    plays_in = game_payload["plays"]
    if not isinstance(plays_in, list):
        raise TypeError("game_payload['plays'] must be a list")

    rows = _ordered_rows(plays_in)

    internal_id = _make_game_id(meta)
    ext_gid = str(meta.get("external_game_id", ""))
    season = int(meta["season"])
    week = int(meta["week"])

    last_row = rows[-1] if rows else None
    final_home = _int_or_none(last_row.get("home_score")) if last_row else None
    final_away = _int_or_none(last_row.get("away_score")) if last_row else None

    game = Game(
        id=internal_id,
        source=DataSource.NFLVERSE,
        external_game_id=ext_gid,
        season=season,
        week=week,
        game_type=_game_type_from_meta(meta),
        home_team=str(meta.get("home_team", "") or ""),
        away_team=str(meta.get("away_team", "") or ""),
        game_date=_parse_game_date(meta),
        status=_infer_game_status(list(plays_in)),
        final_home_score=final_home,
        final_away_score=final_away,
    )

    plays_out: list[Play] = []
    for seq, row in enumerate(rows, start=1):
        ext_play = row.get("play_id")
        if ext_play is None or (isinstance(ext_play, float) and math.isnan(ext_play)):
            external_play_id = str(seq)
        elif isinstance(ext_play, float) and ext_play == int(ext_play):
            external_play_id = str(int(ext_play))
        else:
            external_play_id = str(ext_play).strip()

        q = _quarter_for_play(row)
        mapped_type = _map_play_type(row)
        desc = _desc_text(row) or ""
        play_result = normalize_play_result(desc if desc else None, mapped_type)

        first_down = (
            _truthy(row.get("first_down_rush"))
            or _truthy(row.get("first_down_pass"))
            or _truthy(row.get("first_down_penalty"))
        )
        turnover = _truthy(row.get("interception")) or _truthy(row.get("fumble_lost"))

        plays_out.append(
            Play(
                id=_play_row_id(internal_id, external_play_id),
                game_id=internal_id,
                external_play_id=external_play_id,
                play_sequence=seq,
                quarter=q,
                clock_seconds=_int_or_none(row.get("quarter_seconds_remaining")),
                possession_team=_team_abbr_or_none(row.get("posteam")),
                defense_team=_team_abbr_or_none(row.get("defteam")),
                down=_int_or_none(row.get("down")),
                distance=_int_or_none(row.get("ydstogo")),
                yardline_100=_int_or_none(row.get("yardline_100")),
                score_offense=_int_or_none(row.get("posteam_score")) or 0,
                score_defense=_int_or_none(row.get("defteam_score")) or 0,
                play_type=mapped_type,
                play_result=play_result,
                yards_gained=_int_or_none(row.get("yards_gained")),
                first_down=first_down,
                touchdown=_truthy(row.get("touchdown")),
                turnover=turnover,
                raw_description=desc,
                epa=_float_or_none(row.get("epa")),
                wpa=_float_or_none(row.get("wpa")),
                success=_bool_or_none(row.get("success")),
                shotgun=_bool_or_none(row.get("shotgun")),
                no_huddle=_bool_or_none(row.get("no_huddle")),
                qb_dropback=_bool_or_none(row.get("qb_dropback")),
                defenders_in_box=_int_or_none(row.get("defenders_in_box")),
                offense_personnel=_str_or_none(row.get("offense_personnel")),
                air_yards=_float_or_none(row.get("air_yards")),
                yards_after_catch=_float_or_none(row.get("yards_after_catch")),
                xpass=_float_or_none(row.get("xpass")),
                passer_player_name=_str_or_none(row.get("passer_player_name")),
                receiver_player_name=_str_or_none(row.get("receiver_player_name")),
                rusher_player_name=_str_or_none(row.get("rusher_player_name")),
                pass_length=_str_or_none(row.get("pass_length")),
                pass_location=_str_or_none(row.get("pass_location")),
                run_location=_str_or_none(row.get("run_location")),
                run_gap=_str_or_none(row.get("run_gap")),
            )
        )

    return game, plays_out


if __name__ == "__main__":
    import logging as _logging

    _logging.basicConfig(level=_logging.INFO)
    from warehouse.storage import list_raw_games, load_raw_game

    _ids = list_raw_games(2025, week=1)
    if not _ids:
        print("no raw games for 2025 W1")
    else:
        _raw = load_raw_game(_ids[0])
        if _raw is None:
            print("load_raw_game failed")
        else:
            _game_body = json.loads(_raw.payload_json)
            _g, _plays = normalize_game(_game_body)
            print("len(plays):", len(_plays))
            if _plays:
                print("first play:", _play_to_dict(_plays[0]))
                print("last play:", _play_to_dict(_plays[-1]))
            else:
                print("first play: {}")
                print("last play: {}")
