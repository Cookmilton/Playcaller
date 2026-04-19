"""Store structured pipeline report JSON on import_jobs.

Revision ID: 0004_import_job_pipeline_report
Revises: 0003_source_artifact_raw_fields
Create Date: 2026-04-19

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_import_job_pipeline_report"
down_revision: Union[str, Sequence[str], None] = "0003_source_artifact_raw_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _json_col():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.add_column(
        "import_jobs",
        sa.Column("pipeline_report", _json_col(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("import_jobs", "pipeline_report")
