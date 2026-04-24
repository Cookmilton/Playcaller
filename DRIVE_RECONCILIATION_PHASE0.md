# Phase 0 — Drive data flow audit (pre-refactor)

## 1. Trace the paths

| Field (displayed) | File | Function | Data source |
|-------------------|------|----------|-------------|
| Archived drive header: team, drive # | `playcaller/live_data/drive_display.py` | `prior_drive_heading` | `Drive.feed_team_*`, `Drive.possessing_team`, `team_drive_index` from `chronological_team_drive_indices` |
| Header: outcome phrase | same | same | **`Drive.result.headline`** from `classify_drive_end` / `complete_drive_from_plays` → **inferred from plays** |
| Header: plays, yards, TOP detail | same | same | **`Drive.result.detail_line`** from `_drive_detail_line` → **computed from `len(plays)` and sum yards** (TOP = `seconds_per_play * n`, not ESPN) |
| Drive outcome in expander body | `playcaller/ui/previous_drives_render.py` | Indirect via header only; replay table uses `format_actual_play_operator_headline` | **Actual play text** + reconstruction |
| Audit: Outcome (inferred) | `playcaller/drive_audit_report.py` | `compute_drive_audit` | **`dr.result.headline`** (`inf_label`) |
| Audit: Outcome (ESPN) | same | same | **`DriveFeedAuditSnapshot.espn_display_result` or `espn_result_code`** |
| Score at drive start / after | same | `compute_drive_audit` loop | **Threaded running sum** of `implied_points_for_drive(dr)` using **`dr.result.kind` (inferred)**, not ESPN |
| Field start (audit) | same | same | **ESPN** `audit.start_field_text` / `start_yard_line`; else `"—"` + flag |
| Q start / clock start | same | same | **ESPN** `start_period`, `start_clock_display` (not `first_play_*` in table) |
| Score ribbon hover “outcome” | `playcaller/ui/previous_drives_render.py` | `render_drive_score_ribbon` | **`DriveAuditRow.outcome_inferred`** (inferred headline) |

**Root inconsistency:** The archive **header** and the **running score in the audit** both ultimately lean on **`Drive.result` (play-inferred)**, while **ESPN outcome** is only compared for flags. When ESPN says FG and plays infer Punt, the header shows Punt, the audit flags ESPN≠model, and the implied score row may follow Punt (0 pts) while ESPN expects 3 — duplicated stories.

## 2. Duplicated logic (divergence sources)

| Computation | Locations | Notes |
|-------------|-----------|--------|
| Drive outcome / kind | `game.classify_drive_end`, `game.complete_drive_from_plays`, `drive_audit_report.inferred_outcome_bucket`, `drive_audit_report.espn_outcome_bucket` | Two parallel taxonomies (coarse ESPN string vs `DRIVE_END_*`). |
| Play count | `Drive.play_count` from `with_computed_stats` vs `audit.feed_offensive_plays` | Compared in audit only. |
| Yards | `Drive.total_yards` (sum of plays) vs `audit.feed_yards` | Compared in audit. |
| TOP | `Drive.time_elapsed_seconds` (modeled) vs `audit.time_elapsed_display` | Audit shows both; header uses modeled elapsed via detail line. |
| Start field | ESPN snapshot only in audit; **not** used in `prior_drive_heading`. | Header never shows start field. |
| Start Q/clock | ESPN `start_*` in audit; replay uses **ambient `GameContext`** for `PreSnapContextRecord.quarter/seconds_remaining` — not per-play ESPN clock. | **Divergence:** replay pre-snap clock is overlay, not feed. |
| Score delta for drive | `implied_points_for_drive` in audit vs session `game.offense_points` | Single threaded pass in `compute_drive_audit`; uses inferred kind. |

## 3. Precedence gaps

| Field | Current rule |
|-------|----------------|
| Outcome for display (header) | **(c)** Inferred only — **no ESPN override.** |
| Outcome for implied score | **(b)** Inferred only — order of `classify_drive_end` then points. |
| Plays / yards in header | **(b)** From `Drive` stats (play-derived). |
| ESPN vs inferred mismatch | **(a)** Explicit comparison for flags only — **does not change displayed primary outcome.** |
| Start field / Q / clock | **(a)** ESPN in audit when present; not reconciled with replay chain. |

## 4. Play-by-play context (replay card)

**Shown today:** `format_actual_play_operator_headline` / `detail` (from `actual_result.py`); breakdown checkbox exposes `PreSnapContextRecord` down/distance/territory/yardline, quarter/clock from **overlay**, run/pass buckets.

**In raw `ActualPlayResult`:** No quarter/clock/down/yardline fields — mostly **not** in structured form on the play object.

**ESPN-normalized imports:** Quarter/clock may exist on raw JSON before normalization; worth using in enriched row when available from structured helpers if present on plays.

**Gaps vs target:** Per-play **game clock at snap**, **score at snap**, and **special-teams-specific** fields are **not** in the primary two-line actual column today; special teams often skip model column only.

---

*End of Phase 0. Implementation follows in `playcaller/reconciliation/drive_reconciler.py` and consumers.*
