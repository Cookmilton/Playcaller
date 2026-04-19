"""
Ingest uploaded or on-disk game JSON into the persistent history repository.

Writes:
  - raw copy under ``imports/<import_id>/raw/``
  - normalized play rows under ``games/<repo_game_id>/normalized_plays.jsonl``
  - manifest entries (imports + game index)
"""

from __future__ import annotations

import io
import json
import re
import uuid
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from dataclasses import replace

from playcaller.game import game_from_dict
from playcaller.session_game_metadata import historical_snapshot_session_fields

from .loader import _game_label_from_payload, _schema_version_from_payload
from .normalize import build_normalized_plays
from .records import HistoricalGameSnapshot, normalized_historical_play_to_json_dict
from .repository_manifest import read_manifest, write_manifest
from .repository_metadata import extract_sidecar_metadata, merge_metadata_with_overrides
from .repository_paths import ensure_repository_layout


@dataclass
class IngestRejected:
    logical_name: str
    reason: str


@dataclass
class IngestReport:
    import_id: str
    created_at_iso: str
    source_kind: str
    label: str
    files_found: int
    files_imported: int
    files_rejected: int
    rejected: List[IngestRejected] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    game_repo_ids: List[str] = field(default_factory=list)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_storage_name(original: str, used: Set[str]) -> str:
    base = Path(original).name
    base = re.sub(r"[^\w.\-]+", "_", base).strip("._") or "game"
    if len(base) > 160:
        base = base[:160]
    if not base.lower().endswith(".json"):
        base = f"{base}.json"
    if base not in used:
        used.add(base)
        return base
    stem, suf = Path(base).stem, Path(base).suffix or ".json"
    i = 2
    while True:
        cand = f"{stem}_{i}{suf}"
        if cand not in used:
            used.add(cand)
            return cand
        i += 1


