Playcaller checkpoint — 2026-09-11 (EOD shutdown)
Read from git + source on this checkout. Not from chat memory.

1. Project Summary
- Streamlit 1.56 play-calling console: situation board, heuristic recommendations,
  drive log, ESPN live sync, Review / History / Warehouse pages.
- Live ESPN path is honest-null: missing or out-of-domain fields are skipped with
  reasons; HUD shows “not synced” instead of fake Q1 15:00 / 1st&10.
- Cloud GitHub main is C.7 honesty (a81ad08) on top of G2.0. Local main also has
  G2.1 (feed_drive_plays) plus a merge of the C.7 replay. Scoring/Review WIP is
  unstaged and must not ship with G2.
- Predictor is still a hand-tuned heuristic with history/warehouse as optional
  nudge, not a trained in-game model.
- Operator pushes releases. Agents must not git push.

2. Current Architecture
- streamlit_app.py: session defaults → run_requested_live_sync → apply_all_pending
  → reconcile game_*↔ui_* → sidebar → main console → maybe_rerun_after_widgets.
- playcaller/services/live_feed_sync.py (B–G2): Sync button sets LIVE_SYNC_REQUESTED;
  fetch+apply_snapshot run pre-widget; flag cleared in finally (G2.0).
- playcaller/live_data/: ESPN HTTP, situation, clock, completed/current drive merge,
  drive_boundaries, feed_drive_plays (G2.1 local), apply_snapshot audit.
- playcaller/possession.py: offense|defense|None; Generate/Log/End-drive gates.
- playcaller/streamlit_state/: keys, pending queues, widget_backend_bridge,
  ui_write_guard, load_game, session defaults.
- playcaller/game.py + state.DriveLogger: session Game vs in-progress drive log.
- playcaller/heuristic_predictor.py: ranking + situation buckets.
- playcaller/ui/: sidebar, main_console, situation_honesty, previous_drives_render,
  recommendations, format_play_context.
- warehouse/ + football_history_warehouse/: ingest, validation, review loader.
- pages/: Review_session.py, History_library.py, Warehouse.py.

