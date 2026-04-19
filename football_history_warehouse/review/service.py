"""
Build a :class:`~football_history_warehouse.review.schema.GameReviewPackage` from warehouse rows.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy.orm import Session

from football_history_warehouse.domain.enums import GameStatus, PlayFamily, PlayResultCategory
from football_history_warehouse.query.mappers import drive_from_row, game_from_row, play_from_row
from football_history_warehouse.query.repositories.competition import CompetitionQueryRepository
from football_history_warehouse.review.schema import (
    DriveTimelineEntry,
    GameReviewPackage,
    GameReviewSummary,
    MatchupSummary,
    OutcomeSummary,
    PlayTimelineEntry,
    ReviewDataQuality,
    ScoreBlock,
    SituationalBreakdown,
    TeamSideSnapshot,
    TendencyByTeam,
    TendencySummary,
)
from football_history_warehouse.storage.database.models import LeagueRow, SeasonRow, TeamRow


def _team_label(session: Session, team_id: str) -> str:
    row = session.get(TeamRow, team_id)
    if row is None:
        return team_id
    if row.abbreviation:
        return row.abbreviation
    return row.full_name


def _team_snapshot(session: Session, team_id: str, role: Literal["home", "away"]) -> TeamSideSnapshot:
    row = session.get(TeamRow, team_id)
    if row is None:
        return TeamSideSnapshot(team_id=team_id, role=role, full_name=team_id)
    return TeamSideSnapshot(
        team_id=team_id,
        role=role,
        full_name=row.full_name,
        abbreviation=row.abbreviation,
        nickname=row.nickname,
    )


def _is_explosive(play_family: str, yards_gained: int | None) -> bool:
    if yards_gained is None:
        return False
    try:
        pf = PlayFamily(play_family)
    except ValueError:
        return False
    if pf == PlayFamily.PASS and yards_gained >= 15:
        return True
    if pf == PlayFamily.RUN and yards_gained >= 10:
        return True
    return False


def build_game_review_package(
    session: Session,
    game_id: str,
    *,
    max_plays: int = 3500,
) -> GameReviewPackage | None:
    """
    Load one game and assemble a review package. Returns ``None`` if the game does not exist.

    Uses only warehouse tables available today (games, teams, leagues, seasons, drives, plays).
    """
    repo = CompetitionQueryRepository(session)
    game_row = repo.get_game_row(game_id)
    if game_row is None:
        return None

    game = game_from_row(game_row)
    home_id = str(game.home_team_id)
    away_id = str(game.away_team_id)

    league_row = session.get(LeagueRow, str(game.league_id))
    season_row = session.get(SeasonRow, str(game.season_id))

    matchup = MatchupSummary(
        home=_team_snapshot(session, home_id, "home"),
        away=_team_snapshot(session, away_id, "away"),
        league_id=str(game.league_id),
        league_name=league_row.name if league_row else None,
        season_id=str(game.season_id),
        season_year_label=season_row.year_label if season_row else None,
    )

    status = game.status
    score = ScoreBlock(
        home_points=game.home_score_final,
        away_points=game.away_score_final,
        is_final_on_record=(
            status == GameStatus.FINAL
            and game.home_score_final is not None
            and game.away_score_final is not None
        ),
    )

    summary = GameReviewSummary(
        game_id=game_id,
        status=status.value,
        scheduled_start_utc=game.scheduled_start_utc,
        regulation_period_count=game.regulation_period_count,
        overtime_periods_played=game.overtime_periods_played,
        neutral_site=game.neutral_site,
        venue_id=str(game.venue_id) if game.venue_id else None,
    )

    drive_rows = repo.fetch_drive_rows_for_game(game_id)
    drives = tuple(drive_from_row(r) for r in drive_rows)

    play_rows = repo.fetch_all_play_rows_for_game(game_id, max_plays=max_plays)
    plays = tuple(play_from_row(r) for r in play_rows)
    truncated = len(play_rows) >= max_plays

    plays_by_drive: Counter[str] = Counter()
    for p in plays:
        if p.drive_id:
            plays_by_drive[str(p.drive_id)] += 1

    drive_timeline: list[DriveTimelineEntry] = []
    for d in drives:
        did = str(d.drive_id)
        drive_timeline.append(
            DriveTimelineEntry(
                drive_id=did,
                drive_order=d.drive_order,
                offense_team_id=str(d.offense_team_id),
                defense_team_id=str(d.defense_team_id),
                offense_display=_team_label(session, str(d.offense_team_id)),
                defense_display=_team_label(session, str(d.defense_team_id)),
                result_bucket=d.result_bucket.value if d.result_bucket else None,
                net_yards=d.net_yards,
                play_count=plays_by_drive.get(did, 0),
                start_period=d.start_period,
                end_period=d.end_period,
            )
        )

    team_labels = {home_id: _team_label(session, home_id), away_id: _team_label(session, away_id)}

    play_timeline: list[PlayTimelineEntry] = []
    for p in plays:
        oid = str(p.offense_team_id)
        play_timeline.append(
            PlayTimelineEntry(
                play_id=str(p.play_id),
                sequence_in_game=p.sequence_in_game,
                drive_id=str(p.drive_id) if p.drive_id else None,
                period=p.period,
                clock_seconds_remaining_in_period=p.clock_seconds_remaining_in_period,
                down=p.down,
                distance=p.distance,
                yards_to_goal_line=p.yards_to_goal_line,
                offense_team_id=oid,
                defense_team_id=str(p.defense_team_id),
                offense_display=team_labels.get(oid, _team_label(session, oid)),
                play_family=p.play_family.value,
                result_category=p.outcome.result_category.value,
                yards_gained=p.yards_gained,
                is_touchdown=p.outcome.is_touchdown,
                is_turnover=p.outcome.is_turnover,
                is_explosive=_is_explosive(p.play_family.value, p.yards_gained),
                description_text=p.description_text,
            )
        )

    # Tendencies: counts by offense team × play family
    family_by_offense: dict[str, Counter[str]] = defaultdict(Counter)
    for p in plays:
        oid = str(p.offense_team_id)
        family_by_offense[oid][p.play_family.value] += 1

    tendency_rows: list[TendencyByTeam] = []
    ordered_ids = [home_id, away_id] + sorted(
        tid for tid in family_by_offense if tid not in (home_id, away_id)
    )
    seen: set[str] = set()
    for tid in ordered_ids:
        if tid in seen:
            continue
        seen.add(tid)
        c = family_by_offense.get(tid) or Counter()
        tendency_rows.append(
            TendencyByTeam(
                team_id=tid,
                team_display=team_labels.get(tid, _team_label(session, tid)),
                total_plays=sum(c.values()),
                play_family_counts=dict(c),
            )
        )

    # Outcomes
    rc_counts: Counter[str] = Counter(p.outcome.result_category.value for p in plays)
    turnovers = sum(1 for p in plays if p.outcome.is_turnover is True)
    tds = sum(1 for p in plays if p.outcome.is_touchdown is True)
    sacks = sum(1 for p in plays if p.outcome.result_category == PlayResultCategory.SACK)
    penalties = sum(1 for p in plays if p.flag_penalty)

    rz = third = fourth = two_min = short = gtg = 0
    for p in plays:
        ytg = p.yards_to_goal_line
        if ytg is not None:
            if ytg <= 20:
                rz += 1
            if ytg <= 10:
                gtg += 1
        if p.down == 3:
            third += 1
        elif p.down == 4:
            fourth += 1
        if p.clock_seconds_remaining_in_period is not None and p.clock_seconds_remaining_in_period <= 120:
            two_min += 1
        if p.distance is not None and 1 <= p.distance <= 3:
            short += 1

    situ = SituationalBreakdown(
        red_zone_plays=rz,
        third_down_plays=third,
        fourth_down_plays=fourth,
        two_minute_drill_plays=two_min,
        short_yardage_plays=short,
        goal_to_go_plays=gtg,
    )

    return GameReviewPackage(
        schema_version="1",
        game_id=game_id,
        generated_at_utc=datetime.now(timezone.utc),
        summary=summary,
        matchup=matchup,
        score=score,
        drive_timeline=tuple(drive_timeline),
        play_timeline=tuple(play_timeline),
        tendencies=TendencySummary(by_offense_team=tuple(tendency_rows)),
        outcomes=OutcomeSummary(
            result_category_counts=dict(rc_counts),
            total_turnovers=turnovers,
            total_touchdowns_scored=tds,
            sacks=sacks,
            penalties_flagged=penalties,
        ),
        situational=situ,
        data_quality=ReviewDataQuality(
            play_rows_loaded=len(play_rows),
            play_timeline_truncated=truncated,
        ),
    )
