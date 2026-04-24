"""Sample and skew gates for pattern surfacing (tunable without touching logic)."""

from __future__ import annotations

# Minimum offensive snapshots in a slice for a generic tendency line
MIN_PLAYS_PATTERN = 4

# Red zone–specific patterns (trips / snaps inside opp 20)
MIN_RED_ZONE_ATTEMPTS = 3

# “Distinctive” run/pass or pass-rate skew
SKEW_HIGH = 0.70
SKEW_LOW = 0.30

# Field / situation definitions
SECOND_LONG_MIN_DISTANCE = 7
BACKED_UP_MAX_OWN_YARDLINE = 10
RED_ZONE_MAX_OPP_YARDLINE = 20
TWO_MINUTE_MAX_SECONDS = 120

# 1st & 10 heuristic: first down with “and long” distance typical of standard 1st & 10
FIRST_AND_TEN_MIN_DISTANCE = 8
FIRST_AND_TEN_MAX_DISTANCE = 10

# Next-play “2nd & medium” after a 1st & 10 snap
SECOND_MEDIUM_MIN = 4
SECOND_MEDIUM_MAX = 7

# Top mistakes: minimum total severity to surface (honest silence below this)
MIN_TOP_MISTAKE_SEVERITY = 40

# Model confidence tiers for mistake weighting (aligned with coaching copy)
MODEL_CONF_HIGH = 0.70
MODEL_CONF_MID = 0.50