Changed in Phases B–G2 (and C.7 honesty): live_data/* (situation, clock, drives,
  session date/team, drive_boundaries), live_feed_sync.py, possession.py,
  streamlit_state keys/pending/bridge, situation_honesty.py, local_time.py,
  espn_session_team.py. G2.1 adds espn_drive_plays.py (local only).

3. Data Model / State
- game_* = backend/feed mirrors. ui_* = Streamlit widget keys. GAME_UI_MIRROR_PAIRS
  in widget_backend_bridge.py. Hydrate: if GAME_WIDGET_HYDRATE_PENDING, copy
  game_* → ui_* before widgets; else later sync_backend_from_widgets copies
  ui_* → game_* (skipped while hydrate pending — G1 tripwire).
- Script order: LIVE_SYNC_REQUESTED sync, then pending, then hydrate/reconcile,
  then widgets. Sync after widgets would be clobbered by ui→game copy.
- Pending: log situation advance, end-drive UI, new-game UI, session-setup hydrate,
  ESPN date/team name fill, scoreboard status, load-game JSON,
  PENDING_RERUN_AFTER_WIDGETS (only st.rerun site after widgets).
- Game.possession None = unset (not opponent). Generate/Log/End drive blocked until
  offense|defense. UI label “Not set”.
- Drive identity: session_drive_epoch on operator End drive (stable if archives
  re-sort). ESPN drives ordered by plays[].sequenceNumber. Review data keys off
  epoch / feed identity, not list index.
- Sync audit (LIVE_FEED_LAST_AUDIT / SyncResult): applied[], skipped as
  {field, reason} for situation fields (locked | no_situation_source |
  absent_in_source | out_of_range) plus string skips (leftover open, scope, locks).
  situation_source: scoreboard | last_play_end | None. Counters: plays_appended,
  drives_imported, completed_drive_plays_imported, current_drive_plays_merged,
  drive_log_rows_before/after.
- Dedup: ActualPlayResult.external_play_id. LIVE_FEED_SEEN_PLAY_IDS for current
  merge. LIVE_FEED_MERGED_ESPN_DRIVE_KEYS for completed import. A play id lives in
  DriveLogger or game.drives, not both (drive_boundaries). Leftover: if
  drives.current.id moved but logger still holds previous ids, top up tails and
  skip auto-archive (PREVIOUS_FEED_DRIVE_OPEN); operator End drive owns close.

4. Features implemented in Phases B–G2
- ESPN scoreboard pick or Event ID; coached team; sync readiness gates.
- Pre-widget sync so feed values reach the board (G1).
- Honest situation: skip unsynced down/distance/field/possession/timeouts/clock/
  quarter; HUD “not synced”; Generate gated on possession + honesty.
- Score/date from ESPN; empty session date/team fill; operator-set names/dates win.
- Import completed drives and current-drive plays (toggles); leftover open-drive
  warning + End drive above Generate (does not auto-close).
- DriveLogger vs archive play-id uniqueness; archive order by sequenceNumber.
- Sync stamps in viewer TZ (st.context.timezone), else labelled UTC (C.7).
- No field-diagram marker when field_position not synced (C.7).
- Final: apply ESPN period/clock when present, else skip (C.7).
- G2.0: LIVE_SYNC_REQUESTED always cleared; errors in LIVE_FEED_LAST_ERROR.
- G2.1 (local): one feed_drive_plays helper for current merge, completed import,
  tail top-up. Not on origin/main.

5. Next Steps (order)
- Sunday live-test review (checklist §11). Redeploy if Cloud is not a81ad08.
- Finish/review G2.1–G2.6 as one change: G2.1 already local; G2.2 auto-close
  leftover; G2.3 undo; G2.4 stale Log; G2.5 extra tripwire; G2.6 AppTests.
  Push together after review (operator push).
- H: polling via LIVE_SYNC_REQUESTED (same pre-widget path).
- I: actual vs recommended — reuse format_play_context plus a new neutral
  comparison-line module (not UI-coupled).
- F4.1 parked: down-aware bucket (1st&10 is long_yardage today).
- Merge scoring-attribution WIP (no branch yet; unstaged on main). Do not mix
  with a G2 push.

6. Known Limitations / Gaps
- Ingestion: situation lives on scoreboard, not summary; Final games often omit
  period/clock/situation; TLS verify=False fallback possible locally.
- UI: every archived drive can show [ESPN≠model] when feed outcome ≠ model
  result (drive_audit_report.audit_status_header_tag). Previous-drive comparison
  widgets use prev_drv_{chron_i} prefixes (keys grow with archive length).
- Prediction: hand-set baselines in heuristic_predictor; get_bucket() maps
  distance>=7 to long_yardage with no down test (1st&10 = long_yardage); ranking
  clamps distance to 1–25 (board HUD uses unclamped distance).
- State: no auto-close leftover drive; no stale-call block on Log (regenerate
  after every sync). Undo exists as UNDO_BUNDLE / snap-review trim, not G2.3.
- Local Python 3.14.4; Cloud Python not pinned (no runtime.txt). pandas pin
  pandas>=1.5.3,<2.0 in requirements.txt (GitHub web-edit constraint).
- .gitignore is only `data/`. warehouse.db is tracked and dirty. ~824 *.pyc
  files are tracked. Ignore/pyc cleanup NOT done. Do not commit warehouse.db.

7. Critical Files / Entry Points
- streamlit_app.py — app entry; pre-widget sync + hydrate order.
- playcaller/services/live_feed_sync.py — request_live_sync / run_requested_live_sync.
- playcaller/live_data/sync.py — apply_snapshot + audit.
- playcaller/live_data/espn_situation.py — scoreboard vs last_play_end.
- playcaller/live_data/drive_boundaries.py — play-id occupancy; leftover open.
- playcaller/live_data/espn_drive_plays.py — G2.1 play list helper (local).
- playcaller/streamlit_state/keys.py — session key canon.
- playcaller/streamlit_state/widget_backend_bridge.py — game_* / ui_* mirror.
- playcaller/possession.py — possession None semantics and gates.
- playcaller/ui/situation_honesty.py — HUD + Generate honesty.
- playcaller/ui/main_console.py — Generate / Log / leftover End drive.
- playcaller/ui/sidebar.py — ESPN controls, locks, import toggles.
- playcaller/ui/format_play_context.py — Review context line (reuse for I).
- playcaller/heuristic_predictor.py — buckets + rank.
- playcaller/game.py / playcaller/state.py — Game, Drive, DriveLogger.
- tests/fixtures/espn_summary_live_401872657.json — real ESPN capture.

8. Streamlit rules learned
- Mid-script st.rerun() drops unrendered widgets; one rerun site after widgets
  (PENDING_RERUN_AFTER_WIDGETS).
- Streamlit 1.56 silently resets selectbox/slider if value is out of domain.
- Sync must run pre-widget or ui→game copy clobbers feed values.
- Callbacks may write widget keys; script body must not after those widgets render.
- st.context.timezone may be empty on first run → label UTC.
- Fixtures must come from real ESPN captures.
- AppTests must assert values ARRIVE, not just survive.

9. Git state (after this checkpoint commit on local main)
- origin/main: a81ad088328877473db3dca16062e712174f059c
  (C.7 replay on ee3f5f7; G2.0 a21f829 is ancestor; G2.1 is not.)
- Local main was 7 ahead, then this checkpoint. Prior 7:
  4022479 Share one feed_drive_plays helper for current merge, completed import, and tail top-up.
  11d4617 Merge remote-tracking branch 'origin/main'
  ad3d3d5 Honor Final period and clock: apply ESPN values when present, else skip as not synced.
  b1b8b6c Omit the field-diagram marker when field position is not synced.
  bb36b60 Format live-sync stamps in the viewer timezone, falling back to labelled UTC.
  28a7023 Fill empty session team name from ESPN on sync; operator-set names win.
  20f5a9b Merge remote-tracking branch 'origin/main'
  (ad3d3d5..28a7023 are the original C.7 hashes; origin has replay d7da04f..a81ad08.)
- Branches: only main (g1-sync-board deleted; it was merged). No wip/g2-partial
  (no partial G2 files). No wip/scoring-attribution branch.
- Worktrees: this checkout only.
- Unstaged/untracked WIP (do not fold into G2/C.7):

  Review UX:
  pages/Review_session.py
  playcaller/ui/previous_drives_render.py
  playcaller/ui/review_film_room.py
  playcaller/ui/review_session_ux.py (untracked)
  tests/test_review_session_ux.py (untracked)

  Scoring / warehouse / posteam:
  playcaller/domain.py
  playcaller/drive_audit_report.py
  playcaller/implied_scoring.py (untracked)
  playcaller/reconciliation/play_context.py
  warehouse/debug.py features.py models.py normalize.py quality.py
  warehouse/review_loader.py validation.py
  warehouse/implied_score_audit.py (untracked)
  warehouse/posteam_inference.py (untracked)
  tests/test_features.py test_play_context.py test_quality.py
  tests/test_validation.py test_validation_fixes.py test_validation_rules.py
  tests/test_implied_score_audit_summary.py test_posteam_inference.py
  tests/test_posteam_split.py test_score_reconstruction.py
  tests/test_unknown_reduction.py (untracked)
  scripts/export_unknown_dominant_baseline.py (untracked)

  Data: warehouse.db (tracked, dirty — do not commit)

  Also dirty/untracked: many __pycache__ / *.pyc (tracked history; ignore NOT done)

10. G2 status
- G2.0 shipped — a21f829 on origin/main (and a81ad08).
- G2.1 committed-local — 4022479; not on origin/main.
- G2.2 not started — auto-close leftover; code still requires End drive
  (drive_boundaries: “does not auto-archive”). E6 leftover warning is shipped.
- G2.3 not started — dedicated undo item; UNDO_BUNDLE exists from earlier snap path.
- G2.4 not started — stale Log / regenerate block not in deployed code.
- G2.5 not started — numbered G2 tripwire. G1 already skips ui→game when
  GAME_WIDGET_HYDRATE_PENDING.
- G2.6 not started — G2 AppTests. Leftover End-drive AppTest (E6) is already on
  origin (test_leftover_end_drive_apptest.py).
- No G2.2–G2.6 files were in the working tree; nothing parked on wip/g2-partial.

11. Sunday live-test checklist
- Deployed build is a81ad08 (verify in Manage app). Fresh session:
  load game via Refresh scoreboard or Event ID, pick our team, sync.
- After each sync: down, distance, field position, possession,
  timeouts, quarter, clock match ESPN; situation chip = ESPN live.
- Log a play: chains advance and survive the next click.
- REGENERATE after every sync before logging (stale-call block not
  deployed).
- Open-drive warning -> End drive -> sync: archived drive includes its
  final play (esp. scores); next drive imports; archived order correct.
- Set Dime, sync, Dime survives.
- Note: timestamp timezone, sidebar speed per click, any not-synced
  fields during live play. Save Full last sync detail JSON for any
  anomaly.

12. Copy/paste handoff block

=== START HANDOFF ===
Context: Playcaller Streamlit 1.56 console + ESPN live sync. 2026-09-11 EOD.
Cloud origin/main is a81ad08 (Phases B–G2.0 + C.7 honesty). Local main is
ahead with G2.1 (4022479) and C.7 original hashes merged with the C.7 replay.
Scoring-attribution / Review UX / warehouse.db remain unstaged. Do not push.

Current Capabilities: Load ESPN game, sync situation/score/clock when present,
honest “not synced” HUD, gated Generate, import completed + current drives,
leftover End-drive (manual), drive-log vs archive play-id split, viewer-TZ
stamps, empty team name/date from ESPN. Heuristic recommend + log plays.
Review/History/Warehouse pages exist.

Architecture: streamlit_app pre-widget LIVE_SYNC_REQUESTED → apply_snapshot →
pending → game_* hydrate → widgets. live_data ESPN provider; possession.py
gates; DriveLogger vs game.drives.

Data Model: game_* backend vs ui_* widgets; possession None = unset;
session_drive_epoch vs sequenceNumber; sync audit applied/skipped/situation_source;
dedup via external_play_id + LIVE_FEED_SEEN_PLAY_IDS + MERGED_ESPN_DRIVE_KEYS.

Recent Additions: C.7 honesty (clock/field/TZ/team name) on origin as
d7da04f–a81ad08. G2.0 on origin. G2.1 local only (feed_drive_plays).

Deployed vs local: Deployed should be a81ad08 after Cloud rebuild (was ee3f5f7
before C.7 ship). Local has G2.1 + unstaged scoring/Review WIP. Suites:
local HEAD 881 passed / 4 skipped; origin a81ad08 876 passed / 4 skipped
(clean worktrees, Python 3.14.4).

Next Goal: review Sunday results, then finish G2

Constraints:
  - Keep Streamlit UI; Streamlit pinned 1.56.0
  - Avoid overengineering; build incrementally
  - Never write widget-bound keys after render; one st.rerun site
  - Honest nulls; logic out of UI files
  - Never git push; operator pushes releases
  - Don't touch scoring-attribution / warehouse WIP

Task: After Sunday live-test notes, implement G2.2–G2.6 on top of local G2.1
(4022479), keep scoring/Review WIP unstaged, do not push. Confirm Cloud is
a81ad08 before treating C.7 as live. Park F4.1. Polling (H) and actual-vs-
recommended (I) wait until G2 ships.
=== END HANDOFF ===