def _snapshot_from_game(
    game: Any,
    *,
    source_path: str,
    schema_version: Optional[int],
    game_label: Optional[str],
) -> HistoricalGameSnapshot:
    n_plays = sum(len(d.plays) for d in game.drives)
    n_audit = len(game.recommendation_audit or [])
    sid, sim = historical_snapshot_session_fields(
        game.session_metadata if isinstance(getattr(game, "session_metadata", None), dict) else None
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


def _validation_warnings_for_snapshot(snap: HistoricalGameSnapshot) -> List[str]:
    w: List[str] = []
    if snap.play_count == 0:
        w.append("zero logged plays")
    if snap.audit_row_count == 0:
        w.append(
            "no snap review rows in JSON (`snap_review_log` / legacy `recommendation_audit`); "
            "situation context may be sparse"
        )
    if snap.schema_version is None:
        w.append("schema_version missing in JSON")
    return w


def _game_record_dict(
    *,
    repo_game_id: str,
    import_id: str,
    snap: HistoricalGameSnapshot,
    source_filename: str,
    raw_relpath: str,
    normalized_relpath: str,
    sidecar: Mapping[str, str],
    validation_warnings: Sequence[str],
    tags: Sequence[str],
) -> Dict[str, Any]:
    status = "warnings" if validation_warnings else "ok"
    gl = sidecar.get("game_label") or (snap.game_label or "")
    return {
        "repo_game_id": repo_game_id,
        "import_id": import_id,
        "source_game_id": snap.game_id,
        "source_filename": source_filename,
        "raw_relpath": raw_relpath,
        "normalized_relpath": normalized_relpath,
        "game_label": gl,
        "team": sidecar.get("team", ""),
        "opponent": sidecar.get("opponent", ""),
        "game_date": sidecar.get("game_date", ""),
        "season": sidecar.get("season", ""),
        "roster_id": sidecar.get("roster_id", ""),
        "play_count": snap.play_count,
        "drive_count": snap.drive_count,
        "offense_points": snap.offense_points,
        "defense_points": snap.defense_points,
        "schema_version": snap.schema_version,
        "audit_row_count": snap.audit_row_count,
        "session_game_id": snap.session_game_id or "",
        "session_is_simulated": snap.session_is_simulated,
        "validation_status": status,
        "validation_warnings": list(validation_warnings),
        "tags": list(tags),
        "metadata_overrides": {},
    }


def _ingest_one_parsed_game(
    repo_root: Path,
    *,
    import_id: str,
    data: Dict[str, Any],
    logical_name: str,
    storage_name: str,
    report: IngestReport,
) -> None:
    schema_ver = _schema_version_from_payload(data)
    label = _game_label_from_payload(data)
    sidecar = extract_sidecar_metadata(data)
    if label:
        sidecar = merge_metadata_with_overrides(sidecar, {"game_label": label})

    rel_raw = f"imports/{import_id}/raw/{storage_name}"
    abs_raw = repo_root / rel_raw
    abs_raw.parent.mkdir(parents=True, exist_ok=True)
    abs_raw.write_text(json.dumps(data, indent=2), encoding="utf-8")

    game = game_from_dict(data)
    snap = _snapshot_from_game(
        game,
        source_path=rel_raw,
        schema_version=schema_ver,
        game_label=label,
    )
    vwarn = _validation_warnings_for_snapshot(snap)
    repo_game_id = str(uuid.uuid4())
    rel_norm = f"games/{repo_game_id}/normalized_plays.jsonl"
    abs_norm = repo_root / rel_norm
    abs_norm.parent.mkdir(parents=True, exist_ok=True)

    rows = build_normalized_plays(
        game,
        source_path=f"repo://{repo_game_id}/{storage_name}",
        schema_version=schema_ver,
        game_label=label,
    )
    tagged = [
        replace(r, repository_game_id=repo_game_id, source_path=f"repo://{repo_game_id}/{storage_name}")
        for r in rows
    ]
    with abs_norm.open("w", encoding="utf-8") as f:
        for r in tagged:
            f.write(json.dumps(normalized_historical_play_to_json_dict(r), ensure_ascii=False))
            f.write("\n")

    gdict = _game_record_dict(
        repo_game_id=repo_game_id,
        import_id=import_id,
        snap=snap,
        source_filename=logical_name,
        raw_relpath=rel_raw,
        normalized_relpath=rel_norm,
        sidecar=sidecar,
        validation_warnings=vwarn,
        tags=[],
    )
    manifest = read_manifest(repo_root)
    manifest.setdefault("games", []).append(gdict)
    report.game_repo_ids.append(repo_game_id)
    report.files_imported += 1
    report.warnings.extend([f"{logical_name}: {w}" for w in vwarn])
    write_manifest(repo_root, manifest)


def _try_ingest_one_json_bytes(
    repo_root: Path,
    *,
    import_id: str,
    logical_name: str,
    storage_name: str,
    raw: bytes,
    report: IngestReport,
) -> None:
    try:
        text = raw.decode("utf-8")
        data = json.loads(text)
    except UnicodeDecodeError as e:
        report.files_rejected += 1
        report.rejected.append(IngestRejected(logical_name, f"decode: {e}"))
        return
    except json.JSONDecodeError as e:
        report.files_rejected += 1
        report.rejected.append(IngestRejected(logical_name, f"JSON: {e}"))
        return
    if not isinstance(data, dict):
        report.files_rejected += 1
        report.rejected.append(IngestRejected(logical_name, "JSON root must be an object"))
        return
    try:
        _ingest_one_parsed_game(
            repo_root,
            import_id=import_id,
            data=data,
            logical_name=logical_name,
            storage_name=storage_name,
            report=report,
        )
    except Exception as e:
        report.files_rejected += 1
        report.rejected.append(IngestRejected(logical_name, f"ingest: {e}"))


def ingest_file_bytes(
    repo_root: Path,
    pairs: Sequence[Tuple[str, bytes]],
    *,
    source_kind: str,
    label: str = "",
) -> IngestReport:
    """
    Ingest a sequence of (logical_name, utf-8 json bytes).

    Updates manifest with one import record and N game records.
    """
    ensure_repository_layout(repo_root)
    import_id = str(uuid.uuid4())
    report = IngestReport(
        import_id=import_id,
        created_at_iso=_utc_now_iso(),
        source_kind=source_kind,
        label=(label or "").strip(),
        files_found=len(pairs),
        files_imported=0,
        files_rejected=0,
    )
    used_names: Set[str] = set()
    for logical_name, body in pairs:
        storage = _safe_storage_name(logical_name, used_names)
        _try_ingest_one_json_bytes(
            repo_root,
            import_id=import_id,
            logical_name=logical_name,
            storage_name=storage,
            raw=body,
            report=report,
        )

    imp_entry = {
        "import_id": import_id,
        "created_at_iso": report.created_at_iso,
        "source_kind": source_kind,
        "label": report.label,
        "files_found": report.files_found,
        "files_imported": report.files_imported,
        "files_rejected": report.files_rejected,
        "rejected": [asdict(x) for x in report.rejected],
        "warnings": list(report.warnings),
        "game_repo_ids": list(report.game_repo_ids),
    }
    manifest = read_manifest(repo_root)
    manifest.setdefault("imports", []).append(imp_entry)
    write_manifest(repo_root, manifest)
    return report


def iter_json_from_zip(data: bytes) -> List[Tuple[str, bytes]]:
    out: List[Tuple[str, bytes]] = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename
            if not name.lower().endswith(".json"):
                continue
            # Skip huge / path traversal names
            parts = Path(name).parts
            if ".." in parts:
                continue
            logical = Path(name).as_posix().replace("/", "__")
            if not logical.lower().endswith(".json"):
                logical = f"{logical}.json"
            out.append((logical, zf.read(info)))
    return out


def ingest_zip_bytes(
    repo_root: Path,
    data: bytes,
    *,
    source_kind: str = "zip",
    label: str = "",
) -> IngestReport:
    pairs = iter_json_from_zip(data)
    if not pairs:
        ensure_repository_layout(repo_root)
        import_id = str(uuid.uuid4())
        report = IngestReport(
            import_id=import_id,
            created_at_iso=_utc_now_iso(),
            source_kind=source_kind,
            label=(label or "").strip(),
            files_found=0,
            files_imported=0,
            files_rejected=0,
        )
        report.warnings.append("ZIP contained no .json entries")
        imp_entry = {
            "import_id": import_id,
            "created_at_iso": report.created_at_iso,
            "source_kind": source_kind,
            "label": report.label,
            "files_found": 0,
            "files_imported": 0,
            "files_rejected": 0,
            "rejected": [],
            "warnings": list(report.warnings),
            "game_repo_ids": [],
        }
        manifest = read_manifest(repo_root)
        manifest.setdefault("imports", []).append(imp_entry)
        write_manifest(repo_root, manifest)
        return report
    return ingest_file_bytes(repo_root, pairs, source_kind=source_kind, label=label)


def ingest_directory(
    repo_root: Path,
    directory: Path | str,
    *,
    recursive: bool = False,
    max_json_files: Optional[int] = None,
    label: str = "",
) -> IngestReport:
    """Read ``*.json`` from a folder (operator machine path)."""
    base = Path(directory).expanduser()
    if not base.is_dir():
        ensure_repository_layout(repo_root)
        import_id = str(uuid.uuid4())
        report = IngestReport(
            import_id=import_id,
            created_at_iso=_utc_now_iso(),
            source_kind="folder",
            label=(label or "").strip(),
            files_found=0,
            files_imported=0,
            files_rejected=1,
        )
        report.rejected.append(IngestRejected(str(base), "not a directory"))
        imp_entry = {
            "import_id": import_id,
            "created_at_iso": report.created_at_iso,
            "source_kind": "folder",
            "label": report.label,
            "files_found": 0,
            "files_imported": 0,
            "files_rejected": 1,
            "rejected": [asdict(x) for x in report.rejected],
            "warnings": [],
            "game_repo_ids": [],
        }
        manifest = read_manifest(repo_root)
        manifest.setdefault("imports", []).append(imp_entry)
        write_manifest(repo_root, manifest)
        return report

    paths = sorted(base.rglob("*.json") if recursive else base.glob("*.json"))
    if max_json_files is not None and max_json_files > 0 and len(paths) > max_json_files:
        paths = paths[: int(max_json_files)]
    pairs: List[Tuple[str, bytes]] = []
    for p in paths:
        if not p.is_file():
            continue
        try:
            pairs.append((p.name, p.read_bytes()))
        except OSError:
            continue
    return ingest_file_bytes(repo_root, pairs, source_kind="folder", label=label)
