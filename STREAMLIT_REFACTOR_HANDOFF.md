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

## ESPN live situation (do not regress)

Canonical write-up: **`docs/espn_live_situation.md`**.

Live situation lives on **scoreboard** `events[].competitions[0].situation`, not summary `header`. Sync fetches both; fallback is `drives.current.plays[-1].end`. Unapplied fields use structured `skipped: {field, reason}`. Do not reintroduce summary-header `situation` in fixtures.

Seen-play-id reset keys on **`drives.current.id`**, never on scoreboard possession — the scoreboard flips possession about one snap early, and resetting on it re-merges the still-current drive as duplicates.

Mirrored widget domains are declared once in `streamlit_state/widget_backend_bridge.py` and imported by `ui/sidebar.py`. Streamlit 1.56 silently resets out-of-domain hydrated values, so feed writers must skip, never clamp. `ui_distance` is a 1–99 `number_input`; the predictor still clamps distance to 1–25 for ranking.

Possession rules live in **`playcaller/possession.py`** (leaf, imports nothing from `playcaller`), so `game.py` imports `flipped_possession` at module level. `streamlit_state/possession.py` re-exports them. **Generate**, **Log result**, and **End drive** are all blocked while possession is unset, each at one choke point.

Possession control: three chips (**Not set** | **Our team** | **Opponent**) via `apply_and_rerun`, not `st.radio` / `st.selectbox`. Streamlit 1.56 reports those widgets' defaults when another chip is clicked; only keys `apply_and_rerun` writes survive. `Game.possession` stays `None` while the chip shows **Not set**.

## Files created

| Path | Role |
|------|------|
| `playcaller/streamlit_state/keys.py` | Canonical `session_state` key strings (pending, undo, live feed). |
| `playcaller/streamlit_state/pending.py` | `apply_pending_*`, **`apply_all_pending`** (includes `PENDING_SESSION_SETUP_HYDRATE` so **New game** / **Load JSON** do not write session-setup widgets after they instantiate), `clear_in_progress_log_state`. |
| `playcaller/streamlit_state/ui_defaults.py` | `new_game_ui_values` and related neutral UI presets (avoids `live_data` import cycles). |
| `playcaller/streamlit_state/session.py` | `ensure_play_caller_session_defaults`, `possession_side_radio_label`, `clear_live_feed_session_keys` (delegates new-game presets to `ui_defaults` where appropriate). |
| `playcaller/services/game_controller.py` | End drive, new-game presets, undo, wind sync, chip reruns, **`run_generate_if_requested`**. |
| `playcaller/ui/helpers.py` | Log labels, HUD math/copy, drive list expanders, `post_log_summary_and_toast`. |
| `playcaller/ui/sidebar.py` | Full sidebar (presets, fine tune, drive/session, ESPN NFL/college/**UFL**, generate form). Imports widget-domain constants; Distance is a 1–99 `number_input`. |
| `playcaller/ui/main_console.py` | Main header, live console, generate/undo, HUD, eval expander, drive lists, recommendation dispatch, drive charts. |
| `playcaller/ui/recommendations.py` | Two-column recommendation + quick log UI. |
| `playcaller/ui/situation_honesty.py` | HUD “not synced” / source chip / Generate-disabled reasons. All honesty logic lives here, not in render code. |
| `playcaller/ui/local_time.py` | Local-time formatting (`Synced HH:MM TZ`); `helpers.fmt_local_epoch` delegates here. |
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
| Widget domain constants (down/distance/timeouts/yardline) | `streamlit_state/widget_backend_bridge.py` |
| Live situation parse (scoreboard → last-play-end) | `live_data/espn_situation.py` |
| Seen-play-id reset (`drives.current.id`) | `live_data/espn_current_drive_merge.py` |
| HUD / Generate honesty | `ui/situation_honesty.py` |
| Local-time formatting | `ui/local_time.py` |
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
- **Predictor vs board:** `heuristic_predictor` still clamps distance to 1–25; a honest board distance above 25 ranks as 25.
- **`SyncOptions.reset_seen_play_ids_on_possession_change`:** public field name is historical; consider a rename once call sites can move together.
- **`Drive.possessing_team`:** still normalizes `None` → `"offense"` in `_norm_possessing_team` while `Game.possession` is optional. It is now unreachable from the UI (End drive is blocked while possession is unset) and logs a warning when it fires, so this is a cleanup, not a correctness gap. Making it optional touches the reconciler, drive display, audit report, and export schema — do it as its own phase.

## Validation

- `python3 -m pytest` — full suite green (includes pending-order, live-data, and snap-review export/merge tests).
- **Manual QA (recommended):** Generate → Log → Download JSON → Review Session replay; then Generate → ESPN sync appends a play → confirm the row closes with `linked_actual`, `LIVE_FEED_LAST_AUDIT` sane, and no orphan open rows after sync.
