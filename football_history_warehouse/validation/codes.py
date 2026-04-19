"""
Stable validation ``code`` strings (do not rename casually — operators and jobs key off them).
"""

# Identity / graph integrity (usually fatal)
MISSING_GAME_IDENTITY = "missing_game_identity"
TEAM_IDENTITY_CONFLICT = "team_identity_conflict"
DRIVE_GAME_MISMATCH = "drive_game_mismatch"
PLAY_GAME_MISMATCH = "play_game_mismatch"
PLAY_DRIVE_UNKNOWN = "play_drive_unknown"
OFFENSE_DEFENSE_SAME_TEAM = "offense_defense_same_team"

# Ordering
SEQUENCE_DUPLICATE = "sequence_duplicate"
SEQUENCE_NOT_SORTED = "sequence_not_sorted"
SEQUENCE_GAP = "sequence_gap"

# Situation / field (fatal if outside hard bounds; warnings if suspicious)
DOWN_OUT_OF_RANGE = "down_out_of_range"
DISTANCE_OUT_OF_RANGE = "distance_out_of_range"
YARDS_TO_GOAL_OUT_OF_RANGE = "yards_to_goal_out_of_range"
CLOCK_OUT_OF_RANGE = "clock_out_of_range"

SITUATION_INCOMPLETE = "situation_incomplete"
SITUATION_SPARSE_SCRIMMAGE = "situation_sparse_scrimmage"
PERIOD_CLOCK_MISMATCH = "period_clock_mismatch"
CLOCK_EXCEEDS_REGULATION_QUARTER = "clock_exceeds_regulation_quarter"
PERIOD_EXTREME_OT = "period_extreme_ot"

FIELD_POSITION_SUSPICIOUS = "field_position_suspicious"
