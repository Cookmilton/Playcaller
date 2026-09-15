"""Nullified vs real touchdown normalization (J1.3)."""

from __future__ import annotations

from playcaller.live_data.espn_play_normalize import espn_play_to_actual


def test_nullified_touchdown_is_penalty_not_td() -> None:
    """ESPN play 401872931345 — TOUCHDOWN NULLIFIED by Penalty (-10)."""
    raw = {
        "id": "401872931345",
        "text": (
            "(Shotgun) P.Mahomes scrambles right end for 5 yards, TOUCHDOWN NULLIFIED by Penalty."
            "PENALTY on KC-K.Benson, Offensive Holding, 10 yards, enforced at DEN 5 - No Play."
        ),
        "type": {"text": "Penalty"},
        "statYardage": -10,
        "scoringPlay": False,
    }
    ap = espn_play_to_actual(raw)
    assert ap is not None
    assert ap.touchdown is False
    assert ap.penalty is True
    assert ap.result_type in ("no_play", "penalty")
    assert ap.yards_gained == -10
    assert "TD" not in (ap.description or "")


def test_real_rushing_touchdown_still_marks_td() -> None:
    """ESPN play 401872931379 — real scramble TD (+15)."""
    raw = {
        "id": "401872931379",
        "text": (
            "(Shotgun) P.Mahomes scrambles up the middle for 15 yards, TOUCHDOWN. "
            "H.Butker extra point is GOOD, Center-J.Winchester, Holder-M.Araiza."
        ),
        "type": {"text": "Rushing Touchdown"},
        "statYardage": 15,
        "scoringPlay": True,
    }
    ap = espn_play_to_actual(raw)
    assert ap is not None
    assert ap.touchdown is True
    assert ap.result_type == "touchdown"
    assert ap.yards_gained == 15
