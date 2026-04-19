"""
Shared configuration for canonical Pydantic models.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

# Canonical rows reject unknown fields so typos fail fast at normalization time.
CANONICAL_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True, validate_assignment=False)


class CanonicalModel(BaseModel):
    """Base for warehouse entities: immutable, no silent extra keys."""

    model_config = CANONICAL_MODEL_CONFIG
