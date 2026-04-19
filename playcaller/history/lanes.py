"""
Run vs pass lane labels for historical rows (query aggregates + outcome slices).

Single definition so retrieval dashboards and influence scoring stay aligned.
"""

from __future__ import annotations

from typing import Optional

from playcaller.domain import PASS_FAMILIES, RUN_FAMILIES


def actual_family_to_history_lane(family: Optional[str]) -> str:
    """
    Bucket an **actual** play family into ``run_family`` | ``pass_family`` | ``other`` | ``unknown``.

    ``unknown`` = missing/empty family; ``other`` = specials / unclassified families.
    """
    if not family:
        return "unknown"
    f = str(family)
    if f in RUN_FAMILIES:
        return "run_family"
    if f in PASS_FAMILIES:
        return "pass_family"
    return "other"
