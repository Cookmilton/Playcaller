"""Load normalized historical plays from the on-disk repository into memory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .records import HistoryCorpus, NormalizedHistoricalPlay, normalized_historical_play_from_json_dict
from .repository_manifest import list_game_records


def _load_jsonl(path: Path) -> List[NormalizedHistoricalPlay]:
    rows: List[NormalizedHistoricalPlay] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            try:
                rows.append(normalized_historical_play_from_json_dict(obj))
            except (TypeError, ValueError, KeyError):
                continue
    return rows


def load_repository_plays(
    repo_root: Path,
    *,
    repo_game_ids: Optional[Sequence[str]] = None,
    use_all_games: bool = True,
) -> List[NormalizedHistoricalPlay]:
    """
    Concatenate normalized rows for selected games (or entire index).

    Missing files are skipped silently — callers may compare counts vs index.
    """
    games = list_game_records(repo_root)
    want: Optional[set[str]] = None
    if not use_all_games and repo_game_ids is not None:
        want = {str(x) for x in repo_game_ids if str(x).strip()}
    out: List[NormalizedHistoricalPlay] = []
    for g in games:
        rid = str(g.get("repo_game_id") or "")
        if not rid:
            continue
        if want is not None and rid not in want:
            continue
        rel = g.get("normalized_relpath")
        if not rel or not isinstance(rel, str):
            continue
        path = repo_root / rel
        if not path.is_file():
            continue
        out.extend(_load_jsonl(path))
    return out


def history_corpus_from_repository(
    repo_root: Path,
    *,
    repo_game_ids: Optional[Sequence[str]] = None,
    use_all_games: bool = True,
) -> HistoryCorpus:
    """Build a ``HistoryCorpus``-compatible object for validation + influence."""
    plays = load_repository_plays(
        repo_root,
        repo_game_ids=repo_game_ids,
        use_all_games=use_all_games,
    )
    notes: List[str] = []
    if plays:
        notes.append(
            f"Repository corpus: {len(plays)} normalized plays "
            f"({'all indexed games' if use_all_games else 'selected games'})."
        )
    return HistoryCorpus(plays=plays, games=[], errors=[], notes=notes)


def game_record_by_id(repo_root: Path, repo_game_id: str) -> Optional[Dict[str, Any]]:
    for g in list_game_records(repo_root):
        if str(g.get("repo_game_id")) == str(repo_game_id):
            return g
    return None
