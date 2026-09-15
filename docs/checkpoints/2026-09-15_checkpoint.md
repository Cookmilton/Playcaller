# Playcaller checkpoint — 2026-09-15 (J arc shipped)

Read from git + source on this checkout (`ccbcf82`). Not from chat memory.

## 1. Project Summary
- Streamlit 1.56 sideline OC console: situation board, heuristic recommends,
  DriveLogger, ESPN live sync, Review / History / Warehouse pages.
- Live ESPN path is honest-null; HUD shows “not synced” instead of fake defaults.
- **origin/main = ccbcf82** (B–G2.1, C.7, full J arc) — pushed and on Streamlit Cloud.
- Drive outcomes/yards now ESPN-authoritative; DriveLogger integrity fixed (J2).
- Operator pushes releases. Agents must not `git push`.

## 2. Current Architecture
- `streamlit_app.py` — session → `run_requested_live_sync` → pending → hydrate → UI → one rerun.
- `playcaller/services/live_feed_sync.py` — `LIVE_SYNC_REQUESTED` pre-widget fetch/apply.
- `playcaller/live_data/` — ESPN HTTP, situation, clock, completed/current merge, sync audit.
- `playcaller/possession.py` — offense|defense|None gates; End-drive feed-team attribution (J2).
- `playcaller/streamlit_state/` — keys, pending queues, widget_backend_bridge, load_game.
- `playcaller/game.py` + `state.DriveLogger` — archived Game vs in-progress log.
- `playcaller/heuristic_predictor.py` — ranking + situation buckets.
- `playcaller/ui/` — sidebar, main_console, situation_honesty, previous_drives_render.
- `warehouse/` + `football_history_warehouse/` — ingest / review loader.
- `pages/` — Review_session, History_library, Warehouse.

**J arc touched:** `espn_import_merge` (ESPN outcome/yards; skip partials),
`game.classify_drive_end` / `complete_drive_from_plays` (unknown default; ESPN win;
`inferred_kind` shadow; terminals), `espn_play_normalize` (nullified TD; Official Timeout;
penalty net), `play_event_segment` (snap vs yards; KO/punt/INT/FG exclusion),
`drive_boundaries` (leftover hold on drive-id change), `feed_team_scope` (logger
coached-only), `game_controller` archive (possessing from feed team),
`drive_audit_report` (shadow mismatch; any yards Δ visible).

## 3. Data Model / State
- `game_*` = backend/feed mirrors; `ui_*` = widget keys. Hydrate copies `game_*`→`ui_*`
  before widgets when `GAME_WIDGET_HYDRATE_PENDING`; else later `ui_*`→`game_*`.
- Script order: `LIVE_SYNC_REQUESTED` sync → pending → hydrate/reconcile → widgets.
  Sync after widgets would be clobbered.
- Pending: log situation, end-drive UI, new-game, session-setup, ESPN date/team,
  scoreboard status, load-game JSON, `PENDING_RERUN_AFTER_WIDGETS` (sole `st.rerun`).
- `Game.possession` None = unset (not opponent). Generate/Log/End blocked until set.
- Drive identity: `session_drive_epoch` on operator End drive; ESPN sort by
  `sequenceNumber`. Dedup: `external_play_id`, `LIVE_FEED_SEEN_PLAY_IDS`,
  `LIVE_FEED_MERGED_ESPN_DRIVE_KEYS`.
- Sync audit: `applied[]`, situation skips `{field,reason}`, leftover/scope strings,
  `situation_source`, merge counters, `drive_log_rows_before/after`.

**NEW in J:** `Drive.outcome_source` (`espn`|`inferred`|`unknown`);
`Drive.yards_source` + `computed_yards` (ESPN `total_yards` when present);
`Drive.inferred_kind` (shadow play inference — never the exported primary outcome);
terminal kinds `end_of_half` / `end_of_game`; `unknown` for indeterminate ends;
`outcome_source is None` on legacy drives = untrusted for tendencies.

## 4. Features implemented

### Live console / sync (B–G2.1, C.7)
- ESPN scoreboard/Event ID; coached team; sync readiness; pre-widget sync (G1/G2.0).
- Honest situation skips; HUD; Generate gated on possession + honesty.
- Completed + current drive import; leftover open warning + End drive (manual).
- Play-id uniqueness across logger vs archive; archive order by sequenceNumber.
- Viewer-TZ stamps; field marker omitted when unsynced; Final clock honesty (C.7).
- Shared `feed_drive_plays` helper (G2.1).

### Drive data correctness (J arc)
- ESPN `result` → stored `Drive.result`; unknown default (not invented punt).
- Nullified TD → penalty; Official Timeout skipped; snap vs yards predicates.
- ESPN drive yards authority; KO/punt/INT return / FG distance excluded from offense;
  penalty net once (`yards_gained`; `penalty_yards=0` on ESPN penalties).
