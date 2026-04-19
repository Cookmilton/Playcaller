"""Tests for ``DriveLogger`` operational helpers."""

from playcaller.domain import ActualPlayResult
from playcaller.state import DriveLogger


def _minimal_result(*, family: str = "dropback_pass") -> ActualPlayResult:
    return ActualPlayResult(
        family=family,
        concept_name="Test",
        yards_gained=5,
        result_type="complete_pass",
        description="Test play",
    )


def test_pop_last_returns_none_when_empty() -> None:
    dl = DriveLogger()
    assert dl.pop_last() is None
    assert dl.results == []


def test_pop_last_removes_tail_and_updates_counts() -> None:
    dl = DriveLogger()
    dl.log(_minimal_result(family="dropback_pass"))
    dl.log(_minimal_result(family="run_inside"))
    assert len(dl.results) == 2
    assert dl.family_counts["dropback_pass"] == 1
    assert dl.family_counts["run_inside"] == 1
    last = dl.pop_last()
    assert last is not None
    assert last.family == "run_inside"
    assert len(dl.results) == 1
    assert "run_inside" not in dl.family_counts
    assert dl.family_counts["dropback_pass"] == 1


def test_pop_last_all_plays_clears_counts() -> None:
    dl = DriveLogger()
    dl.log(_minimal_result())
    assert dl.pop_last() is not None
    assert dl.pop_last() is None
    assert dl.family_counts == {}
