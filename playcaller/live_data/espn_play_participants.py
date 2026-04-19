"""
Extract player-facing labels from ESPN ``drives.*.plays[]`` rows.

Tier 1: structured ``participants`` / athlete objects.
Tier 2 (when fields are still empty): conservative parsing of ``text`` — see
:mod:`playcaller.live_data.espn_play_text_players`.

Enrichment is display-only; normalization never depends on these fields.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Dict

from playcaller.domain import ActualPlayResult

from .espn_play_text_players import (
    EspnTextPeople,
    parse_espn_play_text_players,
    play_text_from_espn_row,
    text_people_has_detail,
)


@dataclass
class EspnPlayPeople:
    passer: str = ""
    rusher: str = ""
    receiver: str = ""
    sacker: str = ""
    passer_jersey: str = ""
    receiver_jersey: str = ""
    rusher_jersey: str = ""
    receiver_role: str = ""  # WR | TE | RB when position data is unambiguous


def _athlete_position_role(athlete: Any) -> str:
    if not isinstance(athlete, dict):
        return ""
    pos = athlete.get("position")
    ab = ""
    if isinstance(pos, dict):
        ab = str(pos.get("abbreviation") or pos.get("shortName") or "").strip().upper()
    elif isinstance(pos, str):
        ab = pos.strip().upper()
    if ab in ("WR", "TE", "RB"):
        return ab
    if ab in ("FB",):
        return "RB"
    return ""


def _athlete_jersey_raw(athlete: Any) -> str:
    if not isinstance(athlete, dict):
        return ""
    jer = athlete.get("jersey") if athlete.get("jersey") is not None else athlete.get("jerseyNumber")
    if jer is None:
        return ""
    s = str(jer).strip()
    return s


def _athlete_display_name(athlete: Any) -> str:
    if not isinstance(athlete, dict):
        return ""
    name = str(athlete.get("displayName") or athlete.get("fullName") or "").strip()
    if name:
        return name
    sn = str(athlete.get("shortName") or "").strip()
    return sn


def _athlete_label(athlete: Any) -> str:
    """Display label: full name, else jersey as #n, else shortName."""
    name = _athlete_display_name(athlete)
    if name:
        return name
    jer = _athlete_jersey_raw(athlete)
    if jer:
        return f"#{jer}"
    return ""


def _participant_role_key(part: Dict[str, Any]) -> str:
    t = part.get("type")
    if isinstance(t, dict):
        return str(t.get("text") or t.get("id") or "").strip().lower()
    return str(t or "").strip().lower()


def extract_espn_play_people(play: Dict[str, Any]) -> EspnPlayPeople:
    """Tier-1 passer / rusher / receiver / sacker + jerseys / receiver role."""
    out = EspnPlayPeople()
    raw = play.get("participants")
    if not isinstance(raw, list):
        return out
    for part in raw:
        if not isinstance(part, dict):
            continue
        athlete = part.get("athlete")
        label = _athlete_label(athlete)
        jersey = _athlete_jersey_raw(athlete)
        pos_role = _athlete_position_role(athlete)
        role = _participant_role_key(part)
        rl = role.replace(" ", "")
        if not label and not jersey:
            continue
        if "passer" in role or role == "pass" or "passing" in role:
            out.passer = out.passer or label
            out.passer_jersey = out.passer_jersey or jersey
        elif "receiver" in role or "reception" in role or role == "receiver":
            out.receiver = out.receiver or label
            out.receiver_jersey = out.receiver_jersey or jersey
            out.receiver_role = out.receiver_role or pos_role
        elif "rusher" in role or role in ("rusher", "runner") or (
            "rush" in role and "pass" not in role
        ):
            out.rusher = out.rusher or label
            out.rusher_jersey = out.rusher_jersey or jersey
            if pos_role == "RB":
                out.receiver_role = out.receiver_role or "RB"
        elif (
            "sack" in role
            or "sackedby" in rl
            or "tackler" in role
            or "assistedtackle" in rl
        ):
            out.sacker = out.sacker or label
        elif "penalized" in role or "penalty" in role:
            continue

    return out


