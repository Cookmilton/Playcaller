# Review Session — handoff (film room + dual mode)

## Modes (priority)

1. **`TRUE_STORED`** — Upload (or session) has a non-empty **`snap_review_log`** list. Model side is **Generate-time** history (`is_historical=True`, `is_replay=False`).
2. **`LEGACY_STORED`** — Timeline rows came from **`recommendation_audit`** only in the JSON file (empty or missing `snap_review_log`). Same row builder as true stored; labeling differs.
3. **`REPLAY_ONLY`** — No non-superseded timeline rows, but **`game.drives` have logged plays**. Model side is **retroactive replay** (`is_replay=True`, `is_historical=False`). Never written to exports as truth.
4. **`NOT_REVIEWABLE`** — No plays and no timeline. Hard stop.

Resolution: `playcaller.review.unified_review.resolve_review_mode`.

## Rendering model

- **`UnifiedReviewRow`** (`playcaller/review/unified_review.py`): single contract for the UI — pre-snap dict, actual headline/detail (operator formatting), model headline/subline, **`UnifiedComparison`** (run/pass, summary bucket, family), confidence when known, breakdown via **`breakdown_dict()`** (key fields only, no full raw JSON).
- **Film room UI**: `playcaller/ui/review_film_room.py` — summary metrics, quick insights, drive expanders, two-column play cards, comparison strip, **Breakdown** expander, sidebar filters.

## UX changes

- **Summary strip**: play count, logged actual count, run/pass match %, bucket match %, “correct direction” (= run/pass match), optional family rate caption.
- **Quick insights**: lightweight bullets (model vs actual pass rate, best/worst situation bucket by match rate).
- **Filters (sidebar)**: drive result kind, actual run/pass, our/opponent/both, mismatches-only / matches-only, confidence emphasis, breakdown default expanded.
- **Mismatch styling**: border color by `match_strength` (strong / partial / mismatch / neutral); optional heuristic tags (e.g. short-yardage pass vs run).
- **Copy**: Replay mode uses an explicit warning (no stored decisions); **not** the old “session is not reviewable” when plays exist. Export sidebar caption explains stored vs replay-capable files (`SIDEBAR_CAPTION_EXPORT_REVIEW`).

## Data integrity

- No fabrication of `snap_review_log`.
- Replay remains **view-only**; exports unchanged by Review Session.
- Labels **STORED MODEL** vs **REPLAY MODEL** on cards.

## Tests

- `tests/test_unified_review.py`: mode resolution, audit row build, filters, grouping, metrics, `model_summary_bucket_from_audit_row` smoke.

## Limitations / next steps

- Replay requires a **`predictor`** in `st.session_state` (open main console once); otherwise rows are empty and a warning is shown.
- **Team filter** depends on `feed_team_espn_id` + coached team when possible; unknown side may be excluded under our/opp filters.
- Optional: restore a compact **single-snap navigator** for power users; optional **juxtaposed JSON** for audit vs replay (removed from the main page to reduce confusion).
- Optional: LRU/session cap for replay cache already exists elsewhere; keep an eye on long replay-only sessions.
