"""G2.4: derived staleness of a generated recommendation vs the current situation.

Clock is excluded. A ``stale`` flag is never stored — compare the Generate fingerprint
to the board you would log against.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple

FINGERPRINT_FIELDS: Tuple[str, ...] = (
    "down",
    "distance",
    "yardline",
    "possession",
    "quarter",
    "score_differential",
)

REC_FINGERPRINT_KEY = "situation_fingerprint"


def situation_fingerprint(
    *,
    down: Any,
    distance: Any,
    yardline: Any,
    possession: Any,
    quarter: Any,
    score_differential: Any,
    territory: Any = None,
) -> dict:
    """Stable snapshot of the log-relevant situation (no clock)."""
    yl: Any
    if territory is None or str(territory).strip() == "":
        yl = int(yardline)
    else:
        yl = f"{str(territory).strip()}:{int(yardline)}"
    poss = None if possession is None or str(possession).strip() == "" else str(possession)
    return {
        "down": int(down),
        "distance": int(distance),
        "yardline": yl,
        "possession": poss,
        "quarter": int(quarter),
        "score_differential": int(score_differential),
    }


def fingerprint_from_game_state(game_state: Any, *, possession: Any = None) -> dict:
    """Read fingerprint fields from a mapping, ``GameContext``, or similar object."""
    def _get(name: str, *alts: str) -> Any:
        for key in (name, *alts):
            if isinstance(game_state, Mapping) and key in game_state:
                return game_state[key]
            if hasattr(game_state, key):
                return getattr(game_state, key)
        return None

    poss = possession if possession is not None else _get("possession")
    score = _get("score_differential", "score_diff")
    return situation_fingerprint(
        down=_get("down"),
        distance=_get("distance"),
        yardline=_get("yardline"),
        possession=poss,
        quarter=_get("quarter"),
        score_differential=0 if score is None else score,
        territory=_get("territory"),
    )


def attach_situation_fingerprint(rec: dict, game_state: Any, *, possession: Any = None) -> dict:
    """Store the fingerprint on the recommendation dict (mutates ``rec``)."""
    rec[REC_FINGERPRINT_KEY] = fingerprint_from_game_state(game_state, possession=possession)
    return rec


def stale_recommendation_fields(rec: Optional[Mapping[str, Any]], game_state: Any, *, possession: Any = None) -> Sequence[str]:
    if not isinstance(rec, Mapping):
        return ()
    stored = rec.get(REC_FINGERPRINT_KEY)
    if not isinstance(stored, Mapping) or not stored:
        return ()
    now = fingerprint_from_game_state(game_state, possession=possession)
    changed = [name for name in FINGERPRINT_FIELDS if stored.get(name) != now.get(name)]
    return tuple(changed)


def is_recommendation_stale(rec: Optional[Mapping[str, Any]], game_state: Any, *, possession: Any = None) -> bool:
    return bool(stale_recommendation_fields(rec, game_state, possession=possession))


def stale_recommendation_reason(rec: Optional[Mapping[str, Any]], game_state: Any, *, possession: Any = None) -> Optional[str]:
    fields: Iterable[str] = stale_recommendation_fields(rec, game_state, possession=possession)
    names = list(fields)
    if not names:
        return None
    shown = ", ".join(names)
    return f"Log is disabled — situation changed since Generate ({shown})."