- Shadow `inferred_kind` restores ESPN≠model audit cross-check.
- Logger coached-only (even scope Both); leftover hold on drive-id change incl. manual;
  skip partial completed imports; End-drive possessing from feed team ids;
  `honest_summary_line` renders clock (not `None`).

## 5. Next Steps (order)
1. **G2.2** — auto-close leftover open drive when safe.
2. **G2.3** — undo that un-archives the last End drive.
3. **G2.4** — block Log on stale recommendation after sync.
4. **G2.5** — tripwire raises under tests (hydrate / ui→game).
5. **G2.6** — AppTests on `401872931` fixtures.
6. **H** — polling via `LIVE_SYNC_REQUESTED` (same pre-widget path).
7. **I** — actual vs recommended (reuse `format_play_context` + neutral comparison module).
8. Merge `wip/scoring-attribution` — re-run Part A discovery against corrected
   penalty/return-yard logic before new fixes.
9. **F4.1** parked — down-aware bucket (1st & 10 is `long_yardage` today).

## 6. Known Limitations / Gaps
- **Ingestion:** situation often on scoreboard not summary; Final may omit period/clock;
  TLS `verify=False` fallback exists locally — Cloud behavior unconfirmed.
- **Audit tags (401872931 fixture re-import, board 0–0):**
  - `[ESPN≠model]` — `drive_audit_report.py:384-386` / tag `:213-214`: ESPN outcome
    bucket vs **shadow** `inferred_outcome_bucket` (`inferred_kind`). **4/24** drives
    (12 END_HALF, 22–23 DOWNS, 24 END_GAME). Real signal — not every drive.
  - `[review]` — tag `:218` via `warning_other` (`:191-203`): catch-all for
    `severity=warning` that is not outcome_mismatch / incomplete. **13/24** drives;
    10 of those have **empty per-drive flags**, elevated only because
    `global_score_mismatch` (`:105-106`) when board is 0–0 vs implied 10–31.
    On that re-import path `[review]` carries little per-drive signal. Neither tag
    fires on every drive (7 show `score Δ` instead).
- **UI:** `prev_drv_{chron_i}` widget keys in `previous_drives_render.py` (fix at
  WIP merge). Hand-set heuristic baselines; ranking clamps distance 1–25.
- **State:** no auto-close leftover (G2.2); no stale-Log block (G2.4).
- **Env:** local Python 3.14; Cloud unpinned (no `runtime.txt`);
  `pandas>=1.5.3,<2.0` on Cloud vs 2.x locally.
- **Repo hygiene:** `.gitignore` is only `data/`; `warehouse.db` tracked and dirty;
  ~824 `*.pyc` tracked; cleanup NOT done. Do not commit `warehouse.db`.

## 7. Critical Files / Entry Points
- `streamlit_app.py` — entry; pre-widget sync + hydrate order.
- `playcaller/services/live_feed_sync.py` — request / run live sync.
- `playcaller/live_data/sync.py` — `apply_snapshot` + audit.
- `playcaller/live_data/espn_import_merge.py` — completed drives → `game.drives` (J).
- `playcaller/live_data/espn_play_normalize.py` — ESPN play → ActualPlayResult (J).
- `playcaller/live_data/drive_boundaries.py` — occupancy; leftover hold (J2).
- `playcaller/live_data/feed_team_scope.py` — live logger coached-only (J2).
- `playcaller/game.py` — Drive fields, classify/complete (J).
- `playcaller/play_event_segment.py` — snap vs yards predicates (J).
- `playcaller/drive_audit_report.py` — tags, yards Δ, shadow mismatch (J).
- `playcaller/services/game_controller.py` — End drive archive path (J2).
- `playcaller/possession.py` — None semantics; feed-team possessing (J2).
- `playcaller/ui/situation_honesty.py` — HUD + summary clock (J2).
- `playcaller/ui/main_console.py` / `sidebar.py` — Generate/Log/ESPN controls.
- `tests/fixtures/espn_summary_mnf_401872931.json` — MNF golden.

## 8. Streamlit rules learned
- Mid-script `st.rerun()` drops unrendered widgets; one rerun after widgets.
- Streamlit 1.56 resets selectbox/slider if value is out of domain.
- Sync must run pre-widget or `ui→game` clobbers feed values.
- Callbacks may write widget keys; script body must not after those widgets render.
- `st.context.timezone` may be empty on first run → label UTC.
- Fixtures from real ESPN captures; AppTests assert values arrive, not just survive.

## 9. Git state
- **origin/main:** `ccbcf8260a334ae6508bf81f1c0f3e96cc8e52b9` (in sync with local main
  before this checkpoint commit).