def _merge_people(struct: EspnPlayPeople, text: EspnTextPeople) -> EspnPlayPeople:
    """Structured wins; text fills gaps only."""
    return EspnPlayPeople(
        passer=struct.passer or text.passer,
        rusher=struct.rusher or text.rusher,
        receiver=struct.receiver or text.receiver,
        sacker=struct.sacker or text.sacked_by,
        passer_jersey=struct.passer_jersey or text.passer_jersey,
        receiver_jersey=struct.receiver_jersey or text.receiver_jersey,
        rusher_jersey=struct.rusher_jersey or text.rusher_jersey,
        receiver_role=struct.receiver_role or text.receiver_role,
    )


def _short_yards(y: int) -> str:
    if y > 0:
        return f"+{y} yds"
    if y < 0:
        return f"{y} yds"
    return "0 yds"


def _fmt_receiver_phrase(
    *,
    receiver: str,
    receiver_jersey: str,
    receiver_role: str,
    fallback_role_lbl: str,
) -> str:
    role = receiver_role or ""
    if role not in ("WR", "TE", "RB"):
        role = ""
    fb = (fallback_role_lbl or "").strip().upper()
    if not role and fb in ("WR", "TE", "RB"):
        role = fb
    if receiver and role:
        return f"{receiver} ({role})"
    if receiver:
        return receiver
    if role and receiver_jersey:
        return f"{role} #{receiver_jersey}"
    if role:
        return role
    if receiver_jersey:
        return f"receiver #{receiver_jersey}"
    return ""


def _fmt_rusher_phrase(*, rusher: str, rusher_jersey: str, fallback: str) -> str:
    if rusher:
        return rusher
    if rusher_jersey:
        if (fallback or "").strip().upper() in ("RB", "QB"):
            return f"{fallback.strip().upper()} #{rusher_jersey}"
        return f"RB #{rusher_jersey}"
    return (fallback or "").strip()


