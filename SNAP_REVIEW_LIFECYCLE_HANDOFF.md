# Snap review lifecycle — refactor handoff

## What changed

- **Formal lifecycle module:** `playcaller/evaluation/snap_review_lifecycle.py` owns orchestration (Generate → open row, Log/feed → close row, undo, trim after drive reset / sync). Low-level dict fields stay in `playcaller/evaluation/audit.py`.
- **Row model:** Documented as `SnapReviewRowDict` (TypedDict). Stored as JSON-safe `dict`. New rows include:
  - **`row_id`**: stable 32-char hex; **`snap_id`**: first 12 chars (legacy/display).
  - **`scoreboard_at_generate`**: offense/defense points, game `quarter`, `clock_seconds_remaining` at Generate time (in addition to full **`pre_snap`** `GameContext`).
  - Existing fields unchanged in spirit: `review_ordinal`, `drive_epoch`, `plays_at_recommend`, `session_game_id`, model pick, `team_possession`, `linked_actual` when closed.
- **Generate:** `run_generate_if_requested` calls `record_open_snap_review_row_after_generate` (supersede same snap → append open row).
- **Log:** `playcaller/ui/recommendations.py` calls `close_snap_review_row_with_logged_actual`.
- **Live feed:** `live_data/sync.py` and `live_data/espn_current_drive_merge.py` use the same close helper; sync end still trims with `trim_snap_review_opens_for_play_count`.
- **End drive:** `archive_current_drive_and_reset_session` trims open rows after `drive_log.reset()` so prior-drive opens do not linger.
- **Export:** `game_to_dict` writes **`snap_review_log` first**, then legacy **`recommendation_audit`** (same list). Import still prefers `snap_review_log` via `snap_review_rows_from_export`.
- **Review Session:** Copy treats **`snap_review_log`** as the primary review source; legacy key described as mirror.
- **Module location:** Lifecycle lives under **`evaluation/`** (not `review/`) so `live_data.sync` does not import `playcaller.review` (avoids `review` → `derived` → `ui` → `live_data` circular import).

## Files touched (this refactor)

| File | Change |
|------|--------|
| `playcaller/evaluation/snap_review_lifecycle.py` | **New** — lifecycle API + `SnapReviewRowDict` + rules in docstring |
| `playcaller/evaluation/audit.py` | `row_id` / `snap_id`, `scoreboard_at_generate`; `link_open_audit_to_actual` doc points to lifecycle |
| `playcaller/services/game_controller.py` | Generate / undo / end-drive use lifecycle |
| `playcaller/ui/recommendations.py` | Log uses `close_snap_review_row_with_logged_actual` |
| `playcaller/live_data/sync.py` | Close + trim via lifecycle (`..evaluation` import) |
| `playcaller/live_data/espn_current_drive_merge.py` | Close via lifecycle |
| `playcaller/game.py` | Export key order: `snap_review_log` before `recommendation_audit` |
| `playcaller/review/snap_review.py` | Schema + export key docs |
| `pages/Review_session.py` | Primary vs legacy copy |
| `tests/test_snap_review_lifecycle.py` | **New** — generate+log, double generate+supersede, undo, trim, export order, round-trip |
| `tests/test_evaluation.py` | Export test asserts `row_id`, `scoreboard_at_generate` |

## Snap review lifecycle (rules)

1. **Open:** Successful recommend → supersede prior **open** rows for same `(drive_epoch, plays_at_recommend)` → append one **open** row with frozen model + context.
2. **Close:** After `drive_log.log(actual)`, find the **latest** **open** row with `plays_at_recommend == len(results_after) - 1` → set `linked_actual`, `status: closed`.
3. **Repeat Generate:** Earlier opens on that snap → **`superseded`**; timeline helpers drop them.
4. **Undo:** Latest **closed** → **`void_undone`**; trim trailing opens with stale `plays_at_recommend`.
5. **New series:** After drive log reset, trim with `plays_on_drive=0` (and `eval_drive_epoch` increments for new opens).

## Export behavior

- Both keys always present when `game_to_dict` runs; lists are identical references (same content).
- Older files without `snap_review_log` still load from `recommendation_audit`; empty lists → Review Session “not reviewable” message.

## Edge-case rules (explicit)

| Case | Behavior |
|------|-----------|
| Generate once → Log | One row closes 1:1 with that play index |
| Generate N times same snap | N−1 rows `superseded`, one `open` until log |
| Log with no matching open | Close returns false; no scoring change |
| Undo | Last closed voided; stale opens trimmed |
| End drive | Log reset + trim opens for empty log |
| Feed append | Same close rule as manual log; manual+ESPN id link does not double-close |

## Limitations

- **Historical only:** No recommendation or calibration logic reads `recommendation_audit` / export rows.
- **Open rows at export:** Possible if operator Generated but never logged that snap.
- **Duplicate JSON keys:** Two keys still duplicate array payload size (future: single canonical key + migration).

## Exact next step

Manual: **Generate → Log → Download JSON → Review Session upload**; confirm timeline shows pre-snap, model pick, and `linked_actual`. Optional: **double Generate** then Log → only one non-superseded closed row for that snap.
