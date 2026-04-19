"""
League-specific normalization hooks — interfaces + default pass-through.

Downstream ingest code should depend on :class:`LeagueNormalizationAdapter`,
not on ``if league == NFL`` scattered across modules. Swap the adapter when a
league needs custom logic; the default preserves ``profile`` for inspection.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from football_history_warehouse.rules.profile import LeagueRuleProfile


@runtime_checkable
class LeagueNormalizationAdapter(Protocol):
    """
    Narrow interface for future period/clock/yardline transforms.

    Methods stay small; add new operations when a second league needs them
    instead of central mega-functions.
    """

    @property
    def profile(self) -> LeagueRuleProfile: ...

    def canonical_period_index(self, raw_period_one_based: int | None) -> int | None:
        """Map vendor period numbering to warehouse 1-based period index."""
        ...

    def attach_penalty_yards_policy(self) -> str:
        """
        Symbolic policy key for how penalty yards attach to plays.

        Normalization will interpret documented keys (e.g. ``attach_to_foul_play``).
        """
        ...

    def soft_fields_for_incomplete_feed(self) -> frozenset[str]:
        """Canonical Play field names allowed to stay null for this league's typical feeds."""
        ...


class DefaultLeagueNormalizationAdapter:
    """
    Pass-through adapter: exposes profile and conservative defaults.

    Subclass or replace with league-specific implementations when behavior
    diverges; register overrides in ``registry`` if you need non-default
    selection by ``profile_key``.
    """

    __slots__ = ("_profile",)

    def __init__(self, profile: LeagueRuleProfile) -> None:
        self._profile = profile

    @property
    def profile(self) -> LeagueRuleProfile:
        return self._profile

    def canonical_period_index(self, raw_period_one_based: int | None) -> int | None:
        return raw_period_one_based

    def attach_penalty_yards_policy(self) -> str:
        return "unspecified_pass_through"

    def soft_fields_for_incomplete_feed(self) -> frozenset[str]:
        return frozenset()
