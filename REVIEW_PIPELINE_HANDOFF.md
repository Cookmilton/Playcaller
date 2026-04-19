# Review pipeline & archived-drive comparison — handoff

## What changed

1. **Previous drives (Actual column)**  
   Uses `format_actual_play_operator_headline` / `format_actual_play_operator_detail` so feed **`description`** lines win over thin structured stubs. Field goals append distance when `yards_gained` is set. Expander label is **Technical detail (comparison JSON)** (no “Structured row” placeholder framing).

2. **Model replay (current engine)**  
   Added `replay_summary_bucket_from_recommend` → stable labels (short/medium/deep pass, screen, inside/outside run, draw, QB scramble, special, etc.). `ModelReplayStructuredResult.summary_bucket` holds this; UI leads with the bucket, then family / call / confidence.

3. **Structured comparison rows**  
   `ActualVsReplayComparisonRow` now includes `actual_summary_bucket`, `replay_summary_bucket`, `coarse_bucket_match` (plus existing `to_dict()` fields). Previous drives renders from this object; JSON expander is for analysis only.

4. **Snap review capture & export**  
   - `ensure_snap_review_list_on_game` normalizes `recommendation_audit` to a real list after session init, JSON load, and before Generate.  
   - `game_to_dict` uses `list(game.recommendation_audit or [])`.  
   - Sidebar **Export** always shows an in-session **Snap review** caption: row count, last pipeline event (`after_generate` / `after_log_result` / `before_export` / `generate_skipped`), and latest row status when known.  
   - `merge_streamlit_snap_review_debug` always updates `SNAP_REVIEW_SESSION_TRACE_KEY` (not only when verbose env is on).

## Files touched (main)

| Area | Files |
|------|--------|
| Actual formatting | `playcaller/actual_result.py`, `playcaller/__init__.py` |
| Taxonomy | `playcaller/replay/replay_taxonomy.py`, `playcaller/replay/comparison.py`, `playcaller/replay/analysis_types.py`, `playcaller/replay/previous_drive_replay.py`, `playcaller/replay/__init__.py` |
| UI | `playcaller/ui/previous_drives_render.py`, `playcaller/ui/sidebar.py` |
| Snap review lifecycle | `playcaller/evaluation/snap_review_lifecycle.py`, `playcaller/evaluation/snap_review_logging.py`, `playcaller/services/game_controller.py`, `playcaller/ui/recommendations.py`, `streamlit_app.py`, `pages/Review_session.py` |
| Export | `playcaller/game.py` |
| Tests | `tests/test_replay_taxonomy.py`, `tests/test_archived_replay_juxtapose.py` |

## Actual formatting approach

- Prefer non-empty **`description`** (ESPN / import / finalized log line).  
- Else analysis primary → else `format_actual_play_result_description`.  
- FG good/miss lines include yardage when `yards_gained > 0`.

## Replay taxonomy

- Driven by engine **`bucket`** (e.g. `short_yardage`, `long_yardage`, `red_zone`) + **`play_family`** + light play text (e.g. “screen” in routes).  
- Conservative defaults: unknown family still yields a readable string (e.g. situation bucket as words, or `recommended call`).  
- **Not** stored as historical model output; **not** used for dedup or scoring.

## Snap review lifecycle (unchanged rules, hardened wiring)

- **Generate:** `record_open_snap_review_row_after_generate` appends to `game.recommendation_audit` (exported as `snap_review_log` + legacy `recommendation_audit`).  
- **Log:** `close_snap_review_row_with_logged_actual` closes the matching open row.  
- **Export:** `game_to_json` serializes the same list under both keys.

## Export verification (operator)

1. Use main console **Generate play call**, then **Log result** at least once.  
2. Sidebar **Export** caption should show `row(s) in game.recommendation_audit` **> 0** and `last event: after_generate` / `after_log_result` / `before_export`.  
3. Download JSON: `snap_review_log` and `recommendation_audit` should be non-empty arrays with the same rows.

Optional: `PLAYCALLER_SNAP_REVIEW_LOG=1` for file logging; `PLAYCALLER_SNAP_REVIEW_STREAMLIT_DEBUG=1` for extra JSON expander.

## Remaining limitations

- Replay buckets are **heuristic**; reconstructed pre-snap for archived drives is approximate (documented overlay).  
- **Coarse bucket match** is intentionally conservative (exact bucket match or limited run/pass agreement).  
- Older JSON exports with empty `snap_review_log` remain non-reviewable; that is expected.

## Next step

- Optional: cache `comparison_rows_for_archived_drive` by `(game_id, drive index, predictor identity)` for long sessions.  
- Optional: extend taxonomy with explicit **play-action** vs **quick game** depth using route metadata when present in `PLAY_LIBRARY`.
