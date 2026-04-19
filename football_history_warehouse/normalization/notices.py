"""Non-fatal normalization notes (partial mapping, skipped rows)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NormalizationNotice:
    code: str
    detail: str
    where: str | None = None
