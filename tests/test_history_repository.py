"""Persistent history repository: ingest, manifest, and normalized row round-trip."""

from __future__ import annotations

import json
import zipfile
from io import BytesIO

from playcaller.domain import ActualPlayResult
from playcaller.game import Game, complete_drive_from_plays, game_to_dict
from playcaller.history.ingest import ingest_file_bytes, ingest_zip_bytes
from playcaller.history.records import (
    NormalizedHistoricalPlay,
    normalized_historical_play_from_json_dict,
    normalized_historical_play_to_json_dict,
)
from playcaller.history.repository_corpus import load_repository_plays
from playcaller.history.repository_manifest import list_game_records, read_manifest, update_game_record_fields
from playcaller.history.repository_metadata import extract_sidecar_metadata, merge_metadata_with_overrides


def _minimal_game_dict(*, game_id: str = "g1", label: str = "Test") -> dict:
    g = Game.new_game()
    g.game_id = game_id
    d = complete_drive_from_plays(
        [ActualPlayResult(yards_gained=4, family="inside_zone", play_type="run")],
        possessing_team="offense",
    )
    g.drives = [d]
    payload = game_to_dict(g)
    payload["game_label"] = label
    payload["team"] = "Owls"
    payload["opponent"] = "Sharks"
    payload["game_date"] = "2025-09-07"
    payload["season"] = "2025"
    return payload


def test_extract_sidecar_and_merge() -> None:
    d = _minimal_game_dict()
    m = extract_sidecar_metadata(d)
    assert m["team"] == "Owls"
    merged = merge_metadata_with_overrides(m, {"roster_id": "A1"})
    assert merged["roster_id"] == "A1"


def test_extract_sidecar_reads_session_metadata() -> None:
    g = Game.new_game()
    assert g.session_metadata is not None
    g.session_metadata["team_name"] = "FromSession"
    g.session_metadata["opponent"] = "Other"
    g.session_metadata["game_date"] = "2026-10-01"
    g.session_metadata["season"] = "2026"
    g.session_metadata["roster_version"] = "rv1"
    d = game_to_dict(g)
    m = extract_sidecar_metadata(d)
    assert m["team"] == "FromSession"
    assert m["opponent"] == "Other"
    assert m["game_date"] == "2026-10-01"
    assert m["season"] == "2026"
    assert m["roster_id"] == "rv1"


def test_ingest_and_load_roundtrip(tmp_path) -> None:
    repo = tmp_path / "repo"
    raw = json.dumps(_minimal_game_dict()).encode("utf-8")
    rep = ingest_file_bytes(repo, [("game_a.json", raw)], source_kind="upload", label="batch1")
    assert rep.files_imported == 1
    assert rep.files_rejected == 0
    games = list_game_records(repo)
    assert len(games) == 1
    rid = str(games[0]["repo_game_id"])
    plays = load_repository_plays(repo, repo_game_ids=[rid], use_all_games=False)
    assert len(plays) == 1
    assert plays[0].repository_game_id == rid
    assert plays[0].actual.family == "inside_zone"


def test_normalized_play_json_roundtrip() -> None:
    g = Game.new_game()
    g.drives = [
        complete_drive_from_plays(
            [ActualPlayResult(yards_gained=3, family="quick_game", play_type="pass")],
            possessing_team="offense",
        )
    ]
    from playcaller.history.normalize import build_normalized_plays

    row = build_normalized_plays(g, source_path="x.json", schema_version=1, game_label="L")[0]
    row2 = replace_row_repo(row, "rid9")
    d = normalized_historical_play_to_json_dict(row2)
    s = json.dumps(d)
    back = normalized_historical_play_from_json_dict(json.loads(s))
    assert back.game_id == row.game_id
    assert back.repository_game_id == "rid9"
    assert back.actual.family == "quick_game"


def replace_row_repo(row: NormalizedHistoricalPlay, rid: str) -> NormalizedHistoricalPlay:
    from dataclasses import replace

    return replace(row, repository_game_id=rid)


def test_zip_ingest(tmp_path) -> None:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a/game.json", json.dumps(_minimal_game_dict(game_id="z1")))
    rep = ingest_zip_bytes(tmp_path / "r", buf.getvalue())
    assert rep.files_found == 1
    assert rep.files_imported == 1
    assert len(list_game_records(tmp_path / "r")) == 1


def test_update_game_metadata(tmp_path) -> None:
    repo = tmp_path / "repo2"
    ingest_file_bytes(repo, [("one.json", json.dumps(_minimal_game_dict()).encode())], source_kind="upload")
    rid = list_game_records(repo)[0]["repo_game_id"]
    assert update_game_record_fields(repo, str(rid), {"team": "Fixed", "tags": ["a", "b"]})
    g2 = list_game_records(repo)[0]
    assert g2["team"] == "Fixed"
    assert g2["tags"] == ["a", "b"]
