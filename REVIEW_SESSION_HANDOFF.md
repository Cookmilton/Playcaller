# Review Session — handoff (film room + dual mode)

## Modes (priority)

1. **`TRUE_STORED`** — Upload (or session) has a non-empty **`snap_review_log`** list. Model side is **Generate-time** history (`is_historical=True`, `is_replay=False`).
2. **`LEGACY_STORED`** — Timeline rows came from **`recommendation_audit`** only in the JSON file (empty or missing `snap_review_log`). Same row builder as true stored; labeling differs.
3. **`REPLAY_ONLY`** — No non-superseded timeline rows, but **`game.drives` have logged plays**. Model side is **retroactive replay** (`is_replay=True`, `is_historical=False`). Never written to exports as truth. **First-class** in the UI (not a degraded mode).
4. **`NOT_REVIEWABLE`** — No plays and no timeline. Operator message: `REVIEW_MESSAGE_NONE` (no plays to review).

Resolution: `playcaller.review.unified_review.resolve_review_mode`. **Stored and replay data are never mixed** in a single `UnifiedReviewRow`.

## Main console sidebar (workflow)

Order in `playcaller/ui/sidebar.py`:

1. **Session** — identity (team, opponent, date, sim/real), status chips (`Game loaded` / sync), **Load JSON** + **New game**.
2. **Live Game · ESPN** — expanded by default; long help in a nested “What ESPN updates” expander; **Sync from ESPN** remains primary.
3. **Play Calls** — presets, quick adjust, possession/score, defense chips, **Generate** form + **Undo last play**, fine-tune expander, end-drive controls.
4. **Review & Export** — `_sidebar_export_review_status`: stored row count, replay available, export mode line; footer still holds **Download game JSON** after main console (fresh Generate rows).
5. **Advanced** — game-context debug toggle, corpus nudge (historical influence).

## Film room UI (`playcaller/ui/review_film_room.py`)

- **Coaching report** — plays in view, **drives** count, run/pass & bucket & direction match %, **high-confidence agreement** (≥60% conf snaps where run/pass and bucket both scored).
- **Quick insights** — pass-rate delta, early-down bias heuristic, best/worst down & distance by bucket match.
- **Drive headers** — team/drive #, result, play count, net yards, ~elapsed clock.
- **Cards** — actual vs model; colored **comparison strip** (match vs miss); mismatch tags (including too aggressive / conservative heuristics).
- **Breakdown** expander — normalized fields from `UnifiedReviewRow.breakdown_dict()` (includes `confidence` when known).
- **Filters** — sidebar: drive result, actual run/pass, possession scope, mismatch/match toggles, confidence emphasis, breakdown default.

## Archived drives (`playcaller/ui/previous_drives_render.py`)

- **Breakdown** checkbox per play replaces “Technical detail (comparison JSON)” — actual/replay buckets, field, match flags, confidence; no raw JSON dump.

## Copy (`playcaller/ui/product_copy.py`)

- `REVIEW_MESSAGE_STORED`, `REVIEW_MESSAGE_REPLAY`, `REVIEW_MESSAGE_NONE` — aligned with operator messaging in Review Session and mode banners.

## Replay taxonomy

- `playcaller/replay/replay_taxonomy.py` — punt / FG / two-point labeled under **special teams / …** where applicable for clearer buckets.

## Tests

- `tests/test_unified_review.py` — mode resolution, filters, grouping, metrics (**`drives_with_rows`**, summary rates), taxonomy smoke.

## Limitations / next steps

- **`predictor`**: session defaults **(re)create** a valid `FootballPlayPredictor` when missing or invalid.
- **Team filter** depends on `feed_team_espn_id` + coached team when possible.
- **Nested Streamlit expanders** (Live Game → help): if a Streamlit version disallows nesting, collapse help to a single caption.
- Optional: main-area filter strip on Review page (currently sidebar-only); snap index jumper; debug JSON for power users behind env flag.