def enrich_espn_actual_with_participants(ap: ActualPlayResult, play: Dict[str, Any]) -> ActualPlayResult:
    """
    Overlay feed-only player labels and a richer ``description`` when data exists.

    Does not change ``play_type``, ``result_type``, ``family``, ``external_play_id``, or scoring flags.
    """
    struct = extract_espn_play_people(play)
    raw_text = play_text_from_espn_row(play)
    textp = parse_espn_play_text_players(raw_text)
    people = _merge_people(struct, textp)

    has_struct = any(
        (
            struct.passer,
            struct.rusher,
            struct.receiver,
            struct.sacker,
            struct.passer_jersey,
            struct.receiver_jersey,
            struct.rusher_jersey,
            struct.receiver_role,
        )
    )
    has_text = text_people_has_detail(textp)
    if not has_struct and not has_text:
        return ap

    yds = int(ap.yards_gained)
    ylbl = _short_yards(yds)
    rt = (ap.result_type or "").lower()
    pt = (ap.play_type or "").lower()
    pr = (ap.pass_result or "").lower()
    role_lbl = (ap.target_role_label or "").strip()

    recv_phrase = _fmt_receiver_phrase(
        receiver=people.receiver,
        receiver_jersey=people.receiver_jersey,
        receiver_role=people.receiver_role,
        fallback_role_lbl=role_lbl,
    )

    rusher_phrase = _fmt_rusher_phrase(
        rusher=people.rusher,
        rusher_jersey=people.rusher_jersey,
        fallback=ap.ball_carrier_or_target or "RB",
    )

    passer = people.passer or ap.feed_passer_label
    qb_for_scramble = passer

    new_desc = ap.description
    if rt == "touchdown" and pt == "pass":
        tail = recv_phrase or role_lbl or "receiver"
        if passer:
            new_desc = f"[ESPN] {passer} pass complete to {tail} · TD · {ylbl}"
        else:
            new_desc = f"[ESPN] Pass TD to {tail} · {ylbl}"
    elif rt == "touchdown" and pt == "run":
        carrier = rusher_phrase or ap.ball_carrier_or_target or "RB"
        new_desc = f"[ESPN] {carrier} run · TD · {ylbl}"
    elif rt in ("complete",) and pt == "pass" and pr == "complete":
        tail = recv_phrase or (f"to {role_lbl}" if role_lbl else "")
        if passer and recv_phrase:
            new_desc = f"[ESPN] {passer} pass complete to {recv_phrase} · {ylbl}"
        elif passer and tail:
            new_desc = f"[ESPN] {passer} pass complete {tail} · {ylbl}"
        elif passer:
            new_desc = f"[ESPN] {passer} pass complete · {ylbl}"
        elif recv_phrase:
            new_desc = f"[ESPN] Pass complete to {recv_phrase} · {ylbl}"
        else:
            new_desc = f"[ESPN] Pass complete{(' ' + tail) if tail else ''} · {ylbl}"
    elif rt == "incomplete" and pt == "pass":
        if passer and recv_phrase:
            new_desc = f"[ESPN] {passer} pass incomplete to {recv_phrase}"
        elif passer and role_lbl:
            new_desc = f"[ESPN] {passer} pass incomplete ({role_lbl})"
        elif passer:
            new_desc = f"[ESPN] {passer} pass incomplete"
        elif recv_phrase:
            new_desc = f"[ESPN] Pass incomplete to {recv_phrase}"
        else:
            tail = f" ({role_lbl})" if role_lbl else ""
            new_desc = f"[ESPN] Pass incomplete{tail}"
    elif bool(ap.sack):
        sk = people.sacker
        if passer and sk:
            new_desc = f"[ESPN] {passer} sacked by {sk} · {ylbl}"
        elif sk:
            new_desc = f"[ESPN] Sack by {sk} · {ylbl}"
        elif passer:
            new_desc = f"[ESPN] {passer} sacked · {ylbl}"
    elif pt == "qb_scramble":
        qb = qb_for_scramble or passer
        if qb:
            new_desc = f"[ESPN] QB scramble by {qb} · {ylbl}"
        else:
            new_desc = f"[ESPN] QB scramble · {ylbl}"
    elif pt == "run" and rt == "run" and (people.rusher or people.rusher_jersey):
        carrier = people.rusher or rusher_phrase
        if carrier and carrier.upper() not in ("RB", "QB"):
            new_desc = f"[ESPN] {carrier} run · {ylbl}"
        elif people.rusher_jersey:
            new_desc = f"[ESPN] Run by RB #{people.rusher_jersey} · {ylbl}"
        else:
            new_desc = f"[ESPN] Run by {rusher_phrase} · {ylbl}" if rusher_phrase else ap.description

    feed_role = people.receiver_role if people.receiver_role in ("WR", "TE", "RB") else ""
    if not feed_role and ap.feed_target_role in ("WR", "TE", "RB"):
        feed_role = ap.feed_target_role
    if not feed_role:
        rl0 = role_lbl.upper()
        if rl0 in ("WR", "TE", "RB"):
            feed_role = rl0

    bc = ap.ball_carrier_or_target
    if pt == "run" and (people.rusher or people.rusher_jersey):
        bc = people.rusher or bc
    elif pt == "pass" and people.receiver and rt in ("complete", "touchdown"):
        bc = people.receiver
    elif pt == "qb_scramble" and qb_for_scramble:
        bc = qb_for_scramble

    return replace(
        ap,
        description=new_desc,
        feed_passer_label=people.passer or ap.feed_passer_label,
        feed_receiver_label=people.receiver or ap.feed_receiver_label,
        feed_rusher_label=people.rusher or ap.feed_rusher_label,
        feed_target_role=feed_role or ap.feed_target_role,
        feed_passer_jersey=people.passer_jersey or ap.feed_passer_jersey,
        feed_receiver_jersey=people.receiver_jersey or ap.feed_receiver_jersey,
        feed_rusher_jersey=people.rusher_jersey or ap.feed_rusher_jersey,
        feed_defender_label=people.sacker or ap.feed_defender_label,
        ball_carrier_or_target=bc or ap.ball_carrier_or_target,
    )
