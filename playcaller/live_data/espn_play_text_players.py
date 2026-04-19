"""
Conservative ESPN play **text** parsing for player labels when ``participants`` is absent.

Output is display-only; normalization categories come from :mod:`playcaller.live_data.espn_play_normalize`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

# Name shapes seen on NFL summaries: D.Maye, T.J.Watt, Kenneth Walker III
_PAT_NAME = (
    r"(?:"
    r"[A-Z](?:\.[A-Z])+\.[A-Za-z][a-zA-Z'’\-]*|"  # T.J.Watt
    r"[A-Z]\.[A-Za-z][a-zA-Z'’\-]*|"  # D.Maye
    r"(?:[A-Z][a-zA-Z'’\-]*|[A-Z]{2,4})(?:\s+(?:[A-Z][a-zA-Z'’\-]*|[A-Z]{2,4})){1,3}"  # full name + suffix
    r")"
)

_RE_PASS_INCOMPLETE_TO = re.compile(
    rf"(?P<passer>{_PAT_NAME})\s+pass\s+incomplete\b.*?\bto\s+(?P<recv>{_PAT_NAME})\b",
    re.I | re.DOTALL,
)
_RE_PASS_TO = re.compile(
    rf"(?P<passer>{_PAT_NAME})\s+pass\b.*?\bto\s+(?P<recv>{_PAT_NAME})\b",
    re.I | re.DOTALL,
)
_RE_SCRAMBLE = re.compile(rf"(?P<qb>{_PAT_NAME})\s+scrambles\b", re.I)
_RE_SACK = re.compile(
    rf"(?P<passer>{_PAT_NAME})\s+(?:is\s+)?sacked\s+by\s+(?P<def>{_PAT_NAME})\b",
    re.I,
)
_RE_RUSH_DIR = re.compile(
    rf"(?P<r>{_PAT_NAME})\s+(?:right|left|up\s+the\s+middle)\b",
    re.I,
)
_RE_TWO_POINT_PASS = re.compile(
    rf"(?P<passer>{_PAT_NAME})\s+pass\b.*?\bto\s+(?P<recv>{_PAT_NAME})\b.*?(?:two[- ]point|2[- ]pt)",
    re.I | re.DOTALL,
)


@dataclass
class EspnTextPeople:
    passer: str = ""
    receiver: str = ""
    rusher: str = ""
    sacked_by: str = ""
    receiver_role: str = ""
    passer_jersey: str = ""
    receiver_jersey: str = ""
    rusher_jersey: str = ""


def play_text_from_espn_row(play: Mapping[str, Any]) -> str:
    """Same field resolution as legacy ``_play_text`` in normalize (single source of truth)."""
    tx = play.get("text")
    if isinstance(tx, dict):
        return str(tx.get("text") or "")
    if isinstance(tx, str):
        return tx
    return str(play.get("description") or "")


def strip_leading_parenthetical_segments(text: str) -> str:
    """Remove leading '(clock, formation, …)' preambles ESPN often prefixes."""
    s = (text or "").strip()
    while s.startswith("("):
        close = s.find(")")
        if close == -1:
            break
        s = s[close + 1 :].lstrip()
    return s


def _role_and_jersey_from_free_text(text_l: str) -> Tuple[str, str, str]:
    """
    Detect generic phrases like 'to wide receiver #18' (no proper name).
    Returns (receiver_role WR|TE|RB, jersey, "").
    """
    if m := re.search(r"\b(?:wide receiver|wr)\s*#(\d{1,2})\b", text_l):
        return "WR", m.group(1), ""
    if m := re.search(r"\btight end\b.*?\s*#(\d{1,2})\b", text_l):
        return "TE", m.group(1), ""
    if m := re.search(r"\brunning back\b.*?\s*#(\d{1,2})\b", text_l):
        return "RB", m.group(1), ""
    if m := re.search(r"\b(?:wide receiver|wr)\b", text_l) and "pass" in text_l:
        return "WR", "", ""
    if re.search(r"\btight end\b", text_l) and "pass" in text_l:
        return "TE", "", ""
    if re.search(r"\brunning back\b", text_l) and "pass" in text_l:
        return "RB", "", ""
    return "", "", ""


def parse_espn_play_text_players(raw_text: str) -> EspnTextPeople:
    """
    Tier-2 extraction from broadcast-style ``text`` only.

    Prefer empty fields over false positives; do not infer defenders from trailing '(J.Smith)'.
    """
    out = EspnTextPeople()
    text = strip_leading_parenthetical_segments(raw_text)
    if not text.strip():
        return out
    text_l = text.lower()
    if "kneel" in text_l:
        return out
    if "intercept" in text_l:
        return out

    if m := _RE_SACK.search(text):
        out.passer = (m.group("passer") or "").strip()
        out.sacked_by = (m.group("def") or "").strip()
        return out

    if m := _RE_SCRAMBLE.search(text):
        out.passer = (m.group("qb") or "").strip()
        return out

    if m := _RE_PASS_INCOMPLETE_TO.search(text):
        out.passer = (m.group("passer") or "").strip()
        out.receiver = (m.group("recv") or "").strip()
        return out

    if m := _RE_TWO_POINT_PASS.search(text):
        out.passer = (m.group("passer") or "").strip()
        out.receiver = (m.group("recv") or "").strip()
        return out

    if m := _RE_PASS_TO.search(text):
        out.passer = (m.group("passer") or "").strip()
        out.receiver = (m.group("recv") or "").strip()
        return out

    if "pass" in text_l:
        if not out.receiver:
            role, rjer, _ = _role_and_jersey_from_free_text(text_l)
            if role:
                out.receiver_role = role
            if rjer:
                out.receiver_jersey = rjer
        return out

    if m := _RE_RUSH_DIR.search(text):
        out.rusher = (m.group("r") or "").strip()

    return out


def text_people_has_detail(p: EspnTextPeople) -> bool:
    return bool(
        p.passer
        or p.receiver
        or p.rusher
        or p.sacked_by
        or p.receiver_role
        or p.passer_jersey
        or p.receiver_jersey
        or p.rusher_jersey
    )
