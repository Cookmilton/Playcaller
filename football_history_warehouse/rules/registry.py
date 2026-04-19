"""
Profile registry and resolution — single lookup surface for league behavior.

**How to use (normalization / query):**

1. Load or build canonical :class:`~football_history_warehouse.domain.organizations.League`.
2. Call :func:`resolve_rule_profile` — never branch on ``league.name`` strings.
3. Obtain :class:`~football_history_warehouse.rules.adapters.LeagueNormalizationAdapter`
   via :func:`normalization_adapter_for_profile` when transforming vendor rows.
4. Consult ``profile`` fields (OT, field convention, completeness) for policy
   documentation and tests; put *code* that differs by league on adapter
   subclasses or small strategy modules keyed by ``profile_key``.

This avoids duplicating ``if nfl elif college`` across parsers: one resolution
path, one profile object, optional adapter override per ``profile_key``.
"""

from __future__ import annotations

from collections.abc import Callable

from football_history_warehouse.domain.enums import LeagueFamily
from football_history_warehouse.domain.identifiers import LeagueId
from football_history_warehouse.domain.organizations import League
from football_history_warehouse.rules.adapters import DefaultLeagueNormalizationAdapter, LeagueNormalizationAdapter
from football_history_warehouse.rules.builtins import all_builtin_profiles
from football_history_warehouse.rules.keys import (
    PROFILE_GENERIC_OTHER,
    PROFILE_NCAA_FBS,
    PROFILE_NCAA_FCS,
    PROFILE_NFL,
    PROFILE_UFL,
)
from football_history_warehouse.rules.profile import LeagueRuleProfile

_PROFILES: dict[str, LeagueRuleProfile] = {}
_FAMILY_DEFAULT_KEY: dict[LeagueFamily, str] = {
    LeagueFamily.NFL: PROFILE_NFL,
    LeagueFamily.NCAA_FBS: PROFILE_NCAA_FBS,
    LeagueFamily.NCAA_FCS: PROFILE_NCAA_FCS,
    LeagueFamily.UFL: PROFILE_UFL,
    LeagueFamily.OTHER: PROFILE_GENERIC_OTHER,
}


def _ensure_builtins_loaded() -> None:
    """Merge built-in profiles without clobbering custom registrations."""
    for p in all_builtin_profiles():
        _PROFILES.setdefault(p.profile_key, p)


def register_profile(profile: LeagueRuleProfile, *, overwrite: bool = False) -> None:
    """Register or replace a profile (tests, experimental leagues)."""
    _ensure_builtins_loaded()
    if not overwrite and profile.profile_key in _PROFILES:
        raise ValueError(f"profile_key already registered: {profile.profile_key!r}")
    _PROFILES[profile.profile_key] = profile


def registered_profile_keys() -> frozenset[str]:
    """All keys currently in the registry."""
    _ensure_builtins_loaded()
    return frozenset(_PROFILES)


def get_profile(profile_key: str) -> LeagueRuleProfile:
    """Return a profile by key or raise ``KeyError``."""
    _ensure_builtins_loaded()
    return _PROFILES[profile_key]


def try_get_profile(profile_key: str) -> LeagueRuleProfile | None:
    _ensure_builtins_loaded()
    return _PROFILES.get(profile_key)


def resolve_rule_profile(
    *,
    league: League | None = None,
    league_id: LeagueId | None = None,
    family: LeagueFamily | None = None,
    rules_profile_key: str | None = None,
) -> LeagueRuleProfile:
    """
    Resolve the effective :class:`LeagueRuleProfile`.

    Precedence: explicit ``rules_profile_key`` → ``league.rules_profile_key`` →
    default for ``league.family`` / ``family`` → :data:`PROFILE_GENERIC_OTHER`.

    ``league_id`` is accepted for logging/tracing only; resolution uses keys and family.
    """
    _ensure_builtins_loaded()
    _ = league_id  # reserved for future diagnostics (e.g. structured logging)
    key: str | None = rules_profile_key
    fam: LeagueFamily | None = family

    if league is not None:
        if key is None:
            key = league.rules_profile_key
        if fam is None:
            fam = league.family

    if key:
        hit = _PROFILES.get(key)
        if hit is not None:
            return hit

    if fam is not None:
        fallback_key = _FAMILY_DEFAULT_KEY.get(fam, PROFILE_GENERIC_OTHER)
        return _PROFILES[fallback_key]

    return _PROFILES[PROFILE_GENERIC_OTHER]


def normalization_adapter_for_profile(
    profile: LeagueRuleProfile,
    *,
    factory: Callable[[LeagueRuleProfile], LeagueNormalizationAdapter] | None = None,
) -> LeagueNormalizationAdapter:
    """
    Construct the adapter for ``profile``.

    Pass ``factory`` for custom behavior (e.g. ``NCAAAdapter``). A small
    ``profile_key → factory`` map can live here later without changing callers.
    """
    if factory is not None:
        return factory(profile)
    return DefaultLeagueNormalizationAdapter(profile)


def normalization_adapter_for_league(
    league: League,
    *,
    factory: Callable[[LeagueRuleProfile], LeagueNormalizationAdapter] | None = None,
) -> LeagueNormalizationAdapter:
    profile = resolve_rule_profile(league=league)
    return normalization_adapter_for_profile(profile, factory=factory)


def supported_league_families() -> frozenset[LeagueFamily]:
    """Families that have a default profile mapping in this registry."""
    return frozenset(_FAMILY_DEFAULT_KEY)
