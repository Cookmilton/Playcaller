"""Atomic read/write of the repository manifest (imports + game index)."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, MutableMapping

MANIFEST_VERSION = 1
MANIFEST_NAME = "manifest.json"


def default_manifest() -> Dict[str, Any]:
    return {"version": MANIFEST_VERSION, "imports": [], "games": []}


def read_manifest(repo_root: Path) -> Dict[str, Any]:
    path = repo_root / MANIFEST_NAME
    if not path.is_file():
        return default_manifest()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_manifest()
    if not isinstance(data, dict):
        return default_manifest()
    data.setdefault("version", MANIFEST_VERSION)
    data.setdefault("imports", [])
    data.setdefault("games", [])
    if not isinstance(data["imports"], list):
        data["imports"] = []
    if not isinstance(data["games"], list):
        data["games"] = []
    return data


def write_manifest(repo_root: Path, manifest: MutableMapping[str, Any]) -> None:
    repo_root.mkdir(parents=True, exist_ok=True)
    path = repo_root / MANIFEST_NAME
    manifest["version"] = MANIFEST_VERSION
    payload = json.dumps(manifest, indent=2, sort_keys=True)
    fd, tmp = tempfile.mkstemp(prefix=".manifest_", suffix=".json", dir=str(repo_root))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def list_game_records(repo_root: Path) -> List[Dict[str, Any]]:
    m = read_manifest(repo_root)
    games = m.get("games")
    if not isinstance(games, list):
        return []
    return [g for g in games if isinstance(g, dict)]


def update_game_record_fields(
    repo_root: Path, repo_game_id: str, fields: Dict[str, Any]
) -> bool:
    """Merge string/list fields into a game entry. Returns False if id not found."""
    m = read_manifest(repo_root)
    games = m.get("games")
    if not isinstance(games, list):
        return False
    found = False
    for i, g in enumerate(games):
        if isinstance(g, dict) and str(g.get("repo_game_id")) == str(repo_game_id):
            entry = dict(g)
            for k, v in fields.items():
                entry[k] = v
            games[i] = entry
            found = True
            break
    if not found:
        return False
    m["games"] = games
    write_manifest(repo_root, m)
    return True
