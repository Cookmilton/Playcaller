"""League rule profile registry and adapter wiring."""

from __future__ import annotations

from datetime import UTC, datetime

from football_history_warehouse.domain import League
from football_history_warehouse.domain.enums import CompetitionTier, LeagueFamily
from football_history_warehouse.domain.identifiers import LeagueId
from football_history_warehouse.rules import (
    DefaultLeagueNormalizationAdapter,
    LeagueRuleProfile,
    PROFILE_NFL,
    PROFILE_UFL,
    get_profile,
    normalization_adapter_for_league,
    normalization_adapter_for_profile,
    register_profile,
    resolve_rule_profile,
)
from football_history_warehouse.rules.enums import OvertimeStructure
from football_history_warehouse.rules.keys import PROFILE_GENERIC_OTHER


def _prov_stub():
    from football_history_warehouse.domain import ProvenanceEntry, SourceMetadata
    from football_history_warehouse.domain.identifiers import ImportJobId

    return (
        ProvenanceEntry(
            import_job_id=ImportJobId("t"),
            source=SourceMetadata(source_system="test", observed_at=datetime.now(tz=UTC)),
            warehouse_written_at=datetime.now(tz=UTC),
        ),
    )


def test_resolve_by_explicit_key() -> None:
    p = resolve_rule_profile(rules_profile_key=PROFILE_NFL)
    assert p.profile_key == PROFILE_NFL
    assert p.overtime_structure == OvertimeStructure.NFL_MODIFIED_SUDDEN_DEATH


def test_resolve_fallback_family() -> None:
    p = resolve_rule_profile(family=LeagueFamily.UFL)
    assert p.profile_key == PROFILE_UFL


def test_resolve_league_rules_profile_key_overrides_family() -> None:
    league = League(
        league_id=LeagueId("x"),
        family=LeagueFamily.OTHER,
        name="Minor league experiment",
        rules_profile_key=PROFILE_NFL,
        provenance=_prov_stub(),
    )
    p = resolve_rule_profile(league=league)
    assert p.profile_key == PROFILE_NFL


def test_unknown_key_falls_back_to_family() -> None:
    league = League(
        league_id=LeagueId("y"),
        family=LeagueFamily.NCAA_FBS,
        name="FBS school",
        rules_profile_key="definitely_missing_key",
        provenance=_prov_stub(),
    )
    p = resolve_rule_profile(league=league)
    assert p.family == LeagueFamily.NCAA_FBS


def test_adapter_factory() -> None:
    profile = get_profile(PROFILE_NFL)

    class Custom(DefaultLeagueNormalizationAdapter):
        def attach_penalty_yards_policy(self) -> str:
            return "nfl_test_policy"

    ad = normalization_adapter_for_profile(profile, factory=Custom)
    assert isinstance(ad, Custom)
    assert ad.attach_penalty_yards_policy() == "nfl_test_policy"


def test_normalization_adapter_for_league() -> None:
    league = League(
        league_id=LeagueId("z"),
        family=LeagueFamily.NFL,
        name="NFL",
        provenance=_prov_stub(),
    )
    ad = normalization_adapter_for_league(league)
    assert isinstance(ad, DefaultLeagueNormalizationAdapter)
    assert ad.profile.profile_key == PROFILE_NFL


def test_register_profile_custom() -> None:
    custom = LeagueRuleProfile(
        profile_key="spring_demo",
        display_name="Demo",
        family=LeagueFamily.OTHER,
        default_competition_tier=CompetitionTier.SPRING,
    )
    register_profile(custom, overwrite=True)
    got = get_profile("spring_demo")
    assert got.display_name == "Demo"


def test_resolve_empty_falls_back_generic() -> None:
    p = resolve_rule_profile()
    assert p.profile_key == PROFILE_GENERIC_OTHER
