"""
End-to-end ESPN game summary import: raw ingest → parse → normalize → validate → persist.

Single entry point for manual and scripted loads; keeps one transaction per game import.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from sqlalchemy.orm import Session

from football_history_warehouse.domain.enums import ImportJobStatus, LeagueFamily
from football_history_warehouse.domain.identifiers import GameId, ImportJobId, LeagueId, SeasonId, TeamId
from football_history_warehouse.ingest.checksum import sha256_hex
from football_history_warehouse.ingest.exceptions import RawIngestError
from football_history_warehouse.ingest.raw.models import RegisterRawGameFileRequest
from football_history_warehouse.ingest.raw.service import RawIngestService, create_raw_import_job, finalize_import_job
from football_history_warehouse.normalization.bundle import CanonicalGameBundle
from football_history_warehouse.normalization.context import GameNormalizationContext
from football_history_warehouse.normalization.espn import normalize_espn_summary_parse_result
from football_history_warehouse.normalization.exceptions import NormalizationError
from football_history_warehouse.parsers.espn_summary.exceptions import EspnSummaryParserError
from football_history_warehouse.parsers.espn_summary.parse import parse_espn_game_summary_json_bytes
from football_history_warehouse.reporting.pipeline_report import PersistenceAttemptReport, build_import_pipeline_report
from football_history_warehouse.storage.repositories import (
    PersistCanonicalBundleParams,
    PersistedCanonicalBundleIds,
    persist_canonical_game_bundle,
)
from football_history_warehouse.validation import validate_canonical_game_bundle
from football_history_warehouse.pipeline.dedupe import canonical_game_exists, raw_payload_already_registered

OutcomeKind = Literal[
    "persisted",
    "duplicate_raw_skipped",
    "duplicate_game_skipped",
    "validation_failed",
    "parse_failed",
    "parse_fatal",
    "normalize_failed",
    "raw_ingest_failed",
    "persistence_failed",
]


@dataclass(frozen=True, slots=True)
class EspnSummaryImportSpec:
    league_id: str
    season_id: str
    season_year_label: str | None = None
    league_name: str | None = None
    league_short_code: str | None = "LG"
    league_family: LeagueFamily = LeagueFamily.NFL
    team_id_by_external_ref: dict[str, str] = field(default_factory=dict)
    """Keys ``espn:<id>`` → canonical ``TeamId`` string."""
    parser_version: str = "espn_game_summary_json_v1"
    source_system: str = "espn_api"
    game_id_override: str | None = None
    """If set, canonical game id; otherwise ``espn-{source_event_id}`` from the parsed payload."""


@dataclass(frozen=True, slots=True)
class EspnGameImportResult:
    outcome: OutcomeKind
    job_id: str
    game_id: str | None
    artifact_id: int | None
    checksum_sha256: str | None
    message: str
    pipeline_report: dict[str, Any] | None = None
    persisted: PersistedCanonicalBundleIds | None = None


def _merge_game_extensions(bundle: CanonicalGameBundle, **extra: Any) -> CanonicalGameBundle:
    g = bundle.game
    ext = dict(g.source_extensions)
    for k, v in extra.items():
        if v is not None:
            ext[k] = v
    new_game = g.model_copy(update={"source_extensions": ext})
    return CanonicalGameBundle(
        game=new_game,
        drives=bundle.drives,
        plays=bundle.plays,
        notices=bundle.notices,
    )


def import_espn_summary_game_file(
    session: Session,
    *,
    json_path: Path,
    spec: EspnSummaryImportSpec,
    job_id: str | None = None,
    source_label: str = "espn_summary_import",
    skip_if_duplicate_raw_checksum: bool = True,
    skip_if_canonical_game_exists: bool = True,
    observed_at: datetime | None = None,
) -> EspnGameImportResult:
    """
    Run the full pipeline for one ESPN summary JSON file on an open ``Session``.

    The caller owns the transaction (e.g. :func:`~football_history_warehouse.storage.database.session_scope`).
    On success, the session is committed by the caller; on failure, raise or rollback.

    **Idempotency:** duplicate raw uploads (same SHA-256 + ``source_system``) and duplicate
    canonical ``game_id`` can be skipped without inserting competition rows.
    """
    jid = job_id or f"job-{uuid.uuid4().hex[:16]}"
    observed = observed_at or datetime.now(timezone.utc)
    uri = json_path.resolve().as_uri()

    try:
        content = json_path.read_bytes()
    except OSError as exc:
        return EspnGameImportResult(
            outcome="parse_failed",
            job_id=jid,
            game_id=None,
            artifact_id=None,
            checksum_sha256=None,
            message=f"Cannot read file: {exc}",
            pipeline_report=None,
        )

    digest = sha256_hex(content)

    if skip_if_duplicate_raw_checksum:
        dup = raw_payload_already_registered(session, content_checksum_sha256=digest, source_system=spec.source_system)
        if dup is not None:
            rep = {
                "outcome": "duplicate_raw_skipped",
                "existing_artifact_id": dup.id,
                "existing_import_job_id": dup.import_job_id,
                "checksum_sha256": digest,
            }
            return EspnGameImportResult(
                outcome="duplicate_raw_skipped",
                job_id=jid,
                game_id=None,
                artifact_id=int(dup.id),
                checksum_sha256=digest,
                message="Raw payload already registered with same checksum and source_system.",
                pipeline_report={"duplicate_raw": rep},
            )

    try:
        parsed = parse_espn_game_summary_json_bytes(content)
    except EspnSummaryParserError as exc:
        return EspnGameImportResult(
            outcome="parse_fatal",
            job_id=jid,
            game_id=None,
            artifact_id=None,
            checksum_sha256=digest,
            message=str(exc),
            pipeline_report=None,
        )

    event_id = parsed.game.source_event_id
    canonical_game_id = (spec.game_id_override or f"espn-{event_id}").strip()
    if skip_if_canonical_game_exists and canonical_game_exists(session, canonical_game_id):
        return EspnGameImportResult(
            outcome="duplicate_game_skipped",
            job_id=jid,
            game_id=canonical_game_id,
            artifact_id=None,
            checksum_sha256=digest,
            message=f"Game {canonical_game_id!r} already in warehouse; no import job created.",
            pipeline_report={"duplicate_game_id": canonical_game_id},
        )

    try:
        create_raw_import_job(
            session,
            job_id=jid,
            source_label=source_label,
            config_snapshot={
                "path": str(json_path),
                "league_id": spec.league_id,
                "season_id": spec.season_id,
                "canonical_game_id": canonical_game_id,
            },
            trigger="espn_summary_import",
        )
    except RawIngestError as exc:
        if exc.args[0] == "import_job_exists":
            return EspnGameImportResult(
                outcome="raw_ingest_failed",
                job_id=jid,
                game_id=None,
                artifact_id=None,
                checksum_sha256=digest,
                message=str(exc),
                pipeline_report=None,
            )
        raise

    service = RawIngestService()
    reg = service.register_raw_game_file(
        session,
        RegisterRawGameFileRequest(
            import_job_id=jid,
            source_system=spec.source_system,
            parser_version=spec.parser_version,
            content=content,
            league_key=spec.league_id,
            logical_name=json_path.name,
            uri=uri,
            checksum_sha256=digest,
            observed_at=observed,
            extra_metadata={"canonical_game_id": canonical_game_id, "espn_event_id": event_id},
        ),
    )

    team_map: dict[str, TeamId] = {k: TeamId(v) for k, v in spec.team_id_by_external_ref.items()}
    ctx = GameNormalizationContext(
        league_id=LeagueId(spec.league_id),
        season_id=SeasonId(spec.season_id),
        game_id=GameId(canonical_game_id),
        team_id_by_external_ref=team_map,
        source_system=spec.source_system,
        import_job_id=ImportJobId(jid),
        observed_at=observed,
        parser_version=spec.parser_version,
        raw_content_checksum=digest,
        source_uri=uri,
    )

    try:
        bundle = normalize_espn_summary_parse_result(parsed, ctx)
    except NormalizationError as exc:
        service.mark_artifact_failed(session, artifact_id=reg.artifact_id, message=str(exc))
        finalize_import_job(
            session,
            job_id=jid,
            status=ImportJobStatus.FAILED,
            error_summary=str(exc),
            pipeline_report={
                "schema_version": "1",
                "kind": "import_pipeline_stage_failure",
                "stage": "normalize",
                "import_job_id": jid,
                "canonical_game_id": canonical_game_id,
                "error_message": str(exc),
            },
        )
        return EspnGameImportResult(
            outcome="normalize_failed",
            job_id=jid,
            game_id=canonical_game_id,
            artifact_id=reg.artifact_id,
            checksum_sha256=digest,
            message=str(exc),
            pipeline_report=None,
        )

    bundle = _merge_game_extensions(
        bundle,
        **{
            "warehouse.import_job_id": jid,
            "warehouse.raw_checksum_sha256": digest,
            "warehouse.source_uri": uri,
        },
    )

    validation = validate_canonical_game_bundle(bundle)
    report = build_import_pipeline_report(import_job_id=jid, bundle=bundle, validation=validation)

    if not validation.ok_to_persist:
        finalize_import_job(
            session,
            job_id=jid,
            status=ImportJobStatus.FAILED,
            error_summary="validation_failed",
            pipeline_report=report.to_json_dict(),
        )
        return EspnGameImportResult(
            outcome="validation_failed",
            job_id=jid,
            game_id=canonical_game_id,
            artifact_id=reg.artifact_id,
            checksum_sha256=digest,
            message="Validation failed; see pipeline_report.validation.",
            pipeline_report=report.to_json_dict(),
        )

    try:
        persisted = persist_canonical_game_bundle(
            session,
            bundle,
            PersistCanonicalBundleParams(
                import_job_id=jid,
                ensure_import_job=False,
                import_job_source_label=source_label,
                import_job_trigger="espn_summary_import",
                league_family=spec.league_family,
                league_name=spec.league_name,
                league_short_code=spec.league_short_code,
                season_year_label=spec.season_year_label or spec.season_id,
                validation_result=validation,
            ),
        )
    except Exception as exc:
        fail_report = build_import_pipeline_report(
            import_job_id=jid,
            bundle=bundle,
            validation=validation,
            persistence=PersistenceAttemptReport(
                attempted=True,
                succeeded=False,
                error_type=type(exc).__name__,
                error_message=str(exc),
            ),
        )
        finalize_import_job(
            session,
            job_id=jid,
            status=ImportJobStatus.FAILED,
            error_summary=str(exc),
            pipeline_report=fail_report.to_json_dict(),
        )
        return EspnGameImportResult(
            outcome="persistence_failed",
            job_id=jid,
            game_id=canonical_game_id,
            artifact_id=reg.artifact_id,
            checksum_sha256=digest,
            message=str(exc),
            pipeline_report=fail_report.to_json_dict(),
        )

    full_report = build_import_pipeline_report(
        import_job_id=jid,
        bundle=bundle,
        validation=validation,
        persistence=PersistenceAttemptReport(
            attempted=True,
            succeeded=True,
            persisted_game_id=persisted.game_id,
            drive_count=len(persisted.drive_ids),
            play_count=len(persisted.play_ids),
            provenance_rows_written=persisted.provenance_rows_written,
        ),
    )
    finalize_import_job(
        session,
        job_id=jid,
        status=ImportJobStatus.SUCCEEDED,
        pipeline_report=full_report.to_json_dict(),
    )

    return EspnGameImportResult(
        outcome="persisted",
        job_id=jid,
        game_id=persisted.game_id,
        artifact_id=reg.artifact_id,
        checksum_sha256=digest,
        message=full_report.summary,
        pipeline_report=full_report.to_json_dict(),
        persisted=persisted,
    )


def _parse_team_map(raw: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in raw.items():
        key = str(k)
        if not key.startswith("espn:"):
            key = f"espn:{key}"
        out[key] = str(v)
    return out


def load_manifest(manifest_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], Path]:
    """Load a JSON manifest; returns (global_defaults, games list, manifest directory for relative paths)."""
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Manifest root must be a JSON object.")
    games = data.get("games")
    if not isinstance(games, list) or not games:
        raise ValueError("Manifest must contain a non-empty 'games' array.")
    global_defaults = {k: v for k, v in data.items() if k != "games"}
    return global_defaults, games, manifest_path.parent


def spec_from_manifest_entry(
    manifest_dir: Path,
    global_defaults: dict[str, Any],
    entry: dict[str, Any],
) -> tuple[Path, EspnSummaryImportSpec]:
    """Return resolved JSON path and merged :class:`EspnSummaryImportSpec`."""
    path_s = entry.get("path")
    if not path_s or not isinstance(path_s, str):
        raise ValueError("Each game entry requires a string 'path' to the JSON file.")
    path = Path(path_s)
    if not path.is_absolute():
        path = (manifest_dir / path).resolve()
    league_id = entry.get("league_id", global_defaults.get("league_id"))
    season_id = entry.get("season_id", global_defaults.get("season_id"))
    if not league_id or not season_id:
        raise ValueError("league_id and season_id required (globally or per game).")
    tm = entry.get("team_map") or global_defaults.get("team_map")
    if not isinstance(tm, dict):
        raise ValueError("team_map must be an object mapping espn team ids to canonical team ids.")
    team_map = _parse_team_map(tm)
    lf_raw = entry.get("league_family", global_defaults.get("league_family", "nfl"))
    lf = LeagueFamily(str(lf_raw))
    gid_ov = entry.get("game_id_override", global_defaults.get("game_id_override"))
    return path, EspnSummaryImportSpec(
        league_id=str(league_id),
        season_id=str(season_id),
        season_year_label=entry.get("season_year_label", global_defaults.get("season_year_label")),
        league_name=entry.get("league_name", global_defaults.get("league_name")),
        league_short_code=entry.get("league_short_code", global_defaults.get("league_short_code", "LG")),
        league_family=lf,
        team_id_by_external_ref=team_map,
        parser_version=str(entry.get("parser_version", global_defaults.get("parser_version", "espn_game_summary_json_v1"))),
        source_system=str(entry.get("source_system", global_defaults.get("source_system", "espn_api"))),
        game_id_override=str(gid_ov) if gid_ov else None,
    )
