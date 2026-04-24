"""
Named tuning knobs for drive grades and game-story thresholds.

Coaches adjust weights here — avoid scattering magic numbers in analytics code.
"""

from __future__ import annotations

# --- Letter grade buckets (total score 0–100, inclusive) -----------------------
GRADE_A_MIN = 85
GRADE_B_MIN = 70
GRADE_C_MIN = 55
GRADE_D_MIN = 40
# F: 0–39

# --- Outcome component (0–40) — possessing-team quality ----------------------
# Offense perspective: higher = better possession for the team with the ball.
OUTCOME_WEIGHT_MAX = 40

OUTCOME_POSSESSING_TOUCHDOWN = 40
OUTCOME_POSSESSING_FIELD_GOAL = 25
OUTCOME_POSSESSING_END_OF_HALF = 15
OUTCOME_POSSESSING_PUNT_OPEN_FIELD = 12
OUTCOME_POSSESSING_PUNT_BACKED_UP = 8
OUTCOME_POSSESSING_TURNOVER_ON_DOWNS = 4
OUTCOME_POSSESSING_TURNOVER = 0
OUTCOME_POSSESSING_FIELD_GOAL_MISS = 4
OUTCOME_POSSESSING_SAFETY = -5
OUTCOME_POSSESSING_UNKNOWN_NEUTRAL = 10

# ESPN start.yardLine: high values ≈ backed-up own territory (see reconciler tests).
PUNT_BACKED_UP_YARD_LINE_MIN = 75

# Defense perspective uses: min(40, max(0, OUTCOME_WEIGHT_MAX - possessing_quality))
# Special case: defense scores safety → treat as best stop (full outcome credit).

# --- Efficiency component (0–30) ----------------------------------------------
EFFICIENCY_WEIGHT_MAX = 30

EFFICIENCY_YPP_GREAT_MIN = 6.5  # -> 30 pts
EFFICIENCY_YPP_GOOD_MIN = 5.0  # -> 22
EFFICIENCY_YPP_OK_MIN = 3.5  # -> 15
EFFICIENCY_YPP_WEAK_MIN = 2.0  # -> 8
# below 2.0 -> 0

EFFICIENCY_POINTS_TIER_HIGH = 30
EFFICIENCY_POINTS_TIER_MID_HIGH = 22
EFFICIENCY_POINTS_TIER_MID = 15
EFFICIENCY_POINTS_TIER_LOW = 8
EFFICIENCY_POINTS_TIER_MIN = 0

# --- Situational component (0–20) -------------------------------------------
SITUATIONAL_WEIGHT_MAX = 20

SITUATIONAL_THIRD_CONVERSION_POINTS_EACH = 5
SITUATIONAL_THIRD_CONVERSION_CAP = 10
SITUATIONAL_NO_NEGATIVE_EXPLOSIVE_BONUS = 5
SITUATIONAL_NO_DRIVE_KILLER_PENALTY_BONUS = 5

# Negative play: sack or substantial TFL.
NEGATIVE_PLAY_YARDS_THRESHOLD = -3

# --- Model agreement (0–10) ---------------------------------------------------
MODEL_WEIGHT_MAX = 10
MODEL_AGREE_TIER_HIGH = 0.70  # >= -> 10 pts
MODEL_AGREE_TIER_MID = 0.50  # >= -> 6 pts
# else -> 2
MODEL_AGREE_NEUTRAL_POINTS = 6  # no scorable replay rows

MODEL_CONFIDENCE_HIGH = 0.70  # drive_failure callouts

# --- Game story: sample gates -------------------------------------------------
GAME_STORY_MIN_DRIVES_FOR_HALF_SPLIT = 10
GAME_STORY_MIN_DRIVES_TOTAL = 8
GAME_STORY_MIN_THIRD_ATTEMPTS = 4
GAME_STORY_MIN_PLAYS_PER_DOWN_BUCKET = 4
GAME_STORY_MIN_STREAK = 3
GAME_STORY_MIN_RED_ZONE_TRIPS = 3
GAME_STORY_MAX_BULLET_CHARS = 80
GAME_STORY_TOP_BULLETS = 5
GAME_STORY_CANDIDATE_POOL = 12

GAME_STORY_MIN_EXPLOSIVES_TO_MENTION = 3
GAME_STORY_MIN_NEGATIVES_TO_MENTION = 3

# Significance bands (higher = surfaced first)
SIGNIFICANCE_SCORING_RUN = 92
SIGNIFICANCE_SCORING_DROUGHT = 88
SIGNIFICANCE_RED_ZONE = 80
SIGNIFICANCE_STREAK_FAIL = 78
SIGNIFICANCE_MODEL_LOW_DRIVE = 72
SIGNIFICANCE_EFFICIENCY_DOWN = 68
SIGNIFICANCE_THIRD_DOWN = 65
SIGNIFICANCE_EXPLOSIVE = 62
SIGNIFICANCE_NEGATIVE = 60
SIGNIFICANCE_HALF_SPLIT = 58
SIGNIFICANCE_HIGH_CONF_AGREE = 55

# --- Drive failure ------------------------------------------------------------
DRIVE_FAILURE_MAX_BULLETS = 3
