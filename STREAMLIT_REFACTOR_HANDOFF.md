# Streamlit layer refactor — handoff

## Why `streamlit_state` instead of `state/`

The package already exposes drive logging via `playcaller/state.py` (`DriveLogger`). A nested `playcaller/state/` directory would shadow that module and break imports. Session-key and pending helpers therefore live in **`playcaller/streamlit_state/`** (keys, pending merges, Streamlit defaults).

## Snap review and exports (reviewable by default)

- **Storage:** `Game.recommendation_audit` is the in-memory list; the **`snap_review_log`** JSON key is the export-facing name for the same rows (see `playcaller/review/snap_review.py`, `SNAP_REVIEW_LOG_EXPORT_KEY`).
- **Workflow:** Each successful **Generate** appends a snap-level row (supersedes any prior open row for that snap). **Log** (or feed-append that closes the snap) links `linked_actual` and closes the row—no separate “audit mode” toggle.
- **Import:** `game_from_dict` loads via `snap_review_rows_from_export`, preferring non-empty `snap_review_log`, then legacy `recommendation_audit`.
- **Review Session:** `pages/Review_session.py` uses `review_timeline_rows` (drops `superseded`); feed-only sessions with no Generate rows still show as not reviewable.
- **Live feed:** `merge_current_espn_plays_into_drive_log(..., snap_review_audit=)` and sync paths call `close_snap_review_row_with_logged_actual` after append; `trim_snap_review_opens_for_play_count` runs at end of snapshot apply. **End drive** also trims after `drive_log.reset()`.
- **Export size (future):** `game_to_dict` currently writes the same list under both keys; a schema bump may keep a single canonical key after a deprecation window.

## Circular import / UI defaults

`new_game_ui_values` lives in **`playcaller/streamlit_state/ui_defaults.py`** so `live_data` → `sync` → `widget_backend_bridge` does not import `session` mid–`live_data` init. `widget_backend_bridge` must not pull session during that bootstrap path.

## Files created

| Path | Role |
|------|------|
| `playcaller/streamlit_state/keys.py` | Canonical `session_state` key strings (pending, undo, live feed). |
| `playcaller/streamlit_state/pending.py` | `apply_pending_*`, **`apply_all_pending`**, `clear_in_progress_log_state`. |
| `playcaller/streamlit_state/ui_defaults.py` | `new_game_ui_values` and related neutral UI presets (avoids `live_data` import cycles). |
| `playcaller/streamlit_state/session.py` | `ensure_play_caller_session_defaults`, `possession_side_radio_label`, `clear_live_feed_session_keys` (delegates new-game presets to `ui_defaults` where appropriate). |
| `playcaller/services/game_controller.py` | End drive, new-game presets, undo, wind sync, chip reruns, **`run_generate_if_requested`**. |
| `playcaller/ui/helpers.py` | Log labels, HUD math/copy, drive list expanders, `post_log_summary_and_toast`. |
| `playcaller/ui/sidebar.py` | Full sidebar (presets, fine tune, drive/session, ESPN NFL/college/**UFL**, generate form). |
| `playcaller/ui/main_console.py` | Main header, live console, generate/undo, HUD, eval expander, drive lists, recommendation dispatch, drive charts. |
| `playcaller/ui/recommendations.py` | Two-column recommendation + quick log UI. |
| `playcaller/ui/__init__.py` | Re-exports `render_sidebar`, `render_main_content`. |

## Files changed (high level)

- `streamlit_app.py` — Thin orchestration: defaults → **`apply_all_pending`** → wind pre-sync → `render_sidebar` → `GameContext` → `render_main_content`.
- `playcaller/live_data/sync.py` — Uses `streamlit_state.keys` for live-feed session keys (same string values).
- `playcaller/streamlit_app_support.py`, `streamlit_app_logic.py`, `streamlit_sidebar.py`, `streamlit_main.py` — **Shims** re-exporting new modules for backward compatibility.
- `tests/test_streamlit_app_support.py` — Added `test_apply_all_pending_matches_sequential_apply`.

## Logic map

| Concern | Location |
|---------|----------|
| Widget/pending/live-feed key names | `streamlit_state/keys.py` |
| Pre-widget pending merges | `streamlit_state/pending.py` |
| Neutral new-game UI defaults (import-safe) | `streamlit_state/ui_defaults.py` |
| Snap review lifecycle (Generate / Log / undo / trim) | `playcaller/evaluation/snap_review_lifecycle.py` |
| Snap review export key, timeline helpers | `playcaller/review/snap_review.py` |
| Session defaults / new-game snapshot | `streamlit_state/session.py` |
| Mutating actions & generate | `services/game_controller.py` |
| Sidebar layout & ESPN sync | `ui/sidebar.py` |
| Main shell & charts | `ui/main_console.py` |
| Play card & quick log | `ui/recommendations.py` |
| Shared formatting / drive lists | `ui/helpers.py` |

## Follow-ups (optional)

- Point sidebar live-feed reads/writes at `keys` constants for full consistency.
- Split `ui/recommendations.py` further if it grows (e.g. quick log vs. play header).
- Consider renaming shims once all call sites import `streamlit_state` / `ui` / `services` directly.
- **LIVE_FEED_TEAM_SCOPE:** caption vs prune when narrowing scope after opponent drives were imported (sideline-aligned feed scope).
- **Review UX:** optional handling when `void_undone` rows clutter the timeline; document feed-only sessions (no model rows) in Review Session copy.
- **History pipeline:** extend the same `snap_review_log` / `recommendation_audit` wording to any remaining operator-facing ingest or loader copy.
- **Feed semantics:** align sidebar/ingest documentation for `only_append_when_our_possession` vs current-drive merge and team scope (`LIVE_FEED_TEAM_SCOPE`).

## Validation

- `python3 -m pytest` — full suite green (includes pending-order, live-data, and snap-review export/merge tests).
- **Manual QA (recommended):** Generate → Log → Download JSON → Review Session replay; then Generate → ESPN sync appends a play → confirm the row closes with `linked_actual`, `LIVE_FEED_LAST_AUDIT` sane, and no orphan open rows after sync.