- **Branches:** `main`; `wip/scoring-attribution` exists locally and on origin at
  `7d0cd33` — “WIP: scoring attribution, posteam inference, Review UX”.
- **Worktrees:** this checkout only.
- **Dirty (do not commit):** `warehouse.db`; many tracked/untracked `__pycache__` /
  `*.pyc`; untracked `scripts/`. Checkpoint commit is this file alone.

## 10. J arc summary (defect → fix commit)
- ESPN outcome ignored; inferred last-play defaulted to punt → `9ce62c0`
- Invented punt when unclassified → `unknown` (`6cf50c6`)
- “TOUCHDOWN NULLIFIED” matched as TD → `e89b0c4`
- Official Timeout counted as a snap → `d11de0c`
- KO/punt/INT return + FG kick yards as offense → `ed3ed53` (+ predicates `d11de0c`)
- Penalty `yards_gained` + `penalty_yards` double-count → `aa89cc5`
- Computed sum beat ESPN drive yards → ESPN authority (`3330fba`)
- No terminal end_of_half/end_of_game kinds → `4568ce1`
- ESPN≠model compared stored ESPN kind (0 mismatches) → shadow `inferred_kind` (`e30f707`)
- Scope “both” leaked opponent into DriveLogger → `c011aca`
- Leftover hold skipped manual-only rows → `df9eeea`
- Partial completed-drive import → skip+warn (`ef35aea`)
- End drive used board `possession` → feed team ids (`d689cc2`, kickoff ignore `ccbcf82`)
- `honest_summary_line` rendered “None” → `5429eef`

## 11. Verification record (deployed ccbcf82, event 401872931 final)
- Implied score from stored drives = actual final **DEN 10 / KC 31**.
- 24 drives: all `outcome_source=espn`, `yards_source=espn`.
- Outcomes: 5 TD, 2 FG, 2 downs, 2 INT, 1 fumble, 10 punts, end_of_half, end_of_game.
- Max drive yards 80; espn−computed Δ = 0 on 22 drives; Δ 1 and 2 on drives 18/19.
- Zero duplicate `external_play_id` across 145 plays; 12 DEN offense / 12 KC defense.
- Suite: **918 passed / 4 skipped** in a clean worktree.

## 12. Copy/paste handoff block

```
=== START HANDOFF ===
Context: Playcaller (Cookmilton/Playcaller) — Streamlit 1.56 sideline OC
console + Review Session over live ESPN Site API data. origin/main is
ccbcf82 (Phases B–G2.1, C.7, full J arc J1/J1.6/J1.7/J2), pushed and
deployed. Scoring-attribution / Review UX WIP is on branch
wip/scoring-attribution @ 7d0cd33 — do not touch it or warehouse.db.
Verified on deployed build, event 401872931 final: DEN 10 / KC 31 implied
matches actual; 24 drives espn outcome+yards; max yards 80; Δ≤2; 918/4 suite.

Current Capabilities: ESPN sync with honest nulls; completed + current drive
import; DriveLogger coached-only; leftover hold on drive-id change; ESPN
outcomes/yards with shadow inferred_kind audit; End-drive feed-team
attribution; heuristic recommend + log; Review/History/Warehouse pages.

Architecture: streamlit_app pre-widget LIVE_SYNC_REQUESTED → apply_snapshot →
pending → game_* hydrate → widgets. live_data ESPN provider; possession gates;
DriveLogger vs game.drives; drive_audit_report tags.

Data Model: game_* vs ui_*; possession None=unset; session_drive_epoch /
sequenceNumber; outcome_source / yards_source / computed_yards / inferred_kind
(shadow); terminal end_of_half/end_of_game; unknown ends; legacy outcome_source
None untrusted for tendencies.

Recent Additions: Full J arc on origin/main (drive correctness + logger
integrity). G2.1 feed_drive_plays already on main.

Deployed vs local: Both at ccbcf82 after operator push. Local dirty:
warehouse.db + pycache only (plus this checkpoint once committed).

Next Goal: implement G2.2–G2.6 as one reviewable change
  (auto-close leftover; undo un-archive; stale Log block; tripwire under
  tests; AppTests on 401872931 fixtures).

Constraints:
  - Keep Streamlit UI; Streamlit pinned 1.56.0
  - Avoid overengineering; build incrementally
  - Never write widget-bound keys after render; one st.rerun site
  - Honest nulls over plausible defaults; logic out of UI files
  - Never git push; operator pushes releases
  - Don't touch wip/scoring-attribution or warehouse.db

Task: Implement G2.2 through G2.6 on main as one reviewable change set.
Do not start H/I or merge scoring-attribution yet. Do not push.
=== END HANDOFF ===
```
