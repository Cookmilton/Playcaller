"""
Attach read-only warehouse context to a ``recommend()`` result dict.

**Never** mutates ``scores`` or model selection — advisory JSON only for UI / audit / review.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, Optional

from football_history_warehouse.consumer.client import FootballWarehouseClient
from football_history_warehouse.query.pagination import PageParams
from football_history_warehouse.query.situation.filter import PlaySituationFilter, validate_situation_has_scope

from playcaller.domain import GameContext
from playcaller.game import Game
from playcaller.warehouse.binding import WarehouseBinding, offense_team_id_on_field
from playcaller.warehouse.situation import play_situation_core_from_context

ADVISORY_DISCLAIMER = (
    "Warehouse history is **reference-only** for this build: it does **not** change ranked scores. "
    "Treat counts as exploratory — small imported samples (e.g. a handful of games) are not league truth."
)


def _scope_dict(binding: WarehouseBinding) -> dict[str, Any]:
    return {
        "league_id": binding.league_id,
        "season_id": binding.season_id,
        "game_id": binding.game_id,
    }


def _situation_line(ctx: GameContext, *, possession: str) -> str:
    side = "our offense" if possession == "offense" else "opponent offense"
    return (
        f"{ctx.down}&{ctx.distance} · {ctx.territory} {ctx.yardline} · Q{ctx.quarter} "
        f"· clock {ctx.seconds_remaining}s · score_diff(off-field) via {side}"
    )


def _apply_scope(core: PlaySituationFilter, binding: WarehouseBinding) -> PlaySituationFilter | None:
    """Prefer league+season when both set; else single-game scope."""
    if binding.league_id and binding.season_id:
        return replace(
            core,
            league_id=binding.league_id,
            season_id=binding.season_id,
            game_id=None,
        )
    if binding.game_id:
        return replace(
            core,
            game_id=binding.game_id,
            league_id=None,
            season_id=None,
        )
    if binding.league_id:
        return replace(core, league_id=binding.league_id, season_id=binding.season_id, game_id=None)
    if binding.season_id:
        return replace(core, league_id=None, season_id=binding.season_id, game_id=None)
    return None


def _outcome_summary_dict(client: FootballWarehouseClient, filt: PlaySituationFilter) -> dict[str, Any] | None:
    validate_situation_has_scope(filt)
    summary = client.get_situation_outcome_summary(filt)
    return summary.model_dump(mode="json")


def _tendency_dict(
    client: FootballWarehouseClient, team_id: str, filt: PlaySituationFilter
) -> dict[str, Any] | None:
    validate_situation_has_scope(filt)
    t = client.get_team_tendency_summary(team_id, situation=filt)
    return t.model_dump(mode="json")


def _plays_sample_dict(client: FootballWarehouseClient, filt: PlaySituationFilter, *, limit: int) -> dict[str, Any]:
    validate_situation_has_scope(filt)
    page = client.get_plays_by_situation(filt, page=PageParams(limit=limit, offset=0))
    dumped = page.model_dump(mode="json")
    return dumped


def build_warehouse_advisory_payload(
    client: FootballWarehouseClient,
    ctx: GameContext,
    game: Optional[Game],
    binding: WarehouseBinding,
    *,
    similar_play_limit: int = 12,
) -> dict[str, Any]:
    possession = str(game.possession) if game is not None else "offense"
    core = play_situation_core_from_context(ctx, possession=possession)
    base: dict[str, Any] = {
        "mode": "advisory",
        "enabled": True,
        "disclaimer": ADVISORY_DISCLAIMER,
        "situation_summary": _situation_line(ctx, possession=possession),
        "scope_binding": _scope_dict(binding),
        "scores_were_unchanged": True,
        "outcome_league_season": None,
        "outcome_game": None,
        "offense_team_tendency": None,
        "similar_plays": None,
        "notes": [],
        "errors": [],
    }

    if not binding.has_query_scope():
        base["enabled"] = False
        base["notes"].append(
            "No warehouse scope: set session **warehouse_league_id** + **warehouse_season_id**, "
            "or **warehouse_game_id**, or load an ESPN **Event ID** (maps to ``espn-…``), "
            "or set env vars documented in ``playcaller.warehouse.binding``."
        )
        return base

    scoped = _apply_scope(core, binding)
    if scoped is None:
        base["enabled"] = False
        base["notes"].append("Could not derive a bounded warehouse scope from binding.")
        return base

    try:
        validate_situation_has_scope(scoped)
    except ValueError as exc:
        base["enabled"] = False
        base["errors"].append(str(exc))
        return base

    # --- Outcome: league+season slice when available (broader), plus optional same-game slice ---
    if binding.league_id and binding.season_id:
        try:
            base["outcome_league_season"] = _outcome_summary_dict(client, scoped)
        except Exception as exc:
            base["errors"].append(f"outcome_league_season: {exc}")

    if binding.game_id:
        game_filt = replace(
            core,
            game_id=binding.game_id,
            league_id=None,
            season_id=None,
        )
        try:
            validate_situation_has_scope(game_filt)
            base["outcome_game"] = _outcome_summary_dict(client, game_filt)
        except Exception as exc:
            base["errors"].append(f"outcome_game: {exc}")

    if base["outcome_league_season"] is None and base["outcome_game"] is None:
        try:
            base["outcome_league_season"] = _outcome_summary_dict(client, scoped)
        except Exception as exc:
            base["errors"].append(f"outcome_scoped: {exc}")

    # --- Team tendency (offense on field) ---
    off_id = offense_team_id_on_field(possession=possession, binding=binding)
    if off_id:
        try:
            base["offense_team_tendency"] = _tendency_dict(client, off_id, scoped)
        except ValueError as exc:
            base["notes"].append(f"Team tendency skipped: {exc}")
        except Exception as exc:
            base["errors"].append(f"team_tendency: {exc}")
    else:
        base["notes"].append(
            "Team tendency skipped — set **warehouse_coached_team_id** and **warehouse_opponent_team_id** "
            "for opponent possessions."
        )

    # --- Similar plays (same scope as ``scoped``) ---
    try:
        lim = max(1, min(50, int(similar_play_limit)))
        base["similar_plays"] = _plays_sample_dict(client, scoped, limit=lim)
    except Exception as exc:
        base["errors"].append(f"similar_plays: {exc}")

    return base


def attach_warehouse_advisory_to_result(
    result: Dict[str, Any],
    game: Optional[Game],
    client: Optional[FootballWarehouseClient],
    binding: Optional[WarehouseBinding],
    *,
    similar_play_limit: int = 12,
) -> None:
    """
    Mutates ``result`` in place: sets ``warehouse_advisory`` (always present when called).

    When ``client`` or ``binding`` is missing, records a disabled payload — never raises.
    """
    if client is None:
        result["warehouse_advisory"] = {
            "mode": "advisory",
            "enabled": False,
            "disclaimer": ADVISORY_DISCLAIMER,
            "notes": ["Warehouse DB not configured (set FOOTBALL_WAREHOUSE_DATABASE_URL)."],
            "scores_were_unchanged": True,
        }
        return
    if binding is None:
        result["warehouse_advisory"] = {
            "mode": "advisory",
            "enabled": False,
            "disclaimer": ADVISORY_DISCLAIMER,
            "notes": ["No warehouse binding object supplied."],
            "scores_were_unchanged": True,
        }
        return

    ctx = result.get("ctx")
    if not isinstance(ctx, GameContext):
        result["warehouse_advisory"] = {
            "mode": "advisory",
            "enabled": False,
            "disclaimer": ADVISORY_DISCLAIMER,
            "notes": ["No GameContext on result — warehouse advisory skipped."],
            "scores_were_unchanged": True,
        }
        return

    try:
        payload = build_warehouse_advisory_payload(
            client,
            ctx,
            game,
            binding,
            similar_play_limit=similar_play_limit,
        )
    except Exception as exc:
        payload = {
            "mode": "advisory",
            "enabled": False,
            "disclaimer": ADVISORY_DISCLAIMER,
            "errors": [str(exc)],
            "scores_were_unchanged": True,
        }
    result["warehouse_advisory"] = payload
