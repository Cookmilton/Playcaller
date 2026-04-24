"""Wrap ``FootballPlayPredictor.recommend`` with optional processed-JSON historical advisory."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from playcaller import FootballPlayPredictor, Game, GameContext
from playcaller.state import DriveLogger
from warehouse import recommender as wh_rec

logger = logging.getLogger(__name__)


def get_recommendation_with_history(
    predictor: FootballPlayPredictor,
    ctx: GameContext,
    drive_log: Optional[DriveLogger] = None,
    game: Optional[Game] = None,
    *,
    historical_plays: Any = None,
    warehouse_advisory: bool = False,
    warehouse_client: Any = None,
    warehouse_binding: Any = None,
    warehouse_similar_play_limit: int = 12,
) -> Tuple[Dict[str, Any], Optional[wh_rec.HistoricalRecommendation]]:
    rule_based = predictor.recommend(
        ctx,
        drive_log,
        game,
        historical_plays=historical_plays,
        warehouse_advisory=warehouse_advisory,
        warehouse_client=warehouse_client,
        warehouse_binding=warehouse_binding,
        warehouse_similar_play_limit=warehouse_similar_play_limit,
    )
    historical: Optional[wh_rec.HistoricalRecommendation] = None
    if wh_rec.is_enabled():
        try:
            historical = wh_rec.match(wh_rec.situation_from_game_context(ctx), wh_rec.get_cached_pool())
        except Exception:
            logger.exception("Historical recommender failed; proceeding with rule-based only")
            historical = None
    return rule_based, historical
