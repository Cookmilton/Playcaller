"""
League, season, and team — organizational anchors for all competition data.

**Required vs optional (summary):**
- **League:** ``league_id``, ``family``, ``name`` required; codes and rules
  pointers optional until backfilled.
- **Season:** ``season_id``, ``league_id``, ``year_label`` required; calendar
  bounds optional when unknown.
- **Team:** ``team_id``, ``league_id``, ``full_name`` required; abbreviations
  and conference labels optional for partial catalogs.
"""

from __future__ import annotations

from datetime import date

from pydantic import Field

from football_history_warehouse.domain.base import CanonicalModel
from football_history_warehouse.domain.enums import CompetitionTier, LeagueFamily
from football_history_warehouse.domain.identifiers import LeagueId, SeasonId, TeamId
from football_history_warehouse.domain.provenance import ProvenanceEntry


class League(CanonicalModel):
    """
    A competition authority / rule set namespace (e.g. NFL, NCAA FBS).

    ``league_id`` is warehouse-canonical and stable across seasons. Do not
    encode season or team in this id.
    """

    league_id: LeagueId
    family: LeagueFamily
    name: str = Field(..., min_length=1)
    short_code: str | None = Field(
        default=None,
        description="Short stable code for UI and joins (e.g. NFL, UFL).",
    )
    competition_tier_default: CompetitionTier = Field(
        default=CompetitionTier.UNKNOWN,
        description="Default tier when season does not override.",
    )
    rules_profile_key: str | None = Field(
        default=None,
        description="Key into ``rules`` registry; prefer ``football_history_warehouse.rules.keys`` constants.",
    )
    provenance: tuple[ProvenanceEntry, ...] = Field(
        default_factory=tuple,
        description="One or more entries when data merged from multiple jobs.",
    )


class Season(CanonicalModel):
    """
    A league-scoped season or campaign.

    ``year_label`` is display and index friendly (e.g. ``\"2024\"``,
    ``\"2024-25\"``); do not assume it parses to a single calendar year for
    all leagues.
    """

    season_id: SeasonId
    league_id: LeagueId
    year_label: str = Field(..., min_length=1)
    starts_on: date | None = Field(
        default=None,
        description="League-defined season start when known.",
    )
    ends_on: date | None = Field(
        default=None,
        description="League-defined season end when known.",
    )
    provenance: tuple[ProvenanceEntry, ...] = Field(default_factory=tuple)


class Team(CanonicalModel):
    """
    A franchise or program in league context.

    **College / relocation note:** ``team_id`` should be stable across seasons
    for the same program; conference membership belongs in optional fields
    that may change per season via future ``TeamSeason`` models — not modeled
    here yet to avoid scope creep.
    """

    team_id: TeamId
    league_id: LeagueId
    full_name: str = Field(..., min_length=1)
    abbreviation: str | None = Field(
        default=None,
        description="Often 2–4 letters; may be null in partial imports.",
    )
    nickname: str | None = None
    city: str | None = None
    conference_id: str | None = Field(
        default=None,
        description="Opaque conference key; normalization defines vocabulary.",
    )
    division_id: str | None = Field(
        default=None,
        description="Opaque division key within conference when applicable.",
    )
    provenance: tuple[ProvenanceEntry, ...] = Field(default_factory=tuple)
