"""
Shared numeric and policy constants for the Play Caller app (single import surface).

Wire these gradually into engine, audit, and UI where magic numbers appear today.
"""

from __future__ import annotations

# --- Scoring (NFL-style; PAT/2PT handling is call-site specific) ---
TD_POINTS = 6
FG_POINTS = 3
SAFETY_POINTS = 2
DEFAULT_ASSUMED_PAT_POINTS = 1

# --- Sanity / UI ---
MAX_DRIVE_PLAYS_SANITY = 25

# --- Live ESPN sync (operator-facing latency; not HTTP client timeouts) ---
ESPN_SYNC_AUDIT_TTL_HINT_SECONDS = 30
