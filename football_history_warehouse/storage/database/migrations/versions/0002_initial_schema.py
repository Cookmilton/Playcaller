"""Initial domain tables for canonical football history.

Revision ID: 0002_initial_schema
Revises: 0001_baseline
Create Date: 2026-04-18

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_initial_schema"
down_revision: Union[str, Sequence[str], None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _json_col():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "import_jobs",
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_label", sa.String(length=256), nullable=False),
        sa.Column("trigger", sa.String(length=64), nullable=True),
        sa.Column("records_attempted", sa.Integer(), nullable=True),
        sa.Column("records_succeeded", sa.Integer(), nullable=True),
        sa.Column("records_failed", sa.Integer(), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column(
            "config_snapshot",
            _json_col(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_table(
        "leagues",
        sa.Column("league_id", sa.String(length=64), nullable=False),
        sa.Column("family", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("short_code", sa.String(length=32), nullable=True),
        sa.Column("competition_tier_default", sa.String(length=32), nullable=False),
        sa.Column("rules_profile_key", sa.String(length=64), nullable=True),
        sa.Column(
            "row_updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("league_id"),
    )
    op.create_index(op.f("ix_leagues_family"), "leagues", ["family"], unique=False)
    op.create_index(op.f("ix_leagues_short_code"), "leagues", ["short_code"], unique=False)
    op.create_table(
        "seasons",
        sa.Column("season_id", sa.String(length=64), nullable=False),
        sa.Column("league_id", sa.String(length=64), nullable=False),
        sa.Column("year_label", sa.String(length=32), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=True),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column(
            "row_updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["league_id"], ["leagues.league_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("season_id"),
        sa.UniqueConstraint("league_id", "year_label", name="uq_seasons_league_year_label"),
    )
    op.create_index(op.f("ix_seasons_league_id"), "seasons", ["league_id"], unique=False)
    op.create_table(
        "teams",
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("league_id", sa.String(length=64), nullable=False),
        sa.Column("full_name", sa.String(length=256), nullable=False),
        sa.Column("abbreviation", sa.String(length=16), nullable=True),
        sa.Column("nickname", sa.String(length=128), nullable=True),
        sa.Column("city", sa.String(length=128), nullable=True),
        sa.Column("conference_id", sa.String(length=64), nullable=True),
        sa.Column("division_id", sa.String(length=64), nullable=True),
        sa.Column(
            "row_updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["league_id"], ["leagues.league_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("team_id"),
    )
    op.create_index("ix_teams_league_abbreviation", "teams", ["league_id", "abbreviation"], unique=False)
    op.create_index(op.f("ix_teams_league_id"), "teams", ["league_id"], unique=False)
    op.create_table(
        "games",
        sa.Column("game_id", sa.String(length=64), nullable=False),
        sa.Column("season_id", sa.String(length=64), nullable=False),
        sa.Column("league_id", sa.String(length=64), nullable=False),
        sa.Column("home_team_id", sa.String(length=64), nullable=False),
        sa.Column("away_team_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("scheduled_start_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("home_score_final", sa.Integer(), nullable=True),
        sa.Column("away_score_final", sa.Integer(), nullable=True),
        sa.Column(
            "regulation_period_count",
            sa.Integer(),
            server_default="4",
            nullable=False,
        ),
        sa.Column("overtime_periods_played", sa.Integer(), nullable=True),
        sa.Column("venue_id", sa.String(length=64), nullable=True),
        sa.Column("attendance", sa.Integer(), nullable=True),
        sa.Column("neutral_site", sa.Boolean(), nullable=True),
        sa.Column(
            "source_extensions",
            _json_col(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "row_updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["away_team_id"], ["teams.team_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["home_team_id"], ["teams.team_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["league_id"], ["leagues.league_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["season_id"], ["seasons.season_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("game_id"),
    )
    op.create_index(op.f("ix_games_away_team_id"), "games", ["away_team_id"], unique=False)
    op.create_index(op.f("ix_games_home_team_id"), "games", ["home_team_id"], unique=False)
    op.create_index(op.f("ix_games_league_id"), "games", ["league_id"], unique=False)
    op.create_index("ix_games_league_season", "games", ["league_id", "season_id"], unique=False)
    op.create_index(op.f("ix_games_scheduled_start_utc"), "games", ["scheduled_start_utc"], unique=False)
    op.create_index(op.f("ix_games_season_id"), "games", ["season_id"], unique=False)
    op.create_index(op.f("ix_games_status"), "games", ["status"], unique=False)
    op.create_table(
        "drives",
        sa.Column("drive_id", sa.String(length=64), nullable=False),
        sa.Column("game_id", sa.String(length=64), nullable=False),
        sa.Column("offense_team_id", sa.String(length=64), nullable=False),
        sa.Column("defense_team_id", sa.String(length=64), nullable=False),
        sa.Column("drive_order", sa.Integer(), nullable=False),
        sa.Column("start_period", sa.Integer(), nullable=True),
        sa.Column("end_period", sa.Integer(), nullable=True),
        sa.Column("result_bucket", sa.String(length=32), nullable=True),
        sa.Column("net_yards", sa.Integer(), nullable=True),
        sa.Column("play_count_official", sa.Integer(), nullable=True),
        sa.Column("time_of_possession_seconds", sa.Integer(), nullable=True),
        sa.Column("start_score_offense", sa.Integer(), nullable=True),
        sa.Column("start_score_defense", sa.Integer(), nullable=True),
        sa.Column(
            "source_extensions",
            _json_col(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "row_updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["defense_team_id"], ["teams.team_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["game_id"], ["games.game_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["offense_team_id"], ["teams.team_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("drive_id"),
        sa.UniqueConstraint("game_id", "drive_order", name="uq_drives_game_order"),
    )
    op.create_index(op.f("ix_drives_defense_team_id"), "drives", ["defense_team_id"], unique=False)
    op.create_index(op.f("ix_drives_game_id"), "drives", ["game_id"], unique=False)
    op.create_index(op.f("ix_drives_offense_team_id"), "drives", ["offense_team_id"], unique=False)
    op.create_table(
        "plays",
        sa.Column("play_id", sa.String(length=64), nullable=False),
        sa.Column("game_id", sa.String(length=64), nullable=False),
        sa.Column("season_id", sa.String(length=64), nullable=False),
        sa.Column("league_id", sa.String(length=64), nullable=False),
        sa.Column("drive_id", sa.String(length=64), nullable=True),
        sa.Column("sequence_in_game", sa.Integer(), nullable=False),
        sa.Column("sequence_in_drive", sa.Integer(), nullable=True),
        sa.Column("period", sa.Integer(), nullable=True),
        sa.Column("clock_seconds_remaining_in_period", sa.Integer(), nullable=True),
        sa.Column("down", sa.Integer(), nullable=True),
        sa.Column("distance", sa.Integer(), nullable=True),
        sa.Column("yards_to_goal_line", sa.Integer(), nullable=True),
        sa.Column("field_side", sa.String(length=16), nullable=True),
        sa.Column("offense_team_id", sa.String(length=64), nullable=False),
        sa.Column("defense_team_id", sa.String(length=64), nullable=False),
        sa.Column("offense_points_before_snap", sa.Integer(), nullable=True),
        sa.Column("defense_points_before_snap", sa.Integer(), nullable=True),
        sa.Column("score_differential_offense_perspective", sa.Integer(), nullable=True),
        sa.Column("play_family", sa.String(length=32), nullable=False),
        sa.Column("play_type_detail", sa.String(length=128), nullable=True),
        sa.Column("passer_player_id", sa.String(length=64), nullable=True),
        sa.Column("qb_player_id", sa.String(length=64), nullable=True),
        sa.Column("rusher_player_id", sa.String(length=64), nullable=True),
        sa.Column("target_player_id", sa.String(length=64), nullable=True),
        sa.Column("primary_ballcarrier_player_id", sa.String(length=64), nullable=True),
        sa.Column("result_category", sa.String(length=32), nullable=False),
        sa.Column("is_first_down_gained", sa.Boolean(), nullable=True),
        sa.Column("is_touchdown", sa.Boolean(), nullable=True),
        sa.Column("is_turnover", sa.Boolean(), nullable=True),
        sa.Column("is_safety", sa.Boolean(), nullable=True),
        sa.Column("is_score_on_play", sa.Boolean(), nullable=True),
        sa.Column("chain_advanced", sa.Boolean(), nullable=True),
        sa.Column("touchback", sa.Boolean(), nullable=True),
        sa.Column("fair_catch", sa.Boolean(), nullable=True),
        sa.Column("down_after_play", sa.Integer(), nullable=True),
        sa.Column("distance_after_play", sa.Integer(), nullable=True),
        sa.Column("outcome_notes", sa.Text(), nullable=True),
        sa.Column("flag_penalty", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("penalty_accepted", sa.Boolean(), nullable=True),
        sa.Column("penalty_yards", sa.Integer(), nullable=True),
        sa.Column("counts_toward_offense_stats", sa.Boolean(), nullable=True),
        sa.Column("is_sack", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_scramble", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_no_play_from_penalty", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_spike", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_kneel", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("yards_gained", sa.Integer(), nullable=True),
        sa.Column("description_text", sa.Text(), nullable=True),
        sa.Column(
            "source_extensions",
            _json_col(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "row_updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "clock_seconds_remaining_in_period IS NULL OR clock_seconds_remaining_in_period <= 3600",
            name="ck_plays_clock_sane",
        ),
        sa.CheckConstraint("down IS NULL OR (down >= 1 AND down <= 4)", name="ck_plays_down"),
        sa.CheckConstraint(
            "yards_to_goal_line IS NULL OR (yards_to_goal_line >= 1 AND yards_to_goal_line <= 99)",
            name="ck_plays_ytg",
        ),
        sa.ForeignKeyConstraint(["defense_team_id"], ["teams.team_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["drive_id"], ["drives.drive_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["game_id"], ["games.game_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["league_id"], ["leagues.league_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["offense_team_id"], ["teams.team_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["season_id"], ["seasons.season_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("play_id"),
        sa.UniqueConstraint("game_id", "sequence_in_game", name="uq_plays_game_sequence"),
    )
    op.create_index("ix_plays_defense_team", "plays", ["defense_team_id"], unique=False)
    op.create_index("ix_plays_down_distance", "plays", ["down", "distance"], unique=False)
    op.create_index(op.f("ix_plays_drive_id"), "plays", ["drive_id"], unique=False)
    op.create_index(op.f("ix_plays_game_id"), "plays", ["game_id"], unique=False)
    op.create_index("ix_plays_league_season", "plays", ["league_id", "season_id"], unique=False)
    op.create_index("ix_plays_offense_team", "plays", ["offense_team_id"], unique=False)
    op.create_index(op.f("ix_plays_period"), "plays", ["period"], unique=False)
    op.create_index(
        "ix_plays_period_clock",
        "plays",
        ["period", "clock_seconds_remaining_in_period"],
        unique=False,
    )
    op.create_index("ix_plays_play_family", "plays", ["play_family"], unique=False)
    op.create_index("ix_plays_result_category", "plays", ["result_category"], unique=False)
    op.create_index("ix_plays_season_id", "plays", ["season_id"], unique=False)
    op.create_index("ix_plays_yards_to_goal", "plays", ["yards_to_goal_line"], unique=False)
    op.create_table(
        "source_artifacts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("import_job_id", sa.String(length=64), nullable=False),
        sa.Column("artifact_kind", sa.String(length=32), nullable=False),
        sa.Column("source_system", sa.String(length=128), nullable=False),
        sa.Column("uri", sa.Text(), nullable=True),
        sa.Column("content_checksum", sa.String(length=128), nullable=True),
        sa.Column("byte_length", sa.BigInteger(), nullable=True),
        sa.Column("media_type", sa.String(length=128), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "extra_metadata",
            _json_col(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.ForeignKeyConstraint(["import_job_id"], ["import_jobs.job_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_source_artifacts_import_job_id"), "source_artifacts", ["import_job_id"], unique=False)
    op.create_table(
        "provenance_records",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("import_job_id", sa.String(length=64), nullable=False),
        sa.Column("source_system", sa.String(length=128), nullable=False),
        sa.Column("source_record_id", sa.String(length=256), nullable=True),
        sa.Column("source_subresource", sa.String(length=256), nullable=True),
        sa.Column("ingest_uri", sa.Text(), nullable=True),
        sa.Column("content_checksum", sa.String(length=128), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_payload_version", sa.String(length=64), nullable=True),
        sa.Column("warehouse_written_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_by_job_id", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["import_job_id"], ["import_jobs.job_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["superseded_by_job_id"], ["import_jobs.job_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_provenance_entity", "provenance_records", ["entity_type", "entity_id"], unique=False)
    op.create_index("ix_provenance_import_job", "provenance_records", ["import_job_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_provenance_import_job", table_name="provenance_records")
    op.drop_index("ix_provenance_entity", table_name="provenance_records")
    op.drop_table("provenance_records")
    op.drop_index(op.f("ix_source_artifacts_import_job_id"), table_name="source_artifacts")
    op.drop_table("source_artifacts")
    op.drop_index("ix_plays_yards_to_goal", table_name="plays")
    op.drop_index("ix_plays_season_id", table_name="plays")
    op.drop_index("ix_plays_result_category", table_name="plays")
    op.drop_index("ix_plays_play_family", table_name="plays")
    op.drop_index("ix_plays_period_clock", table_name="plays")
    op.drop_index(op.f("ix_plays_period"), table_name="plays")
    op.drop_index("ix_plays_offense_team", table_name="plays")
    op.drop_index("ix_plays_league_season", table_name="plays")
    op.drop_index(op.f("ix_plays_game_id"), table_name="plays")
    op.drop_index(op.f("ix_plays_drive_id"), table_name="plays")
    op.drop_index("ix_plays_down_distance", table_name="plays")
    op.drop_index("ix_plays_defense_team", table_name="plays")
    op.drop_table("plays")
    op.drop_index(op.f("ix_drives_offense_team_id"), table_name="drives")
    op.drop_index(op.f("ix_drives_game_id"), table_name="drives")
    op.drop_index(op.f("ix_drives_defense_team_id"), table_name="drives")
    op.drop_table("drives")
    op.drop_index(op.f("ix_games_status"), table_name="games")
    op.drop_index(op.f("ix_games_season_id"), table_name="games")
    op.drop_index(op.f("ix_games_scheduled_start_utc"), table_name="games")
    op.drop_index("ix_games_league_season", table_name="games")
    op.drop_index(op.f("ix_games_league_id"), table_name="games")
    op.drop_index(op.f("ix_games_home_team_id"), table_name="games")
    op.drop_index(op.f("ix_games_away_team_id"), table_name="games")
    op.drop_table("games")
    op.drop_index(op.f("ix_teams_league_id"), table_name="teams")
    op.drop_index("ix_teams_league_abbreviation", table_name="teams")
    op.drop_table("teams")
    op.drop_index(op.f("ix_seasons_league_id"), table_name="seasons")
    op.drop_table("seasons")
    op.drop_index(op.f("ix_leagues_short_code"), table_name="leagues")
    op.drop_index(op.f("ix_leagues_family"), table_name="leagues")
    op.drop_table("leagues")
    op.drop_table("import_jobs")
