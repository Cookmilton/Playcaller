from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from warehouse.models import DataSource, RawGamePayload

logger = logging.getLogger(__name__)

REPO_ROOT: Path = Path(__file__).resolve().parent.parent


def processed_data_dir() -> Path:
    """Repo-root ``data/processed`` (absolute). Not cwd-dependent."""
    return REPO_ROOT / "data" / "processed"


def _raw_root() -> Path:
    return REPO_ROOT / "data" / "raw"


def _game_path(season: int, week: int, internal_game_id: str) -> Path:
    return _raw_root() / str(season) / f"week_{week:02d}" / f"{internal_game_id}.json"


def _make_game_id(meta: dict[str, Any]) -> str:
    """Deterministic internal id: sha1 of f\"{season}-{week}-{away}@{home}\" truncated to 16 chars."""
    season = meta["season"]
    week = meta["week"]
    away = meta["away_team"]
    home = meta["home_team"]
    key = f"{season}-{week}-{away}@{home}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        if tmp.is_file():
            try:
                tmp.unlink()
            except OSError:
                logger.debug("Could not remove temp file %s", tmp, exc_info=True)
        raise


def _record_from_file_obj(data: dict[str, Any]) -> RawGamePayload:
    if "payload_json" in data:
        payload_json = str(data["payload_json"])
    else:
        game_body = data["game"]
        payload_json = json.dumps(game_body, indent=2, default=str)
    raw_fetched = data["fetched_at"]
    fetched_at = (
        raw_fetched
        if isinstance(raw_fetched, datetime)
        else datetime.fromisoformat(str(raw_fetched))
    )
    source_val = data["source"]
    source = source_val if isinstance(source_val, DataSource) else DataSource(str(source_val))
    return RawGamePayload(
        id=str(data["payload_id"]),
        game_id=str(data["game_id"]),
        source=source,
        fetched_at=fetched_at,
        payload_json=payload_json,
    )


def _read_payload_from_path(path: Path) -> RawGamePayload | None:
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.error("Malformed JSON in raw game file: %s", path)
        return None
    except OSError as e:
        logger.error("Could not read raw game file %s: %s", path, e)
        return None
    try:
        return _record_from_file_obj(data)
    except (KeyError, TypeError, ValueError) as e:
        logger.error("Invalid raw game record in %s: %s", path, e)
        return None


def store_raw_games(
    games: list[dict[str, Any]],
    *,
    source: DataSource = DataSource.NFLVERSE,
    overwrite: bool = False,
) -> list[RawGamePayload]:
    """Persist each game as JSON. Return one :class:`RawGamePayload` per input game."""
    out: list[RawGamePayload] = []
    _raw_root().parent.mkdir(parents=True, exist_ok=True)

    for game in games:
        meta = game["meta"]
        season = int(meta["season"])
        week = int(meta["week"])
        internal_id = _make_game_id(meta)
        path = _game_path(season, week, internal_id)

        if path.is_file() and not overwrite:
            logger.info("Skipping existing raw game file (overwrite=False): %s", path)
            loaded = _read_payload_from_path(path)
            if loaded is None:
                raise RuntimeError(f"Existing raw game file is unreadable: {path}")
            out.append(loaded)
            continue

        fetched_at = datetime.now(timezone.utc)
        payload_id = hashlib.sha1(
            f"{internal_id}-{fetched_at.isoformat()}".encode("utf-8")
        ).hexdigest()[:16]
        payload_json = json.dumps(game, indent=2, default=str)
        record = {
            "payload_id": payload_id,
            "game_id": internal_id,
            "source": source.value,
            "fetched_at": fetched_at.isoformat(),
            "payload_json": payload_json,
            "game": game,
        }
        text = json.dumps(record, indent=2, default=str)
        _atomic_write_text(path, text)
        out.append(
            RawGamePayload(
                id=payload_id,
                game_id=internal_id,
                source=source,
                fetched_at=fetched_at,
                payload_json=payload_json,
            )
        )

    return out


def load_raw_game(game_id: str) -> RawGamePayload | None:
    """Load a single :class:`RawGamePayload` by internal game id. Return None if not found."""
    matches = list(_raw_root().rglob(f"{game_id}.json"))
    if not matches:
        return None
    if len(matches) > 1:
        logger.warning("Multiple raw game files for id %s; using %s", game_id, matches[0])
    return _read_payload_from_path(matches[0])


def list_raw_games(season: int, week: int | None = None) -> list[str]:
    """List internal game_ids stored for a given season (and optional week)."""
    season_dir = _raw_root() / str(season)
    if not season_dir.is_dir():
        return []

    if week is not None:
        week_dir = season_dir / f"week_{week:02d}"
        if not week_dir.is_dir():
            return []
        dirs = [week_dir]
    else:
        dirs = sorted(p for p in season_dir.iterdir() if p.is_dir() and p.name.startswith("week_"))

    ids: list[str] = []
    for d in dirs:
        for p in d.glob("*.json"):
            ids.append(p.stem)
    return sorted(ids)
