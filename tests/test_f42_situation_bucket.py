"""F4.2 phase 1: pin ``situation_bucket`` as it behaves at bb6307c.

No production change. A key that is present but ``None`` crashes; those cases
are pinned with ``pytest.raises``. An absent key is filled by
``dict.get`` — down 1, distance 10, territory ``own``, yardline 25 — and that
substitution is pinned by equality with an explicit context.

``long = dist >= 7`` (``audit.py``) does not consult down. Downs 1–3 therefore
all become ``long_distance_*``. Down 4 still returns ``4th_*`` because that
branch runs before the long return; the long predicate itself is still true.
"""

from __future__ import annotations

import pytest

from playcaller.evaluation.audit import situation_bucket

_OWN_25 = {"down": 1, "distance": 10, "territory": "own", "yardline": 25}


def test_f42_empty_context_substitutes_first_ten_own_25() -> None:
    """CURRENT: ``{}`` is tagged as 1st & 10 at own 25 (``long_distance_field``).

    1st, 2nd, and 3rd produce the same tag for a given distance and field
    position, so an absent down is pinned by equality with explicit down 1,
    which is the ``.get("down", 1)`` default. The tag is not a 4th-down tag.
    Own 25 is ``field``; opponents' 25 would be ``frontier``, and own 15 would
    be ``backed_up``, so the zone also pins territory ``own`` and yardline 25
    together. Every distance >= 7 shares this tag, so distance 10 is pinned
    by equality with the explicit context below.
    """
    assert situation_bucket({}) == situation_bucket(_OWN_25) == "long_distance_field"


def test_f42_absent_down_matches_explicit_first_down() -> None:
    """CURRENT: a missing down is 1, not a crash and not 4th down."""
    omitted = {"distance": 4, "territory": "own", "yardline": 40}
    explicit = {"down": 1, **omitted}
    assert situation_bucket(omitted) == situation_bucket(explicit) == "standard_field"
    fourth = {"down": 4, **omitted}
    assert situation_bucket(fourth) == "4th_field"


def test_f42_absent_distance_matches_explicit_ten() -> None:
    """CURRENT: a missing distance is 10, which is long (``dist >= 7``)."""
    omitted = {"down": 3, "territory": "own", "yardline": 40}
    explicit = {"distance": 10, **omitted}
    assert situation_bucket(omitted) == situation_bucket(explicit) == "long_distance_field"
    six = {"distance": 6, **omitted}
    assert situation_bucket(six) == "standard_field"


def test_f42_absent_yardline_matches_explicit_own_25() -> None:
    """CURRENT: a missing yardline is 25. With territory left absent, that is own 25."""
    omitted = {"down": 1, "distance": 4}
    explicit = {"territory": "own", "yardline": 25, **omitted}
    assert situation_bucket(omitted) == situation_bucket(explicit) == "standard_field"
    backed_up = {"down": 1, "distance": 4, "territory": "own", "yardline": 15}
    assert situation_bucket(backed_up) == "standard_backed_up"
    opponents_25 = {"down": 1, "distance": 4, "territory": "opponents", "yardline": 25}
    assert situation_bucket(opponents_25) == "standard_frontier"


@pytest.mark.parametrize("key", ["down", "distance", "yardline"])
def test_f42_present_none_crashes(key: str) -> None:
    """CURRENT behaviour is a crash: ``int(None)`` when the key is present but None.

    ``dict.get`` returns the stored ``None`` instead of the default, and
    ``situation_bucket`` passes that straight to ``int``.
    """
    ctx: dict[str, object] = {"down": 1, "distance": 10, "territory": "own", "yardline": 25}
    ctx[key] = None
    with pytest.raises(TypeError, match="NoneType"):
        situation_bucket(ctx)


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
    """CURRENT: distance >= 7 is long on downs 1, 2, and 3.

    Down 4 is ``4th_field`` because ``if down == 4`` returns before the long
    return. ``long = dist >= 7`` itself still has no down guard.
    """
    ctx = {"down": down, "distance": distance, "territory": "own", "yardline": 25}
    assert situation_bucket(ctx) == expected
