"""
Map raw ESPN play JSON objects into :class:`~playcaller.domain.ActualPlayResult`.

Heuristic text / type parsing only — no roster fidelity. Prefer stable categories
for drive summaries and :func:`~playcaller.game.classify_drive_end`.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from playcaller.domain import ActualPlayResult, PASS_FAMILIES, RUN_FAMILIES

from .espn_play_participants import enrich_espn_actual_with_participants
from .espn_play_text_players import play_text_from_espn_row

_ADMIN_SUBSTRINGS = (
    "end of quarter",
    "end of half",
    "two-minute warning",
    "end of game",
    "coin toss",
    "tv timeout",
    "timeout #",
    "official's timeout",
    "challenged",
    "challenge",
    "measurement",
    "review",
    "injury timeout",
)

def _play_text(play: Dict[str, Any]) -> str:
    return play_text_from_espn_row(play)


def _type_text(play: Dict[str, Any]) -> str:
    ty = play.get("type")
    if isinstance(ty, dict):
        return str(ty.get("text") or "")
    return str(ty or "")


def _yards(play: Dict[str, Any]) -> int:
    try:
        v = play.get("statYardage")
        if v is None:
            return 0
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _infer_target_role(text_l: str) -> Tuple[str, str]:
    """
    Broad role bucket + short label for descriptions.

    Returns (target_position, target_role_label) e.g. ("WR", "WR").
    """
    if "tight end" in text_l or re.search(r"\bte\b", text_l):
        return "TE", "TE"
    if "wide receiver" in text_l or re.search(r"\bwr\b", text_l) or " wideout" in text_l:
        return "WR", "WR"
    if "running back" in text_l or re.search(r"\brb\b", text_l) or " rusher " in text_l:
        return "RB", "RB"
    if "quarterback" in text_l or re.search(r"\bqb\b", text_l) or " qb " in text_l:
        return "QB", "QB"
    return "", ""


def _short_yards(y: int) -> str:
    if y > 0:
        return f"+{y} yds"
    if y < 0:
        return f"{y} yds"
    return "0 yds"


def should_skip_espn_play(play: Dict[str, Any]) -> bool:
    """Filter administrative / clock-only rows that are not football plays."""
    t = _play_text(play).strip().lower()
    if not t:
        return True
    return any(s in t for s in _ADMIN_SUBSTRINGS)


def _espn_play_to_actual_core(play: Dict[str, Any]) -> Optional[ActualPlayResult]:
    """Normalize ESPN JSON into categories and base descriptions (no participant overlay)."""
    text = _play_text(play).strip() or "(no description)"
    text_l = text.lower()
    ptype = _type_text(play).lower()
    yds = _yards(play)

    pos, role_lbl = _infer_target_role(text_l)

    # --- Touchdown (often embedded in another play type) ---
    if "touchdown" in text_l or ptype == "touchdown":
        if "pass" in text_l or "pass" in ptype:
            fam = "dropback_pass"
            pt, pr = "pass", "complete"
            desc = f"[ESPN] Pass TD ({role_lbl or 'receiver'}) · {_short_yards(yds)}"
            return ActualPlayResult(
                concept_name="Pass TD",
                family=fam,
                play_type=pt,
                result_type="touchdown",
                yards_gained=yds,
                target_position=pos or None,
                target_role_label=role_lbl,
                pass_result=pr,
                first_down=True,
                touchdown=True,
                description=desc,
            )
        if "field goal" in text_l:
            return ActualPlayResult(
                concept_name="Field goal",
                family="dropback_pass",
                play_type="special",
                result_type="field_goal",
                yards_gained=yds,
                touchdown=False,
                description=f"[ESPN] Field goal good · {_short_yards(yds)}",
            )
        fam = "inside_zone"
        carrier = "RB"
        if "quarterback" in text_l or "scramble" in text_l:
            fam, carrier = "draw", "QB"
            desc = f"[ESPN] QB run TD · {_short_yards(yds)}"
        else:
            desc = f"[ESPN] Run TD ({carrier}) · {_short_yards(yds)}"
        return ActualPlayResult(
            concept_name="Rush TD",
            family=fam,
            play_type="run",
            result_type="touchdown",
            yards_gained=yds,
            ball_carrier_or_target=carrier,
            first_down=True,
            touchdown=True,
            description=desc,
        )

    # --- Turnovers ---
    if "interception" in text_l or ptype == "interception" or "intercepted" in text_l:
        return ActualPlayResult(
            concept_name="Interception",
            family="dropback_pass",
            play_type="pass",
            result_type="interception",
            yards_gained=yds,
            turnover=True,
            turnover_kind="interception",
            pass_result="intercepted",
            target_position=pos or None,
            target_role_label=role_lbl,
            description=f"[ESPN] Interception · {_short_yards(yds)}",
        )

    if "fumble" in text_l:
        tk = "fumble"
        recovered_opp = "own" not in text_l and "recovered" in text_l
        return ActualPlayResult(
            concept_name="Fumble",
            family="inside_zone",
            play_type="run",
            result_type="fumble",
            yards_gained=yds,
            turnover=recovered_opp,
            turnover_kind=tk,
            description=f"[ESPN] Fumble · {_short_yards(yds)}",
        )

    # --- Kicks / punts ---
    if "field goal" in text_l:
        missed = any(x in text_l for x in ("no good", "missed", "blocked", "wide", "short"))
        if missed:
            return ActualPlayResult(
                concept_name="Field goal",
                family="dropback_pass",
                play_type="special",
                result_type="field_goal_miss",
                yards_gained=yds,
                description=f"[ESPN] Field goal missed · {_short_yards(yds)}",
            )
        return ActualPlayResult(
            concept_name="Field goal",
            family="dropback_pass",
            play_type="special",
            result_type="field_goal",
            yards_gained=yds,
            description=f"[ESPN] Field goal good · {_short_yards(yds)}",
        )

    if "punt" in text_l or ptype == "punt":
        return ActualPlayResult(
            concept_name="Punt",
            family="inside_zone",
            play_type="special",
            result_type="punt",
            yards_gained=yds,
            description=f"[ESPN] Punt · {_short_yards(yds)}",
        )

    # --- Sack ---
    if "sack" in text_l or ptype == "sack":
        return ActualPlayResult(
            concept_name="Sack",
            family="dropback_pass",
            play_type="pass",
            result_type="sack",
            yards_gained=yds,
            sack=True,
            pass_result="sack",
            description=f"[ESPN] Sack · {_short_yards(yds)}",
        )

    # --- Penalty ---
    if "penalty" in text_l or ptype == "penalty":
        no_play = "no play" in text_l or "declined" in text_l
        return ActualPlayResult(
            concept_name="Penalty",
            family="inside_zone",
            play_type="admin",
            result_type="no_play" if no_play else "penalty",
            yards_gained=yds,
            penalty=True,
            penalty_yards=abs(yds),
            description=f"[ESPN] Penalty · {_short_yards(yds)}",
        )

    if "scramble" in text_l or " qb rush" in text_l or (ptype == "rushing" and "quarterback" in text_l):
        return ActualPlayResult(
            concept_name="QB scramble",
            family="draw",
            play_type="qb_scramble",
            result_type="scramble",
            yards_gained=yds,
            scramble=True,
            ball_carrier_or_target="QB",
            description=f"[ESPN] QB scramble · {_short_yards(yds)}",
        )

    if (
        "pass" in text_l
        or "pass" in ptype
        or ptype in ("pass reception",)
        or "threw" in text_l
        or "catch" in text_l
    ) and "interception" not in text_l:
        if "incomplete" in text_l:
            tail = f" ({role_lbl})" if role_lbl else ""
            return ActualPlayResult(
                concept_name="Pass incomplete",
                family="dropback_pass",
                play_type="pass",
                result_type="incomplete",
                yards_gained=0,
                pass_result="incomplete",
                target_position=pos or None,
                target_role_label=role_lbl,
                description=f"[ESPN] Pass incomplete{tail}",
            )
        tail = f" to {role_lbl}" if role_lbl else ""
        fd = "first down" in text_l
        return ActualPlayResult(
            concept_name=f"Pass ({role_lbl or 'receiver'})",
            family="dropback_pass",
            play_type="pass",
            result_type="complete",
            yards_gained=yds,
            target_position=pos or None,
            target_role_label=role_lbl,
            pass_result="complete",
            first_down=fd,
            description=f"[ESPN] Pass complete{tail} · {_short_yards(yds)}",
        )

    # --- Rush ---
    if (
        "rush" in ptype
        or "rushing" in ptype
        or " run " in text_l
        or text_l.endswith(" run")
        or " rushes " in text_l
        or "kneel" in text_l
    ):
        if "kneel" in text_l:
            return ActualPlayResult(
                concept_name="Kneel",
                family="inside_zone",
                play_type="run",
                result_type="kneel",
                yards_gained=yds,
                ball_carrier_or_target="QB",
                description=f"[ESPN] QB kneel · {_short_yards(yds)}",
            )
        return ActualPlayResult(
            concept_name="RB run",
            family="inside_zone",
            play_type="run",
            result_type="run",
            yards_gained=yds,
            ball_carrier_or_target="RB",
            first_down="first down" in text_l,
            description=f"[ESPN] RB run · {_short_yards(yds)}",
        )

    # --- Turnover on downs (explicit) ---
    if "turnover on downs" in text_l:
        return ActualPlayResult(
            concept_name="Turnover on downs",
            family="inside_zone",
            play_type="run",
            result_type="turnover_on_downs",
            yards_gained=yds,
            turnover=True,
            description=f"[ESPN] Turnover on downs · {_short_yards(yds)}",
        )

    # --- Fallback: preserve type hint ---
    fam = "dropback_pass"
    pt = "pass"
    if "rush" in ptype or "rushing" in ptype:
        fam, pt = "inside_zone", "run"
    desc = f"[ESPN] {ptype or 'Play'} · {_short_yards(yds)} — {text[:120]}"
    return ActualPlayResult(
        concept_name=ptype or "Play",
        family=fam,
        play_type=pt,
        result_type="unknown",
        yards_gained=yds,
        description=desc,
    )


def espn_play_to_actual(play: Dict[str, Any]) -> Optional[ActualPlayResult]:
    """
    Convert one ESPN ``drives.*.plays[]`` element into an ``ActualPlayResult``.

    Returns ``None`` for rows that should not appear in a drive chart (timeouts, etc.).
    """
    if not isinstance(play, dict):
        return None
    if should_skip_espn_play(play):
        return None
    ap = _espn_play_to_actual_core(play)
    if ap is None:
        return None
    return enrich_espn_actual_with_participants(ap, play)


def validate_actual_for_engine(a: ActualPlayResult) -> ActualPlayResult:
    """Ensure ``family`` is in a bucket the predictor recognizes when possible."""
    from dataclasses import replace

    if a.family in RUN_FAMILIES or a.family in PASS_FAMILIES:
        return a
    if a.play_type == "run":
        return replace(a, family="inside_zone")
    if a.play_type in ("pass", "qb_scramble"):
        return replace(a, family="dropback_pass")
    return replace(a, family="dropback_pass")
