"""F4.2: ``situation_bucket`` nulls are ``"unknown"``; the long rule is unchanged.

``long = dist >= 7`` does not consult down. Downs 1–3 therefore all become
``long_distance_*``. Down 4 still returns ``4th_*`` because that branch runs
before the long return. No down guard by design pending F4.4.
"""

from __future__ import annotations

import pytest

from playcaller.evaluation.audit import situation_bucket
from playcaller.evaluation.metrics import evaluate_audit_records

_OWN_25 = {"down": 1, "distance": 10, "territory": "own", "yardline": 25}


# F4.2 phase 2 flip: absent and present-but-None used to substitute 1 / 10 / own / 25
# or crash in int(None). They now return the string "unknown".


def test_f42_empty_context_is_unknown() -> None:
    """F4.2 phase 2 flip: ``{}`` is ``"unknown"``, not 1st & 10 at own 25."""
    assert situation_bucket({}) == "unknown"
    assert situation_bucket(_OWN_25) == "long_distance_field"


def test_f42_absent_down_is_unknown() -> None:
    """F4.2 phase 2 flip: a missing down is ``"unknown"``."""
    omitted = {"distance": 4, "territory": "own", "yardline": 40}
    assert situation_bucket(omitted) == "unknown"
    explicit = {"down": 1, **omitted}
    assert situation_bucket(explicit) == "standard_field"
    fourth = {"down": 4, **omitted}
    assert situation_bucket(fourth) == "4th_field"


def test_f42_absent_distance_is_unknown() -> None:
    """F4.2 phase 2 flip: a missing distance is ``"unknown"``."""
    omitted = {"down": 3, "territory": "own", "yardline": 40}
    assert situation_bucket(omitted) == "unknown"
    explicit = {"distance": 10, **omitted}
    assert situation_bucket(explicit) == "long_distance_field"
    six = {"distance": 6, **omitted}
    assert situation_bucket(six) == "standard_field"


def test_f42_absent_yardline_is_unknown() -> None:
    """F4.2 phase 2 flip: a missing yardline is ``"unknown"``."""
    omitted = {"down": 1, "distance": 4, "territory": "own"}
    assert situation_bucket(omitted) == "unknown"
    explicit = {"yardline": 25, **omitted}
    assert situation_bucket(explicit) == "standard_field"
    backed_up = {"down": 1, "distance": 4, "territory": "own", "yardline": 15}
    assert situation_bucket(backed_up) == "standard_backed_up"
    opponents_25 = {"down": 1, "distance": 4, "territory": "opponents", "yardline": 25}
    assert situation_bucket(opponents_25) == "standard_frontier"


def test_f42_absent_territory_is_unknown() -> None:
    """Territory selects the field zone, so a missing territory is ``"unknown"``."""
    omitted = {"down": 1, "distance": 4, "yardline": 40}
    assert situation_bucket(omitted) == "unknown"
    explicit = {"territory": "own", **omitted}
    assert situation_bucket(explicit) == "standard_field"


@pytest.mark.parametrize("key", ["down", "distance", "yardline", "territory"])
def test_f42_present_none_is_unknown(key: str) -> None:
    """F4.2 phase 2 flip: a present ``None`` is ``"unknown"``, not ``int(None)``.

    Territory ``None`` did not crash before (``str(None)`` became the zone
    ``"field"``). It is ``"unknown"`` for the same reason as an absent territory.
    """
    ctx: dict[str, object] = {"down": 1, "distance": 10, "territory": "own", "yardline": 25}
    ctx[key] = None
    assert situation_bucket(ctx) == "unknown"


@pytest.mark.parametrize("distance", [7, 10, 15])
@pytest.mark.parametrize(
    ("down", "expected"),
    [
        (1, "long_distance_field"),
        (2, "long_distance_field"),
        (3, "long_distance_field"),
        (4, "4th_field"),
    ],
)
def test_f42_distance_at_least_7_has_no_down_guard_on_the_long_rule(
    down: int, distance: int, expected: str
) -> None:
    """Distance >= 7 is long on downs 1, 2, and 3. Down 4 is ``4th_field``.

    No down guard by design pending F4.4.
    """
    ctx = {"down": down, "distance": distance, "territory": "own", "yardline": 25}
    assert situation_bucket(ctx) == expected


def _closed_record(pre: dict[str, object]) -> dict[str, object]:
    return {
        "status": "closed",
        "pre_snap": pre,
        "selected_family": "power",
        "linked_actual": {"family": "power", "yards_gained": 0},
    }


def test_f42_metrics_present_none_down_still_raises() -> None:
    # KNOWN DEFECT F4.2b - metrics.py:149-150 int(pre.get(...)) - pinned as current behaviour, flip when fixed.
    pre = {"down": None, "distance": 10, "territory": "own", "yardline": 25}
    with pytest.raises(TypeError):
        evaluate_audit_records([_closed_record(pre)])


def test_f42_metrics_present_none_distance_still_raises() -> None:
    # KNOWN DEFECT F4.2b - metrics.py:149-150 int(pre.get(...)) - pinned as current behaviour, flip when fixed.
    pre = {"down": 1, "distance": None, "territory": "own", "yardline": 25}
    with pytest.raises(TypeError):
        evaluate_audit_records([_closed_record(pre)])
