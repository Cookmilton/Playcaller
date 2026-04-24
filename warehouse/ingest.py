from __future__ import annotations

import json
import logging
from typing import Any

import nfl_data_py as nfl
import pandas as pd

logger = logging.getLogger(__name__)


def load_week_games_from_raw_cache(season: int, week: int) -> list[dict[str, Any]]:
    """Load ``{"meta", "plays"}`` game dicts from on-disk raw week files (no network).

    Expects ``warehouse.storage`` raw layout:
    ``data/raw/{season}/week_{WW}/*.json`` in the wrapped record shape written by
    :func:`warehouse.storage.store_raw_games`.
    """
    from warehouse.storage import REPO_ROOT

    week_dir = REPO_ROOT / "data" / "raw" / str(season) / f"week_{week:02d}"
    if not week_dir.is_dir():
        logger.warning("Raw cache directory missing (nothing to load): %s", week_dir.resolve())
        return []

    out: list[dict[str, Any]] = []
    for path in sorted(week_dir.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Skipping unreadable raw file: %s", path)
            continue
        game: dict[str, Any] | None = None
        g = raw.get("game")
        if isinstance(g, dict) and isinstance(g.get("meta"), dict) and isinstance(g.get("plays"), list):
            game = g
        else:
            pj = raw.get("payload_json")
            if isinstance(pj, str):
                try:
                    parsed = json.loads(pj)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, dict) and isinstance(parsed.get("meta"), dict) and isinstance(
                    parsed.get("plays"), list
                ):
                    game = parsed
        if game is None:
            logger.warning("Skipping raw file without meta/plays game payload: %s", path)
            continue
        out.append(game)

    logger.info(
        "Loaded %s game(s) from raw cache (%s)",
        len(out),
        week_dir.resolve(),
    )
    return out


def _iso_game_date(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if hasattr(value, "date") and callable(getattr(value, "date", None)):
        try:
            d = value.date()
            return d.isoformat()
        except (TypeError, ValueError, AttributeError):
            pass
    text = str(value).strip()
    if "T" in text:
        return text.split("T", 1)[0]
    return text[:10] if len(text) >= 10 else text


def load_week_games(
    season: int,
    week: int,
    *,
    game_type: str = "REG",
    cache_dir: str | None = None,
) -> list[dict[str, Any]]:
    """Load all games for the given season/week from nflverse.

    Returns one dict per game: ``meta`` (stable identifiers) and ``plays``
    (raw nflverse rows as dicts).
    """
    import_kwargs: dict[str, Any] = {"downcast": True}
    if cache_dir is not None:
        import_kwargs["alt_path"] = cache_dir

    try:
        df = nfl.import_pbp_data([season], **import_kwargs)
    except OSError as e:
        raise RuntimeError(
            f"Network error while loading nflverse play-by-play for season {season}: {e}"
        ) from e
    except ValueError as e:
        raise RuntimeError(
            f"Failed to parse nflverse play-by-play for season {season}: {e}"
        ) from e
    except Exception as e:
        raise RuntimeError(
            f"Unexpected error loading nflverse play-by-play for season {season}: {e}"
        ) from e

    if df.empty:
        logger.warning(
            "nflverse returned no play-by-play rows for season=%s (empty frame).",
            season,
        )
        return []

    if "week" not in df.columns or "season_type" not in df.columns:
        logger.warning(
            "nflverse frame missing expected columns (week / season_type) for season=%s.",
            season,
        )
        return []

    week_mask = pd.to_numeric(df["week"], errors="coerce") == int(week)
    type_mask = df["season_type"].astype(str) == str(game_type)
    subset = df.loc[week_mask & type_mask]

    if subset.empty:
        logger.warning(
            "No nflverse plays for season=%s week=%s game_type=%s (nothing to return).",
            season,
            week,
            game_type,
        )
        return []

    games_out: list[dict[str, Any]] = []
    for _gid, group in subset.groupby("game_id", sort=True):
        gdf = group
        if "play_id" in gdf.columns:
            gdf = gdf.sort_values("play_id", kind="mergesort")
        else:
            gdf = gdf.sort_index(kind="mergesort")

        row0 = gdf.iloc[0]
        home = row0["home_team"] if "home_team" in gdf.columns else ""
        away = row0["away_team"] if "away_team" in gdf.columns else ""
        gid = row0["game_id"] if "game_id" in gdf.columns else _gid
        gdate = (
            _iso_game_date(row0["game_date"])
            if "game_date" in gdf.columns
            else ""
        )

        meta = {
            "external_game_id": str(gid),
            "season": int(season),
            "week": int(week),
            "game_type": str(game_type),
            "home_team": str(home) if pd.notna(home) else "",
            "away_team": str(away) if pd.notna(away) else "",
            "game_date": gdate,
        }
        plays_raw = gdf.to_dict(orient="records")
        games_out.append({"meta": meta, "plays": plays_raw})

    n_games = len(games_out)
    n_plays = sum(len(g["plays"]) for g in games_out)
    logger.info("Loaded %s games, %s plays for %s W%s", n_games, n_plays, season, week)

    return games_out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _loaded = load_week_games(2025, 1)
    print("games:", len(_loaded))
    print("plays:", sum(len(g["plays"]) for g in _loaded))
    if _loaded and _loaded[0]["plays"]:
        _keys = sorted(_loaded[0]["plays"][0].keys())
        print("first_play_keys:", _keys)
    else:
        print("first_play_keys:", [])
