"""
Structured **actual** play results (post-log) — formatting and classification helpers.

``PredictedPlayResult`` / ``predicted_play_result`` stay recommendation-only; this module
is for logged truth on ``ActualPlayResult``.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from typing import Optional, Tuple

from .domain import (
    CALL_SOURCE_UNOBSERVED,
    PASS_FAMILIES,
    RUN_FAMILIES,
    TRUSTED_CALL_SOURCES,
    ActualPlayResult,
    ball_carrier_and_target_from_play,
    play_type_for_family,
)
from .situation import classify_logged_outcome


def classify_actual_result_type(
    *,
    yards: int,
    to_go: int,
    earned_first_down: bool,
    touchdown: bool,
    pass_result: str = "",
    turnover_kind: str = "",
    sack: bool = False,
) -> str:
    """Stable ``result_type`` including pass-specific outcomes."""
    pr = (pass_result or "").strip().lower()
    tk = (turnover_kind or "").strip().lower()
    if tk == "interception" or pr == "intercepted":
        return "interception"
    if pr == "incomplete":
        return "incomplete"
    if sack or pr == "sack":
        y = int(yards)
        if touchdown:
            return "touchdown"
        if earned_first_down:
            return "first_down_exact" if y == int(to_go) else "first_down"
        if y == 0:
            return "no_gain"
        return "sack" if y <= -4 else "negative"
    return classify_logged_outcome(
        yards=yards,
        to_go=to_go,
        earned_first_down=earned_first_down,
        touchdown=touchdown,
    )


def earned_first_down_for_advance(actual: ActualPlayResult, distance: int) -> bool:
    """Whether the chains should move — excludes INT, incomplete, sack, turnover."""
    if actual.turnover or (actual.turnover_kind or "").lower() == "interception":
        return False
    pr = (actual.pass_result or "").lower()
    if pr in ("incomplete", "intercepted", "sack"):
        return False
    if actual.sack:
        return False
    return int(actual.yards_gained) >= int(distance)


def _yards_phrase(n: int) -> str:
    n = int(n)
    if n == 1:
        return "1 yard"
    if n == -1:
        return "loss of 1"
    if n < 0:
        return f"loss of {abs(n)}"
    return f"{n} yards"


def _feed_receiver_display(a: ActualPlayResult) -> str:
    """Display-only: names/jerseys from feed overlays when structured target labels are generic."""
    r = (a.feed_receiver_label or "").strip()
    role = (a.feed_target_role or "").strip().upper()
    jer = (a.feed_receiver_jersey or "").strip()
    if r and role in ("WR", "TE", "RB"):
        return f"{r} ({role})"
    if r:
        return r
    if role in ("WR", "TE", "RB") and jer:
        return f"{role} #{jer}"
    if role in ("WR", "TE", "RB"):
        return role
    if jer:
        return f"receiver #{jer}"
    return ""


def _target_tail(a: ActualPlayResult, *, for_interception: bool) -> str:
    label = (a.target_role_label or "").strip()
    if label:
        return f" targeting {label}" if for_interception else f" to {label}"
    pos = (a.target_position or a.ball_carrier_or_target or "").strip().upper()
    if not pos:
        return ""
    if pos == "H":
        phrase = "slot"
    elif pos == "Y":
        phrase = "TE"
    elif pos in ("X", "Z"):
        phrase = f"{pos} receiver"
    elif pos == "RB":
        phrase = "RB"
    elif pos == "QB":
        phrase = "QB"
    else:
        phrase = f"{pos} receiver"
    return f" targeting {phrase}" if for_interception else f" to {phrase}"


def format_actual_play_result_description(a: ActualPlayResult) -> str:
    """
    One-line broadcast-style summary from structured fields.

    If ``a.description`` is set, returns it; otherwise derives from fields.
    """
    if (a.description or "").strip():
        return (a.description or "").strip()

    rtype = (a.result_type or "").strip().lower()
    if rtype == "field_goal":
        y = int(a.yards_gained)
        return f"Field goal good — {y}" if y > 0 else "Field goal good"
    if rtype == "field_goal_miss":
        y = int(a.yards_gained)
        return f"Field goal missed — {y}" if y > 0 else "Field goal missed"

    pr = (a.pass_result or "").strip().lower()
    pt = (a.play_type or "").strip().lower()
    tk = (a.turnover_kind or "").strip().lower()

    if tk == "interception" or pr == "intercepted":
        return f"Interception{_target_tail(a, for_interception=True)}".rstrip()

    if a.sack or pr == "sack":
        y = int(a.yards_gained)
        def_fb = (a.feed_defender_label or "").strip()
        qb_fb = (a.feed_passer_label or "").strip()
        if qb_fb and def_fb:
            sack_line = f"{qb_fb} sacked by {def_fb}"
        elif def_fb:
            sack_line = f"Sack by {def_fb}"
        elif qb_fb:
            sack_line = f"{qb_fb} sacked"
        else:
            sack_line = ""
        if sack_line:
            if y < 0:
                return f"{sack_line} for {_yards_phrase(y)}"
            return f"{sack_line} for no gain" if y == 0 else f"{sack_line} for {_yards_phrase(y)}"
        if y < 0:
            return f"Sack for {_yards_phrase(y)}"
        return "Sack for no gain"

    if a.scramble or (pt in ("qb_scramble", "qb_run") and pr != "complete"):
        qb_fb = (a.feed_passer_label or "").strip()
        if qb_fb:
            return f"QB scramble by {qb_fb} for {_yards_phrase(int(a.yards_gained))}"
        return f"QB scramble for {_yards_phrase(int(a.yards_gained))}"

    if pt == "run" or (pt not in ("pass", "qb_scramble", "qb_run") and a.family in RUN_FAMILIES):
        rush_fb = (a.feed_rusher_label or "").strip()
        jer = (a.feed_rusher_jersey or "").strip()
        carrier = rush_fb or (a.ball_carrier_or_target or "RB").strip() or "RB"
        if (not rush_fb) and jer:
            carrier = f"RB #{jer}"
        if carrier.upper() in ("RB", "QB") and rush_fb:
            carrier = rush_fb
        if a.touchdown:
            if rush_fb and rush_fb.upper() not in ("RB", "QB"):
                return f"{rush_fb} run · TD for {_yards_phrase(int(a.yards_gained))}"
            return f"Touchdown run by {carrier} for {_yards_phrase(int(a.yards_gained))}"
        if rush_fb and rush_fb.upper() not in ("RB", "QB"):
            return f"{rush_fb} run for {_yards_phrase(int(a.yards_gained))}"
        return f"Run by {carrier} for {_yards_phrase(int(a.yards_gained))}"

    if pt == "pass" or a.family in PASS_FAMILIES:
        tail = _feed_receiver_display(a) or _target_tail(a, for_interception=False)
        passer = (a.feed_passer_label or "").strip()
        if pr == "incomplete":
            if passer and tail:
                return f"{passer} pass incomplete to {tail}".rstrip()
            if passer:
                return f"{passer} pass incomplete".rstrip()
            return f"Pass incomplete{tail}".rstrip()
        if a.touchdown:
            if passer and tail:
                return f"{passer} pass complete to {tail} · TD for {_yards_phrase(int(a.yards_gained))}"
            return f"Touchdown pass{tail} for {_yards_phrase(int(a.yards_gained))}"
        if pr == "complete" or (not pr and int(a.yards_gained) > 0):
            if passer and tail:
                return f"{passer} pass complete to {tail} for {_yards_phrase(int(a.yards_gained))}"
            return f"Pass complete{tail} for {_yards_phrase(int(a.yards_gained))}"
        if passer and tail:
            return f"{passer} pass to {tail} for {_yards_phrase(int(a.yards_gained))}"
        return f"Pass{tail} for {_yards_phrase(int(a.yards_gained))}"

    if a.touchdown:
        return f"Touchdown for {_yards_phrase(int(a.yards_gained))}"
    return f"Play for {int(a.yards_gained):+d} yards"


def actual_play_structured_dict(a: ActualPlayResult) -> dict:
    """JSON-serializable snapshot of logged truth (for replay / analysis pipelines)."""
    return asdict(a)


def _analysis_category_and_body(a: ActualPlayResult) -> Tuple[str, str]:
    """
    (category_label, body_phrase) for operator-facing analysis lines.
    Body omits redundant category words when possible.
    """
    rtype = (a.result_type or "").strip().lower()
    pr = (a.pass_result or "").strip().lower()
    pt = (a.play_type or "").strip().lower()
    tk = (a.turnover_kind or "").strip().lower()

    if rtype == "punt":
        y = int(a.yards_gained)
        return "Punt", f"net {_yards_phrase(y)}" if y else "—"
    if rtype == "kickoff":
        y = int(a.yards_gained)
        return "Kickoff", _yards_phrase(y) if y else "—"
    if rtype in ("extra_point", "extra_point_miss"):
        return "Extra point", "good" if rtype == "extra_point" else "missed"
    if rtype == "field_goal":
        return "Field goal", "good"
    if rtype == "field_goal_miss":
        return "Field goal", "missed"

    if a.penalty:
        y = int(a.penalty_yards)
        note = (a.notes or "").strip() or "penalty"
        return "Penalty", f"{note}, {_yards_phrase(y)}" if y else note

    if tk == "fumble" or rtype == "fumble":
        return "Fumble", format_actual_play_result_description(a)

    if tk == "interception" or pr == "intercepted":
        return "Interception", format_actual_play_result_description(a).replace("Interception", "").strip() or "—"

    if a.sack or pr == "sack":
        y = int(a.yards_gained)
        def_fb = (a.feed_defender_label or "").strip()
        qb_fb = (a.feed_passer_label or "").strip()
        if qb_fb and def_fb:
            body = f"{qb_fb} sacked by {def_fb} ({_yards_phrase(y)})"
        elif def_fb:
            body = f"by {def_fb} ({_yards_phrase(y)})"
        else:
            body = _yards_phrase(y)
        return "Sack", body

    if a.scramble or pt in ("qb_scramble", "qb_run"):
        qb_fb = (a.feed_passer_label or "").strip()
        y = int(a.yards_gained)
        if qb_fb:
            return "QB scramble", f"{qb_fb} · {_yards_phrase(y)}"
        return "QB scramble", _yards_phrase(y)

    if pt == "run" or (pt not in ("pass", "qb_scramble", "qb_run") and a.family in RUN_FAMILIES):
        rush_fb = (a.feed_rusher_label or "").strip()
        carrier = rush_fb or (a.ball_carrier_or_target or "").strip() or "Runner"
        y = int(a.yards_gained)
        if a.touchdown:
            return "Run", f"{carrier} · TD · {_yards_phrase(y)}"
        return "Run", f"{carrier} · {_yards_phrase(y)}"

    if pt == "pass" or a.family in PASS_FAMILIES:
        tail = _feed_receiver_display(a) or _target_tail(a, for_interception=False)
        passer = (a.feed_passer_label or "").strip()
        y = int(a.yards_gained)
        if pr == "incomplete":
            if passer and tail:
                return "Pass incomplete", f"{passer} to {tail}"
            if passer:
                return "Pass incomplete", passer
            return "Pass incomplete", (tail or "—").lstrip(" to")
        if a.touchdown:
            if passer and tail:
                return "Pass complete", f"{passer} to {tail} · TD · {_yards_phrase(y)}"
            return "Pass complete", f"TD · {_yards_phrase(y)}"
        if pr == "complete" or (not pr and y > 0):
            if passer and tail:
                return "Pass complete", f"{passer} to {tail} · {_yards_phrase(y)}"
            return "Pass complete", (f"{tail} · {_yards_phrase(y)}" if tail else _yards_phrase(y)).lstrip()

    if a.touchdown:
        return "Touchdown", _yards_phrase(int(a.yards_gained))

    body = format_actual_play_result_description(a)
    return "", body


def format_actual_play_analysis_primary(a: ActualPlayResult) -> str:
    """
    Single scannable headline: **Category** — detail (broadcast / analysis style).

    Prefer this over raw ``description`` when building analysis surfaces; falls back to
    :func:`format_actual_play_result_description` when category is unknown.
    """
    cat, body = _analysis_category_and_body(a)
    body = (body or "").strip()
    if cat and body:
        return f"{cat} — {body}"
    if body:
        return body
    return format_actual_play_result_description(a)


def format_actual_play_operator_headline(a: ActualPlayResult) -> str:
    """
    Primary line for drive-archive / comparison UIs: prefer feed ``description``, then analysis headline.
    """
    desc = (a.description or "").strip()
    if desc:
        return desc
    line = format_actual_play_analysis_primary(a).strip()
    if line:
        return line
    return format_actual_play_result_description(a)


def format_actual_play_operator_detail(a: ActualPlayResult) -> str:
    """
    Secondary line: concept / family / markers. Omits redundancy when the headline already carries names.
    """
    return format_actual_play_analysis_detail(a)


def format_actual_play_analysis_detail(a: ActualPlayResult) -> str:
    """Secondary line: concept/family tags and situation markers (may be empty)."""
    parts: list[str] = []
    fam = (a.family or "").strip()
    cn = (a.concept_name or "").strip()
    if fam:
        parts.append(fam.replace("_", " "))
    if cn:
        parts.append(f"“{cn}”")
    if not fam and not cn:
        # K1.2: say so, rather than silently omitting the call from the line.
        parts.append(NOT_RECORDED_LABEL)
    pt = (a.play_type or "").strip()
    if pt and pt not in (x.lower() for x in parts):
        parts.append(pt)
    markers: list[str] = []
    if a.touchdown:
        markers.append("TD")
    if a.first_down and not a.touchdown:
        markers.append("1st down")
    if a.turnover:
        markers.append("Turnover")
    if (a.turnover_kind or "").strip():
        markers.append(str(a.turnover_kind).strip())
    tr = (a.feed_target_role or "").strip().upper()
    if tr in ("WR", "TE", "RB"):
        markers.append(f"target {tr}")
    def_fb = (a.feed_defender_label or "").strip()
    if def_fb:
        markers.append(f"vs {def_fb}")
    y = int(a.yards_gained)
    py = int(a.penalty_yards) if a.penalty else 0
    if py:
        markers.append(f"penalty yards {py:+d}")

    bits = []
    if parts:
        bits.append(" · ".join(parts))
    if markers:
        bits.append(" · ".join(markers))
    return " · ".join(bits) if bits else ""


#: Shown wherever a logged play's family / concept was never recorded (K1.2). An
#: explicit state — never blank text, and never a colour that reads as a real family.
NOT_RECORDED_LABEL = "call not recorded"
#: Amber-grey, deliberately outside ``FAM_COLOR``'s run-green / pass-blue palette.
NOT_RECORDED_COLOR = "#78716c"


def family_display_label(family: Optional[str]) -> str:
    """Family for display, or an explicit "not recorded" when the call is unobserved."""
    fam = (family or "").strip()
    if not fam:
        return NOT_RECORDED_LABEL
    return fam.replace("_", " ")


def family_display_color(family: Optional[str], palette: dict) -> str:
    """Colour for ``family``; unobserved calls get their own colour, not a palette default."""
    fam = (family or "").strip()
    if not fam:
        return NOT_RECORDED_COLOR
    return palette.get(fam, NOT_RECORDED_COLOR)


def role_label_from_position(pos: Optional[str]) -> str:
    if not pos:
        return ""
    u = str(pos).strip().upper()
    if u == "H":
        return "slot"
    if u == "Y":
        return "TE"
    if u in ("X", "Z"):
        return f"{u} receiver"
    if u in ("RB", "QB"):
        return u
    return u


def target_role_label_from_choice(target_choice: str, pos_code: Optional[str]) -> str:
    tc = (target_choice or "").strip()
    if tc.startswith("Auto"):
        return role_label_from_position(pos_code)
    mapping = {
        "X": "X receiver",
        "Z": "Z receiver",
        "H (slot)": "slot",
        "Y (TE)": "TE",
        "RB": "RB",
        "QB": "QB",
    }
    return mapping.get(tc, role_label_from_position(tc))


def carrier_and_position_from_target_choice(
    target_choice: str,
    play: dict,
    family: str,
) -> tuple[str, Optional[str], str]:
    """
    Returns (ball_carrier_or_target, target_position, target_role_label).
    """
    if (target_choice or "").startswith("Auto"):
        bc, tpos = ball_carrier_and_target_from_play(play, family)
        return bc, tpos, role_label_from_position(tpos)

    code_map = {
        "X": ("X", "X"),
        "Z": ("Z", "Z"),
        "H (slot)": ("H", "H"),
        "Y (TE)": ("Y", "Y"),
        "RB": ("RB", None),
        "QB": ("QB", None),
    }
    bc, tpos = code_map.get(target_choice, ("", None))
    lbl = target_role_label_from_choice(target_choice, tpos)
    return bc, tpos, lbl


def resolve_logging_semantics(
    *,
    family: Optional[str],
    yards_gained: int,
    outcome_ui: str,
    sack_from_chip: bool,
) -> tuple[Optional[str], str, bool, bool, bool, str, str]:
    """
    Derive (play_type, pass_result, sack, scramble, turnover, turnover_kind, result_type_preset)
    from UI. ``result_type_preset`` is ``field_goal``, ``field_goal_miss``, or ``""``.

    K1.2: ``play_type`` comes from ``outcome_ui``. ``family`` is only consulted when the
    operator confirmed the call — on ``Auto`` with no family the play type is ``None``
    ("not recorded") rather than a guess inherited from the recommendation.
    """
    y = int(yards_gained)
    base_pt = play_type_for_family(family) if family else None
    auto = (outcome_ui or "").startswith("Auto")

    if not auto:
        if outcome_ui == "Complete pass":
            return "pass", "complete", False, False, False, "", ""
        if outcome_ui == "Incomplete pass":
            return "pass", "incomplete", False, False, False, "", ""
        if outcome_ui == "QB scramble":
            return "qb_scramble", "", False, True, False, "", ""
        if outcome_ui == "Run":
            return "run", "", False, False, False, "", ""
        if outcome_ui == "Sack":
            return "pass", "sack", True, False, False, "", ""
        if outcome_ui == "Interception":
            return "pass", "intercepted", False, False, True, "interception", ""
        if outcome_ui == "Field goal good":
            return "field_goal", "", False, False, False, "", "field_goal"
        if outcome_ui == "Field goal missed":
            return "field_goal", "", False, False, False, "", "field_goal_miss"

    if sack_from_chip:
        return "pass", "sack", True, False, False, "", ""
    if base_pt is None:
        # Auto with no confirmed call: yards alone do not say run or pass.
        return None, "", False, False, False, "", ""
    if base_pt == "pass" and y <= -4:
        return "pass", "sack", True, False, False, "", ""
    if base_pt == "run":
        return "run", "", False, False, False, "", ""
    if base_pt == "pass":
        if y > 0:
            return "pass", "complete", False, False, False, "", ""
        return "pass", "incomplete", False, False, False, "", ""
    return base_pt, "", False, False, False, "", ""


def assemble_actual_semantics(
    *,
    concept_name: Optional[str],
    family: Optional[str],
    play: dict,
    yards_gained: int,
    target_choice: str,
    outcome_ui: str,
    sack_from_chip: bool,
    forced_interception: bool = False,
    forced_incomplete: bool = False,
    call_source: str = CALL_SOURCE_UNOBSERVED,
) -> ActualPlayResult:
    """Build semantic ``ActualPlayResult`` before down/distance advance (yards/flags only).

    K1.2: ``family`` / ``concept_name`` are only kept when ``call_source`` says the
    operator confirmed the call was run. Otherwise they stay ``None`` — the logged play
    must not inherit the *recommendation's* identity just because it was on screen.
    """
    if call_source not in TRUSTED_CALL_SOURCES:
        family = None
        concept_name = None
    oc = outcome_ui
    if forced_interception:
        oc = "Interception"
    elif forced_incomplete:
        oc = "Incomplete pass"

    yds = int(yards_gained)
    if oc == "Interception":
        yds = 0
    elif oc == "Incomplete pass":
        yds = 0

    pt, pr, sack, scramble, turnover, tk, preset_rt = resolve_logging_semantics(
        family=family,
        yards_gained=yds,
        outcome_ui=oc,
        sack_from_chip=sack_from_chip,
    )
    if forced_interception:
        pt, pr, sack, scramble = "pass", "intercepted", False, False
        turnover, tk = True, "interception"
        yds = 0

    bc, tpos, role_lbl = carrier_and_position_from_target_choice(target_choice, play, family)

    if pt == "run":
        if not bc:
            bc = "RB"
        tpos = None
        role_lbl = role_lbl or "RB"
    elif pt == "qb_scramble":
        bc, tpos, role_lbl = "QB", None, "QB"

    return ActualPlayResult(
        concept_name=concept_name,
        family=family,
        play_type=pt,
        call_source=call_source,
        pass_result=pr,
        result_type=preset_rt or "",
        yards_gained=yds,
        ball_carrier_or_target=bc,
        target_position=tpos,
        target_role_label=role_lbl,
        scramble=scramble,
        first_down=False,
        touchdown=False,
        turnover=turnover,
        turnover_kind=tk,
        sack=sack,
        penalty=False,
        penalty_yards=0,
        notes="",
        description="",
    )


def finalize_actual_after_snap(
    base: ActualPlayResult,
    *,
    snap,
    to_go: int,
    earned_first_down: bool,
) -> ActualPlayResult:
    """Set ``result_type``, ``first_down``, ``touchdown``, and formatted ``description``."""
    preset = (base.result_type or "").strip().lower()
    if preset in ("field_goal", "field_goal_miss"):
        rt = preset
    else:
        rt = classify_actual_result_type(
            yards=base.yards_gained,
            to_go=to_go,
            earned_first_down=earned_first_down,
            touchdown=snap.touchdown,
            pass_result=base.pass_result,
            turnover_kind=base.turnover_kind,
            sack=base.sack,
        )
    fd = rt in ("first_down", "first_down_exact", "touchdown")
    out = replace(
        base,
        result_type=rt,
        first_down=fd,
        touchdown=snap.touchdown,
    )
    return replace(out, description=format_actual_play_result_description(out))


__all__ = [
    "actual_play_structured_dict",
    "assemble_actual_semantics",
    "carrier_and_position_from_target_choice",
    "classify_actual_result_type",
    "earned_first_down_for_advance",
    "finalize_actual_after_snap",
    "format_actual_play_analysis_detail",
    "format_actual_play_analysis_primary",
    "format_actual_play_operator_detail",
    "format_actual_play_operator_headline",
    "format_actual_play_result_description",
    "resolve_logging_semantics",
    "role_label_from_position",
    "target_role_label_from_choice",
]
