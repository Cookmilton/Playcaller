"""Add first-class raw-ingest metadata on source_artifacts.

Revision ID: 0003_source_artifact_raw_fields
Revises: 0002_initial_schema
Create Date: 2026-04-19

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_source_artifact_raw_fields"
down_revision: Union[str, Sequence[str], None] = "0002_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "source_artifacts",
        sa.Column("league_key", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "source_artifacts",
        sa.Column("parser_version", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "source_artifacts",
        sa.Column(
            "ingest_status",
            sa.String(length=32),
            server_default="registered",
            nullable=False,
        ),
    )
    op.add_column(
        "source_artifacts",
        sa.Column("logical_name", sa.String(length=512), nullable=True),
    )
    op.create_index(
        "ix_source_artifacts_league_key",
        "source_artifacts",
        ["league_key"],
        unique=False,
    )
    op.create_index(
        "ix_source_artifacts_ingest_status",
        "source_artifacts",
        ["ingest_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_source_artifacts_ingest_status", table_name="source_artifacts")
    op.drop_index("ix_source_artifacts_league_key", table_name="source_artifacts")
    op.drop_column("source_artifacts", "logical_name")
    op.drop_column("source_artifacts", "ingest_status")
    op.drop_column("source_artifacts", "parser_version")
    op.drop_column("source_artifacts", "league_key")
