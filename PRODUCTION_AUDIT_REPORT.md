# Play Caller — production audit (TEST2 workspace)

Date: 2026-04-20. Scope: Streamlit app (`streamlit_app.py`), `playcaller/`, `football_history_warehouse/`, `tests/`.  
**Dependency versions:** unchanged (`requirements.txt` not modified).

---

## Phase 1 — Codebase inventory (no code changes)

### 1. Python modules (~130 files, excluding `.pytest_vendor2/` and `__pycache__`)

| Area | Role |
|------|------|
| **Root** | `streamlit_app.py` — main multipage entry; `app.py` — legacy alternate Streamlit UI (not used by main path); `football_play_predictor.py` — re-exports `playcaller` for stable imports. |
| **pages/** | `History_library.py`, `Review_session.py`, `Warehouse.py` — multipage Streamlit routes sharing session/pending/reconcile pattern. |
| **playcaller/** | Core domain: `game.py`, `state.py`, `situation.py`, `engine.py`, `domain.py`; ESPN live: `live_data/*` (fetch, parse, merge, sync, feed scope, display); UI: `ui/*`; Streamlit glue: `streamlit_state/*`, `streamlit_app_logic.py`, `services/game_controller.py`; replay/review: `replay/*`, `review/*`; warehouse adapter: `warehouse/*`. |
| **football_history_warehouse/** | FastAPI `api/app.py`, ingest/normalization/pipeline, SQLite/Alembic storage, query repositories/services, validation, CLI. |

*Per-file one-liners:* omitted here for length; every path is listed under `find . -name '*.py'` excluding vendor/venv (see repo). Key entrypoints: `streamlit_app.py`, `football_history_warehouse/api/app.py`, `football_history_warehouse/cli/*.py`.

### 2. Orphan / legacy candidates [REPORT ONLY]

- **`app.py`** — Standalone Streamlit prototype (`football_play_predictor_claude_final`); not imported by tests or `streamlit_app.py`. **Recommendation:** keep but add a one-line module comment pointing to `streamlit_app.py` as the supported entry, or archive if unused locally.
- **`.pytest_vendor2/`** — vendored pytest subtree in repo (unusual); tests run against system/pyenv `pytest`. **Recommendation:** document why vendored copy exists or remove from tree to avoid confusion.

### 3. Duplicate / overlapping logic [REPORT ONLY]

- **Session defaults:** `ensure_play_caller_session_defaults` + `new_game_ui_values` — intentional split (documented in `ui_defaults.py`).
- **Score/situation mirroring:** `widget_backend_bridge` vs `sync.apply_snapshot` — complementary (widgets ↔ `game_*` vs ESPN snapshot).
- **Team labels:** ESPN summary helpers vs drive display — domain-appropriate overlap.

### 4. Data flow (ESPN → render)

1. **Fetch:** `live_data/http_client`, `espn_football.parse_espn_summary` → `NormalizedGameSnapshot` (single parse per sync when invoked from sidebar flow).
2. **Ingest:** `sync.apply_snapshot` updates `session` `game_*` keys, `Game`, optional `DriveLogger`, merges **completed** drives via `espn_import_merge.merge_completed_espn_drives_into_game`, live current plays via `espn_current_drive_merge`.
3. **Storage:** Session holds `game`, `drive_log`, predictor, live-feed keys; optional warehouse is separate DB/API.
4. **Render:** Sidebar + `main_console` / `previous_drives_render` after `reconcile_widget_and_backend_state` + `sync_backend_from_widgets`.
5. **Export:** Sidebar JSON/export slot uses `game` + session metadata.

**Mutation guards:** `assign_session_state` / `ui_write_guard`, pending dicts applied before widgets, `ensure_play_caller_session_defaults` on cold start.

### 5. `st.session_state` keys

- **Canonical names:** `playcaller/streamlit_state/keys.py` (must not rename — product rule).
- **Writes-without-read / cold KeyError:** mitigated by `ensure_play_caller_session_defaults` and widget defaults in `new_game_ui_values`.
- **Duplication:** `ui_*` vs `game_*` mirrors are intentional (bridge layer).

---

## Phase 2 — Dead code & cleanup

| Action | Status |
|--------|--------|
| Delete orphan `.py` files | **Deferred** — `app.py` kept; flag legacy only. |
| Strip multiline commented code | **Not fully scanned** — no bulk removal this pass (risk of removing intentional commented API examples). |
| `print()` / debug `st.write` | **Verified:** debug `print` not in `playcaller/ui`; CLI `playcaller/cli.py` prints are intentional TUI. |
| Unused imports (autoflake repo-wide) | **Deferred** — high risk without incremental CI; recommend `ruff check --select F401` in a follow-up. |
| Stale TODO/FIXME sweep | **Deferred** — date-stamped follow-up. |

---

## Phase 3 — Logic & bugs

| Item | Result |
|------|--------|
| **(a) Unguarded state access** | **Improved:** `streamlit_app.py` now reads operator widget keys via `.get(..., new_game_ui_values()[...])` and wraps defaults init in `_init_session_state()`. Full-repo sweep of `st.session_state.attr` remains a follow-up (e.g. `game_controller`, `sidebar`). |
| **(b) Silent failures** | **REPORT ONLY** — broad pattern change; existing `SyncResult`/sidebar errors cover sync path. |
| **(c) ESPN edge cases** | **REPORT ONLY** — existing fixtures (`espn_summary_no_display_clock.json`, golden NFL trim) + tests; exhaustive safety/PAT/OT matrix deferred. |
| **(d) Score/context threading** | **REPORT ONLY** — prior sequential threading work assumed present; full re-audit of `complete_drive_from_plays` + audit trail not repeated in this pass. |
| **(e) Dedup key** | **Reviewed:** `_stable_drive_key` uses `event_id|drive:id` or play-id span — adequate for coarse dedup. |
| **(f) Feed team scope** | **Fixed:** Completed drives are **always** merged into `game.drives`; scope applies only in `drive_display.filter_previous_drive_indices` / Previous drives UI. **Exception:** In-progress **current drive** play merge to `DriveLogger` still respects scope/possession so opponent plays are not written into the OC’s live log — intentional safety (documented below). |

---

## Phase 4 — Performance

| Item | Result |
|------|--------|
| **(a) Re-render / cache** | **REPORT ONLY** — audit `st.cache_data` on hot paths (drive audit, warehouse client) as follow-up. |
| **(b) Warehouse SQL** | **REPORT ONLY** — migrations already index `games.game_id`, `drives.game_id`, etc.; `NULLS LAST` avoided in inventory/competition queries (see tests). |
| **(c) ESPN single-parse** | **REPORT ONLY** — `apply_snapshot` consumes one `NormalizedGameSnapshot` per call; verify multi-call paths in UI manually. |
| **(d) Session bloat** | **REPORT ONLY** — full JSON / `game.drives` can exceed 50KB; candidate: disk cache keyed by `event_id` (future). |

---

## Phase 5 — Tests

- **Full suite:** `421 passed, 2 skipped` (after changes).
- **Packers 31–24 Lions fixture:** **Not in `tests/fixtures/`** — golden file is NE/SEA (`espn_summary_nfl_golden.json`). **REPORT ONLY:** add dedicated fixture when capturing that game.

---

## Phase 6 — Quality & consistency

| Item | Result |
|------|--------|
| **Naming** | **No session key renames** (per product rule). |
| **Type hints / docstrings** | **Partial:** `app_constants.py` added; full public-API docstring sweep **deferred**. |
| **Magic numbers** | **`playcaller/app_constants.py`** added as the single surface (incremental adoption). |

---

## Phase 7 — Code changes applied (this pass)

1. **`playcaller/live_data/espn_import_merge.py`** — Store all completed feed drives; `feed_team_scope` ignored for merge filtering (audit/UI unchanged strings).
2. **`tests/test_espn_drive_import.py`** — Expectations updated; renamed test for scope behavior.
3. **`streamlit_app.py`** — `_init_session_state()` + safe `.get` for UI reads.
4. **`playcaller/app_constants.py`** — Central constants file (TD/FG/safety, sanity ceiling, sync TTL hint).

### Manual Streamlit verification [REPORT ONLY]

Recommended operator checklist: cold start, ESPN sync, archived drives + filter, drive audit ribbon, generate, end drive, JSON download — not executed in this agent session.

---

## REPORT ONLY — consolidated backlog

- Legacy `app.py` deprecation or archive.
- Repo-wide `st.session_state` attribute access hardening.
- `ruff`/`autoflake` unused imports.
- `st.cache_data` for expensive audit/warehouse reads.
- Packers–Lions (or chosen) full ESPN summary fixture for integration tests.
- Session-state size / optional file cache for large payloads.
- Film room / archive lens copy alignment (product).
