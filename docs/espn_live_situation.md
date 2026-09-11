# ESPN live situation

Operator-facing live down / distance / field / possession / timeouts for Play Caller.

## Source of truth

Live situation lives on **scoreboard** `events[].competitions[0].situation`, not summary `header`. Sync fetches both; fallback is `drives.current.plays[-1].end`. Unapplied fields use structured `skipped: {field, reason}`. Do not reintroduce summary-header `situation` in fixtures.

Priority:

1. `"scoreboard"` — the only source that carries timeouts.
2. `"last_play_end"` — summary `drives.current.plays[-1].end`, used only when the scoreboard fetch failed, the event is missing, or its `situation` block is absent.

Parsers live in `playcaller/live_data/espn_situation.py`. They return **raw** values; range policy is in `playcaller/live_data/sync.py` so a field that cannot be applied is reported instead of silently coerced.

## Seen-play-id reset

Seen-play-id reset keys on **`drives.current.id`**, never on scoreboard possession — the scoreboard flips possession about one snap early, and resetting on it re-merges the still-current drive as duplicates.

- Working set: `prepare_seen_play_ids_for_feed` in `playcaller/live_data/espn_current_drive_merge.py`
- Snapshot field: `EspnLiveSnapshot.current_feed_drive_id`
- Session key: `live_feed_last_current_drive_id` (`LIVE_FEED_LAST_CURRENT_DRIVE_ID`)
- Toggle: `SyncOptions.reset_seen_play_ids_on_possession_change` — the name is historical; the flag now controls a **drive-id** reset, not board possession.

Board possession can still disagree with `drives.current` for one snap at change of possession. Drive-id keying removed the duplicate-merge consequence of that disagreement; it did not remove the disagreement.

## Widget domains

Mirrored widget domains are declared once in `streamlit_state/widget_backend_bridge.py` and imported by `ui/sidebar.py`. Streamlit 1.56 silently resets out-of-domain hydrated values, so feed writers must skip, never clamp. `ui_distance` is a 1–99 `number_input`; the predictor still clamps distance to 1–25 for ranking.

| Constant | Domain |
|----------|--------|
| `GAME_DOWN_ALLOWED_VALUES` | 1–4 |
| `GAME_DISTANCE_MIN` / `GAME_DISTANCE_MAX` | 1–99 |
| `GAME_TIMEOUTS_ALLOWED_VALUES` | 0–3 |
| `GAME_YARDLINE_RANGE` | 1–50 |

`distance_in_widget_domain` is the single check for distance. A synced distance of 31 reaches the board honestly and then ranks as 25 inside `heuristic_predictor` (and related clamps in `situation.py` / replay). That is intentional for now: the board and the model do not agree above 25.

## Honesty UI

Skipped fields must not render as live defaults. Logic lives in `playcaller/ui/situation_honesty.py` (not in render code). The HUD shows `"not synced"` plus a source chip (`ESPN live` / `ESPN last play` / `Manual` / `Not set`) and reason captions. A fresh board has possession unset — chip **Not set**, possession **unknown**, Generate disabled until the operator sets a side or syncs. Generate is also disabled on opponent possession. Opponent-ball gating lives in `playcaller/streamlit_state/possession.py` (`possession_is_opponent` / `generate_blocked_reason_for_possession`); UI buttons and `game_controller` both call it.

`Game.possession` is `offense` | `defense` | **`None`**. Unknown is not the opponent: `flipped_possession(None)` stays `None`, `possession_is_opponent(None)` is `False`, and both **Generate** and **Log result** are blocked with *Set possession or sync from ESPN*. Export writes JSON `null`; a legacy save with no `possession` key still loads as `offense`.

The sidebar possession control is three chips (**Not set** | **Our team** | **Opponent**) that write `ui_possession_side` via `apply_and_rerun` — same pattern as down/distance. Do not bind it as `st.radio` / `st.selectbox`: Streamlit 1.56 reports those widgets' defaults when another chip is clicked, and only keys `apply_and_rerun` writes survive. `Game.possession` stays `None` while the chip shows **Not set**.

**Import direction.** The rules themselves live in **`playcaller/possession.py`**, a leaf that imports nothing from `playcaller`, so `playcaller/game.py` imports `flipped_possession` at module level. Keep it a leaf: importing any `streamlit_state` submodule from it would execute `streamlit_state/__init__.py` → `session.py` → `playcaller.game` and cycle. `playcaller/streamlit_state/possession.py` re-exports those rules and adds only the two session-aware helpers (`apply_possession_from_ui`, `mark_board_origin_manual`).

**End drive.** Blocked while possession is unset, same reason string as Generate and Log. The single choke point is `archive_current_drive_and_reset_session` in `services/game_controller.py`; the one-tap End buttons are disabled but do not carry their own check. That gate is what keeps `Drive.possessing_team`'s `None` → `"offense"` coercion unreachable from the UI — the coercion logs a warning when it fires.

**New game / Load JSON.** Do not call `hydrate_session_setup_widgets` in the same run as the click — Streamlit 1.56 raises once those widgets already exist. Set `PENDING_SESSION_SETUP_HYDRATE` and let `apply_all_pending` hydrate before widgets.

## File map

| Path | Role |
|------|------|
| `playcaller/live_data/espn_situation.py` | Parse scoreboard / last-play-end situation |
| `playcaller/live_data/espn_football.py` | Snapshot includes `current_feed_drive_id` |
| `playcaller/live_data/espn_current_drive_merge.py` | Drive-id keyed seen-play-id reset |
| `playcaller/live_data/sync.py` | Apply or skip; persist last current drive id |
| `playcaller/streamlit_state/widget_backend_bridge.py` | Canonical widget domains |
| `playcaller/possession.py` | Pure rules: unset vs opponent vs our ball; Generate/Log/End-drive gating; sole `flipped_possession` |
| `playcaller/streamlit_state/possession.py` | Re-exports those rules; adds `apply_possession_from_ui`, `mark_board_origin_manual` |
| `playcaller/ui/situation_honesty.py` | HUD / Generate honesty |
| `playcaller/ui/sidebar.py` | Imports domain constants; Distance 1–99; possession chips |
| `tests/test_espn_situation.py` | Scoreboard vs last-play-end + skip reasons |
| `tests/test_situation_honesty.py` | Domain + HUD / skip copy |

Fixtures for live situation must come from the **scoreboard** payload (see `tests/fixtures/espn_scoreboard_live_*.json`). Summary fixtures must not invent a `header.situation` block.
