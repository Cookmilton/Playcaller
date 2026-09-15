"""
Live-board honesty for the console HUD and Generate affordances.

Skipped situation fields (and every field when ``situation_source`` is missing on a
feed sync) must not be shown as live defaults. Operator-owned boards (manual origin or
a lock skip) still display the widget values.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from playcaller.game_situation_input import format_ball_spot, format_down_distance, period_display_label
from playcaller.live_data.drive_boundaries import PREVIOUS_FEED_DRIVE_OPEN
from playcaller.streamlit_state.possession import (
    GENERATE_OPPONENT_REASON,
    ORIGIN_FEED,
    ORIGIN_MANUAL,
    generate_blocked_reason_for_possession,
    possession_is_opponent,
    possession_is_unset,
)

_SKIP_LOCKED = "locked"

NOT_SYNCED_TEXT = "not synced"
UNKNOWN_POSSESSION_TEXT = "unknown"

SOURCE_CHIP_SCOREBOARD = "ESPN live"
SOURCE_CHIP_LAST_PLAY = "ESPN last play"
SOURCE_CHIP_MANUAL = "Manual"
SOURCE_CHIP_NOT_SET = "Not set"
SOURCE_CHIP_PRESET = "Preset"

_SKIP_REASON_CAPTION = {
    "no_situation_source": "no live situation in this sync",
    "absent_in_source": "not present in the ESPN payload",
    "out_of_range": "ESPN value outside the widget domain",
    "locked": "held by operator lock",
}

_BOARD_FIELD_LABEL = {
    "down": "Down",
    "distance": "Distance",
    "field_position": "Field position",
    "quarter": "Quarter",
    "clock": "Clock",
}

_CLOCK_BOARD_FIELDS = frozenset({"quarter", "clock"})


@dataclass(frozen=True)
class HonestField:
    synced: bool
    text: str
    reason: str = ""


@dataclass(frozen=True)
class SituationHonesty:
    source_chip: str
    down: HonestField
    distance: HonestField
    field_position: HonestField
    possession: HonestField
    own_timeouts: HonestField
    opp_timeouts: HonestField
    quarter: HonestField
    clock: HonestField
    generate_blocked_reason: Optional[str]
    unsynced_board_warning: Optional[str]

    def reason_captions(self) -> tuple[str, ...]:
        out: list[str] = []
        seen: set[str] = set()
        for fld in (
            self.down,
            self.distance,
            self.field_position,
            self.possession,
            self.own_timeouts,
            self.opp_timeouts,
            self.quarter,
            self.clock,
        ):
            if fld.synced or not fld.reason:
                continue
            if fld.reason in seen:
                continue
            seen.add(fld.reason)
            out.append(fld.reason)
        return tuple(out)


def skipped_situation_reasons(audit: Any) -> dict[str, str]:
    """Map situation field name → skip reason from last-sync audit ``skipped``."""
    if not isinstance(audit, Mapping):
        return {}
    out: dict[str, str] = {}
    for entry in audit.get("skipped") or []:
        if not isinstance(entry, dict):
            continue
        field = str(entry.get("field") or "").strip()
        reason = str(entry.get("reason") or "").strip()
        if field and reason:
            out[field] = reason
    return out


def leftover_feed_drive_caption(audit: Any) -> Optional[str]:
    """Console copy when sync left the previous ESPN drive open in DriveLogger."""
    if not isinstance(audit, Mapping):
        return None
    for entry in audit.get("skipped") or []:
        if entry == PREVIOUS_FEED_DRIVE_OPEN:
            return (
                "Previous feed drive still open in DriveLogger. "
                "End drive to archive it — the new ESPN drive will not merge until you do."
            )
    return None


def defense_look_chip_label(origin: Any) -> str:
    """Personnel/box/coverage/safeties are never ESPN-observed — Preset or Manual only."""
    if str(origin or "").strip() == ORIGIN_MANUAL:
        return SOURCE_CHIP_MANUAL
    return SOURCE_CHIP_PRESET


def situation_source_chip_label(*, origin: str, situation_source: Optional[str]) -> str:
    o = str(origin or "").strip()
    if o == ORIGIN_FEED:
        if situation_source == "scoreboard":
            return SOURCE_CHIP_SCOREBOARD
        if situation_source == "last_play_end":
            return SOURCE_CHIP_LAST_PLAY
        return SOURCE_CHIP_NOT_SET
    if o == ORIGIN_MANUAL:
        return SOURCE_CHIP_MANUAL
    return SOURCE_CHIP_NOT_SET


def skip_reason_caption(reason: str) -> str:
    return _SKIP_REASON_CAPTION.get(reason, reason.replace("_", " "))


def field_is_not_synced(
    field: str,
    *,
    origin: str,
    situation_source: Optional[str],
    skipped: Mapping[str, str],
) -> bool:
    """True when the HUD must not treat the board default as a live feed value."""
    if str(origin or "").strip() != "feed":
        return False
    reason = skipped.get(field)
    if reason == _SKIP_LOCKED:
        return False
    if field in _CLOCK_BOARD_FIELDS:
        return field in skipped
    if situation_source is None:
        return True
    return field in skipped


def generate_blocked_reason(*, possession: Optional[str]) -> Optional[str]:
    return generate_blocked_reason_for_possession(possession)


def unsynced_board_warning(
    *,
    origin: str,
    situation_source: Optional[str],
    skipped: Mapping[str, str],
) -> Optional[str]:
    missing = [
        _BOARD_FIELD_LABEL[f]
        for f in ("down", "distance", "field_position", "quarter", "clock")
        if field_is_not_synced(
            f, origin=origin, situation_source=situation_source, skipped=skipped
        )
    ]
    if not missing:
        return None
    return f"{', '.join(missing)} not synced — confirm the board before trusting this call."


def _field(
    field: str,
    display: str,
    *,
    origin: str,
    situation_source: Optional[str],
    skipped: Mapping[str, str],
) -> HonestField:
    if field_is_not_synced(
        field, origin=origin, situation_source=situation_source, skipped=skipped
    ):
        reason = skipped.get(field) or "no_situation_source"
        return HonestField(False, NOT_SYNCED_TEXT, skip_reason_caption(reason))
    return HonestField(True, display)


def possession_display_text(*, possession: Optional[str]) -> str:
    if possession_is_unset(possession):
        return UNKNOWN_POSSESSION_TEXT
    if possession_is_opponent(possession):
        return "Opponent ball"
    return "Our ball"


def honesty_from_session(
    session: Mapping[str, Any],
    *,
    possession: Optional[str],
    down: int,
    distance: int,
    territory: str,
    yardline: int,
    own_timeouts: int,
    opp_timeouts: int,
    period: int = 1,
    seconds_in_quarter: int = 15 * 60,
) -> SituationHonesty:
    from playcaller.streamlit_state.keys import LIVE_FEED_LAST_AUDIT, LIVE_FEED_LAST_ORIGIN

    audit = session.get(LIVE_FEED_LAST_AUDIT)
    origin = str(session.get(LIVE_FEED_LAST_ORIGIN) or "")
    src = None
    if isinstance(audit, Mapping):
        raw_src = audit.get("situation_source")
        src = str(raw_src).strip() if raw_src else None
        if src == "":
            src = None
    return build_situation_honesty(
        origin=origin,
        situation_source=src,
        skipped=skipped_situation_reasons(audit),
        possession=possession,
        down=down,
        distance=distance,
        territory=territory,
        yardline=yardline,
        own_timeouts=own_timeouts,
        opp_timeouts=opp_timeouts,
        period=period,
        seconds_in_quarter=seconds_in_quarter,
    )


def build_situation_honesty(
    *,
    origin: str,
    situation_source: Optional[str],
    skipped: Mapping[str, str],
    possession: Optional[str],
    down: int,
    distance: int,
    territory: str,
    yardline: int,
    own_timeouts: int,
    opp_timeouts: int,
    period: int = 1,
    seconds_in_quarter: int = 15 * 60,
) -> SituationHonesty:
    src = str(situation_source).strip() if situation_source else None
    down_f = _field(
        "down",
        str(int(down)),
        origin=origin,
        situation_source=src,
        skipped=skipped,
    )
    dist_f = _field(
        "distance",
        str(int(distance)),
        origin=origin,
        situation_source=src,
        skipped=skipped,
    )
    spot = format_ball_spot(territory=territory, yardline=int(yardline))
    field_f = _field(
        "field_position",
        spot,
        origin=origin,
        situation_source=src,
        skipped=skipped,
    )
    poss_f = _field(
        "possession",
        possession_display_text(possession=possession),
        origin=origin,
        situation_source=src,
        skipped=skipped,
    )
    own_f = _field(
        "own_timeouts",
        str(int(own_timeouts)),
        origin=origin,
        situation_source=src,
        skipped=skipped,
    )
    opp_f = _field(
        "opp_timeouts",
        str(int(opp_timeouts)),
        origin=origin,
        situation_source=src,
        skipped=skipped,
    )
    sec = max(0, int(seconds_in_quarter))
    m, s = divmod(sec, 60)
    quarter_f = _field(
        "quarter",
        period_display_label(int(period)),
        origin=origin,
        situation_source=src,
        skipped=skipped,
    )
    clock_f = _field(
        "clock",
        f"{m}:{s:02d} left",
        origin=origin,
        situation_source=src,
        skipped=skipped,
    )
    return SituationHonesty(
        source_chip=situation_source_chip_label(origin=origin, situation_source=src),
        down=down_f,
        distance=dist_f,
        field_position=field_f,
        possession=poss_f,
        own_timeouts=own_f,
        opp_timeouts=opp_f,
        quarter=quarter_f,
        clock=clock_f,
        generate_blocked_reason=generate_blocked_reason_for_possession(possession),
        unsynced_board_warning=unsynced_board_warning(
            origin=origin, situation_source=src, skipped=skipped
        ),
    )


def honest_field_html(field: HonestField) -> str:
    if field.synced:
        return html.escape(field.text)
    title = html.escape(field.reason, quote=True) if field.reason else ""
    title_attr = f' title="{title}"' if title else ""
    return (
        f'<span style="color:#64748b;font-weight:500"{title_attr}>'
        f"{html.escape(NOT_SYNCED_TEXT)}</span>"
    )


def down_distance_html(honesty: SituationHonesty) -> str:
    if honesty.down.synced and honesty.distance.synced:
        return html.escape(f"{honesty.down.text}&{honesty.distance.text}")
    return f"{honest_field_html(honesty.down)}&{honest_field_html(honesty.distance)}"


def timeouts_html(honesty: SituationHonesty) -> str:
    return f"{honest_field_html(honesty.own_timeouts)}–{honest_field_html(honesty.opp_timeouts)}"


def source_chip_html(label: str) -> str:
    return (
        '<span style="display:inline-block;padding:2px 8px;border-radius:999px;'
        "border:1px solid #475569;color:#cbd5e1;font-size:0.72rem;font-weight:600;"
        f'letter-spacing:0.04em">{html.escape(label)}</span>'
    )


def clock_phrase_from_honesty(honesty: SituationHonesty) -> str:
    q = honesty.quarter.text if honesty.quarter.synced else NOT_SYNCED_TEXT
    c = honesty.clock.text if honesty.clock.synced else NOT_SYNCED_TEXT
    return f"{q} · {c}"


def clock_line_html(honesty: SituationHonesty) -> str:
    return f"{honest_field_html(honesty.quarter)} · {honest_field_html(honesty.clock)}"


def honest_summary_line(
    *,
    clock_phrase: str | None = None,
    our_score: int,
    their_score: int,
    honesty: SituationHonesty,
) -> str:
    clock = clock_phrase if clock_phrase is not None else clock_phrase_from_honesty(honesty)
    ball = honesty.field_position.text if honesty.field_position.synced else NOT_SYNCED_TEXT
    if honesty.down.synced and honesty.distance.synced:
        dd = format_down_distance(int(honesty.down.text), int(honesty.distance.text))
    elif not honesty.down.synced and not honesty.distance.synced:
        dd = NOT_SYNCED_TEXT
    else:
        dpart = honesty.down.text if honesty.down.synced else NOT_SYNCED_TEXT
        npart = honesty.distance.text if honesty.distance.synced else NOT_SYNCED_TEXT
        dd = f"{dpart} & {npart}" if honesty.down.synced else f"{NOT_SYNCED_TEXT} & {npart}"
    return (
        f"{clock} · Ball on {ball} · {int(our_score)}–{int(their_score)} · {dd}"
    )
