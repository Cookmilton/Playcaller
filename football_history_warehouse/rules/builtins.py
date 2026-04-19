"""
Built-in :class:`LeagueRuleProfile` instances for first-class leagues.

Tweak enum values here as rule research solidifies; avoid embedding this data
inside normalization functions.
"""

from __future__ import annotations

from football_history_warehouse.domain.enums import CompetitionTier, LeagueFamily
from football_history_warehouse.rules.enums import (
    FeedCompletenessBand,
    FieldConvention,
    OvertimeStructure,
    SeasonWeekLabeling,
)
from football_history_warehouse.rules.keys import (
    PROFILE_GENERIC_OTHER,
    PROFILE_NCAA_FBS,
    PROFILE_NCAA_FCS,
    PROFILE_NFL,
    PROFILE_UFL,
)
from football_history_warehouse.rules.profile import LeagueRuleProfile


def nfl_profile() -> LeagueRuleProfile:
    return LeagueRuleProfile(
        profile_key=PROFILE_NFL,
        display_name="National Football League",
        family=LeagueFamily.NFL,
        default_competition_tier=CompetitionTier.REGULAR,
        regulation_period_count=4,
        overtime_structure=OvertimeStructure.NFL_MODIFIED_SUDDEN_DEATH,
        field_convention=FieldConvention.NFL_STANDARD,
        season_week_labeling=SeasonWeekLabeling.NFL_STYLE_REGULAR_POST,
        feed_completeness=FeedCompletenessBand.FULL_PBP_TYPICAL,
        league_metadata={},
    )


def ncaa_fbs_profile() -> LeagueRuleProfile:
    return LeagueRuleProfile(
        profile_key=PROFILE_NCAA_FBS,
        display_name="NCAA Division I FBS",
        family=LeagueFamily.NCAA_FBS,
        default_competition_tier=CompetitionTier.REGULAR,
        regulation_period_count=4,
        overtime_structure=OvertimeStructure.NCAA_TWO_POSSESSION_MINIMUM,
        field_convention=FieldConvention.NCAA_COLLEGIATE,
        season_week_labeling=SeasonWeekLabeling.NCAA_CONFERENCE_AND_BOWL,
        feed_completeness=FeedCompletenessBand.VARIABLE_BY_PROGRAM,
        league_metadata={},
    )


def ncaa_fcs_profile() -> LeagueRuleProfile:
    return LeagueRuleProfile(
        profile_key=PROFILE_NCAA_FCS,
        display_name="NCAA Division I FCS",
        family=LeagueFamily.NCAA_FCS,
        default_competition_tier=CompetitionTier.REGULAR,
        regulation_period_count=4,
        overtime_structure=OvertimeStructure.NCAA_TWO_POSSESSION_MINIMUM,
        field_convention=FieldConvention.NCAA_COLLEGIATE,
        season_week_labeling=SeasonWeekLabeling.NCAA_CONFERENCE_AND_BOWL,
        feed_completeness=FeedCompletenessBand.VARIABLE_BY_PROGRAM,
        league_metadata={},
    )


def ufl_profile() -> LeagueRuleProfile:
    return LeagueRuleProfile(
        profile_key=PROFILE_UFL,
        display_name="United Football League",
        family=LeagueFamily.UFL,
        default_competition_tier=CompetitionTier.SPRING,
        regulation_period_count=4,
        overtime_structure=OvertimeStructure.PRO_GENERIC_SUDDEN_DEATH,
        field_convention=FieldConvention.UFL_ALIGNS_PRO,
        season_week_labeling=SeasonWeekLabeling.SPRING_LEAGUE_ROUND_ROBIN,
        feed_completeness=FeedCompletenessBand.FULL_PBP_TYPICAL,
        league_metadata={},
    )


def generic_other_profile() -> LeagueRuleProfile:
    return LeagueRuleProfile(
        profile_key=PROFILE_GENERIC_OTHER,
        display_name="Generic / unknown league",
        family=LeagueFamily.OTHER,
        default_competition_tier=CompetitionTier.UNKNOWN,
        regulation_period_count=4,
        overtime_structure=OvertimeStructure.UNKNOWN,
        field_convention=FieldConvention.UNKNOWN,
        season_week_labeling=SeasonWeekLabeling.UNKNOWN,
        feed_completeness=FeedCompletenessBand.UNKNOWN,
        league_metadata={},
    )


def all_builtin_profiles() -> tuple[LeagueRuleProfile, ...]:
    return (
        nfl_profile(),
        ncaa_fbs_profile(),
        ncaa_fcs_profile(),
        ufl_profile(),
        generic_other_profile(),
    )
