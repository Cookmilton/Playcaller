"""
Load saved game JSON files into a ``HistoryCorpus`` of normalized play rows.

Parse path matches the app: ``read`` → ``json.loads`` → ``game_from_dict`` (``playcaller.game``).
Normalization lives in ``playcaller.history.normalize`` — no I/O there.

Does **not** touch Streamlit session state or the recommendation engine.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Union

from playcaller.game import Game, game_from_dict
from playcaller.session_game_metadata import historical_snapshot_session_fields

from .normalize import build_normalized_plays
from .records import GameJsonLoadError, HistoricalGameSnapshot, HistoryCorpus


def _schema_version_from_payload(data: Dict[str, Any]) -> Optional[int]:
    raw = data.get("schema_version")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _game_label_from_payload(data: Dict[str, Any]) -> Optional[str]:
    sm = data.get("session_metadata")
    if isinstance(sm, dict):
        for key in ("game_label", "label"):
            raw = sm.get(key)
            if raw is not None and str(raw).strip():
                return str(raw).strip()
        team = str(sm.get("team_name") or "").strip()
        opp = str(sm.get("opponent") or "").strip()
        dt = str(sm.get("game_date") or "").strip()
        if team and opp:
            return f"{team} vs {opp}" + (f" ({dt})" if dt else "")
        if team and dt:
            return f"{team} ({dt})"
    for key in ("game_label", "label", "session_label"):
        raw = data.get(key)
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    return None


def parse_game_dict(data: Dict[str, Any]) -> Game:
    """Parse a game object dict — same as sidebar / review upload (``game_from_dict``)."""
    return game_from_dict(data)


def load_game_json_path(path: Union[str, Path]) -> Game:
    """Read one JSON file and return a ``Game`` (raises on I/O or invalid JSON)."""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("JSON root must be an object")
    return game_from_dict(data)


def _snapshot_from_game(
    game: Game,
    *,
    source_path: str,
    schema_version: Optional[int],
    game_label: Optional[str],
) -> HistoricalGameSnapshot:
    n_plays = sum(len(d.plays) for d in game.drives)
    n_audit = len(game.recommendation_audit or [])
    sid, sim = historical_snapshot_session_fields(
        game.session_metadata if isinstance(game.session_metadata, dict) else None
    )
    return HistoricalGameSnapshot(
        game_id=str(game.game_id),
        source_path=source_path,
        schema_version=schema_version,
        game_label=game_label,
        offense_points=int(game.offense_points),
        defense_points=int(game.defense_points),
        drive_count=len(game.drives),
        play_count=n_plays,
        audit_row_count=n_audit,
        session_game_id=sid,
        session_is_simulated=sim,
    )


def load_history_directory(
    root: Union[str, Path],
    *,
    pattern: str = "*.json",
    recursive: bool = False,
    max_json_files: Optional[int] = None,
) -> HistoryCorpus:
    """
    Load each matching JSON file under ``root`` into normalized play rows.

    Bad files are recorded in ``corpus.errors``; processing continues.

    ``max_json_files``: if set, only the first N paths (after sorted glob) are read — safety cap.
    """
    base = Path(root).expanduser()
    if not base.is_dir():
        return HistoryCorpus(errors=[GameJsonLoadError(str(base), "Not a directory or does not exist")])

    paths = sorted(base.rglob(pattern) if recursive else base.glob(pattern))
    corpus = HistoryCorpus()
    if max_json_files is not None and max_json_files > 0 and len(paths) > max_json_files:
        corpus.notes.append(
            f"Processing {max_json_files} of {len(paths)} JSON files (max_json_files cap)."
        )
        paths = paths[: int(max_json_files)]
    for path in paths:
        if not path.is_file():
            continue
        rel = str(path)
        try:
            text = path.read_text(encoding="utf-8")
            data = json.loads(text)
        except (OSError, UnicodeDecodeError) as e:
            corpus.errors.append(GameJsonLoadError(rel, f"read error: {e}"))
            continue
        except json.JSONDecodeError as e:
            corpus.errors.append(GameJsonLoadError(rel, f"JSON: {e}"))
            continue

        if not isinstance(data, dict):
            corpus.errors.append(GameJsonLoadError(rel, "JSON root must be an object"))
            continue

        schema_ver = _schema_version_from_payload(data)
        label = _game_label_from_payload(data)
        try:
            game = game_from_dict(data)
        except Exception as e:
            corpus.errors.append(GameJsonLoadError(rel, f"game_from_dict: {e}"))
            continue

        corpus.games.append(
            _snapshot_from_game(game, source_path=rel, schema_version=schema_ver, game_label=label)
        )
        corpus.plays.extend(
            build_normalized_plays(
                game,
                source_path=rel,
                schema_version=schema_ver,
                game_label=label,
            )
        )

    return corpus
