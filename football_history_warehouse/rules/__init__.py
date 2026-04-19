"""
League-aware rules configuration (not operational ``config``).

**Exports:** profile model, registry resolution, adapter protocol, built-in keys.

Normalization and query code should resolve :class:`LeagueRuleProfile` once per
batch or game context, then thread ``profile`` / :class:`LeagueNormalizationAdapter`
instead of branching on league display names.
"""

from __future__ import annotations

from football_history_warehouse.rules.adapters import (
    DefaultLeagueNormalizationAdapter,
    LeagueNormalizationAdapter,
)
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
from football_history_warehouse.rules.registry import (
    get_profile,
    normalization_adapter_for_league,
    normalization_adapter_for_profile,
    register_profile,
    registered_profile_keys,
    resolve_rule_profile,
    supported_league_families,
    try_get_profile,
)

__all__ = [
    "DefaultLeagueNormalizationAdapter",
    "FeedCompletenessBand",
    "FieldConvention",
    "LeagueNormalizationAdapter",
    "LeagueRuleProfile",
    "OvertimeStructure",
    "PROFILE_GENERIC_OTHER",
    "PROFILE_NCAA_FBS",
    "PROFILE_NCAA_FCS",
    "PROFILE_NFL",
    "PROFILE_UFL",
    "SeasonWeekLabeling",
    "get_profile",
    "normalization_adapter_for_league",
    "normalization_adapter_for_profile",
    "register_profile",
    "registered_profile_keys",
    "resolve_rule_profile",
    "supported_league_families",
    "try_get_profile",
]
