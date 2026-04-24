# COPY/PASTE HANDOFF

## 1. Project / Goal

This work replaces the archived-drive “flag discrepancies only” model with **reconciliation**: one **reconciled** outcome and stats for the archive header, score ribbon, and threaded implied score, while ESPN raw and play-inferred values remain **diagnostic**. The audit panel explains **how** the primary UI was built (provenance, resolution notes, verbose flags) instead of contradicting the header.

## 2. Audit findings

See **`DRIVE_RECONCILIATION_PHASE0.md`** for the full Phase 0 trace. Summary:

- **Divergence:** Archive titles used **`Drive.result` (plays-only)** while the audit compared ESPN metadata to the same inferred result without **overriding** display — three stories (header, ESPN column, inferred column) could disagree.
- **Score threading** used **`implied_points_for_drive`** on inferred kinds, not ESPN-authoritative scoring when feeds disagreed.
- **No precedence rules** for outcome in UI; ESPN was advisory only.
- **Replay rows** showed operator headlines; structured quarter/clock/field were only in optional breakdowns, with clock coming from **session overlay** in `PreSnapContextRecord`.

## 3. What was implemented

- **Phase 1:** `playcaller/reconciliation/drive_reconciler.py` — `EspnDriveRaw`/`InferredDriveSnapshot` (internal), `ReconciledDrive`, `AuditFlag`, `reconcile_drive()`, `archived_drive_expander_title()`, `scoring_points_for_reconciled_kind()`. ESPN authoritative buckets win for outcome; plays/yards prefer ESPN when present; start field from ESPN or reconstructed first snap; start Q/clock from ESPN `start_*` or first-play metadata only (never `end_*`).
- **Phase 2:** `compute_drive_audit()` threads **`rec.possession_points`** (reconciled) for cumulative score.
- **Phase 3–5:** `archived_drive_expander_title_from_audit()`, archive expanders and ribbon use **reconciled** labels; audit table adds **Outcome (reconciled)**, **Provenance**, **Pts (reconciled)**; inline audit block is diagnostic (three outcomes + provenance + notes).
- **Phase 4:** Compact monospace **pre-snap context line** above each play in replay (Q/clock left, down/distance, own/opp yard line; special-teams rows skip fake offensive down/distance).
- **Phase 6:** Removed duplicate ESPN/inferred bucket implementations from `drive_audit_report` (canonical in reconciler). `implied_points_for_drive()` now delegates to **`reconcile_drive`** for backward compatibility.
- **Phase 8:** `tests/test_drive_reconciliation.py` — precedence, override, missing ESPN, scoring, title smoke.
- **UX:** Default “flagged” lens includes drives with **raw bucket disagreement** even when reconciled severity is **clean**, so diagnostics stay visible.

## 4. Key files changed

| Path | Change |
|------|--------|
| `DRIVE_RECONCILIATION_PHASE0.md` | Phase 0 written audit. |
| `playcaller/reconciliation/__init__.py` | Package exports. |
| `playcaller/reconciliation/drive_reconciler.py` | New reconciliation service and types. |
| `playcaller/drive_audit_report.py` | Wired to reconciler; threaded score; `DriveAuditRow` extended; `archived_drive_expander_title_from_audit()`; lens/filter semantics. |
| `playcaller/ui/previous_drives_render.py` | Reconciled titles, ribbon hover, audit block, compact play context lines. |
| `tests/test_drive_reconciliation.py` | New unit tests. |

## 5. Why the changes were made

**Central reconciliation** avoids UI-level `espn or inferred` choices and keeps **one** path for primary display. **Provenance** and **AuditFlag** preserve transparency without showing three conflicting “truths” as equals. The audit panel **explains** the reconciled row; raw ESPN vs plays remain for debugging.

## 6. Tests added/updated

| File | Purpose |
|------|---------|
| `tests/test_drive_reconciliation.py` | Precedence, ESPN override, missing ESPN, scoring points, expander title smoke. |

Full suite: **427 passed**, 2 skipped (after this work).

## 7. Remaining limitations / follow-ups

- **PAT/2PT:** Still uses TD = 7; no distinct 2PT detection from feed in reconciler.
- **Clock on replay:** Pre-snap clock still derives from **reconstruction + overlay** (`PreSnapContextRecord`); not true per-snap ESPN game clock unless feed enriches plays later.
- **END_HALF / long ESPN strings:** Mapped conservatively; edge labels may stay coarse.
- **`implied_points_for_drive`:** Now calls `reconcile_drive` per invocation — acceptable for rare callers; avoid tight loops without caching.
- **Full Packers–Lions fixture assertions:** Not added as a single large integration test in this pass; can extend `tests/test_espn_nfl_golden_fixture.py` or similar.

## 8. Recommended next step

Run **`streamlit run streamlit_app.py`**, open **Archived drives** with a synced ESPN session, and confirm one **reconciled** headline matches the **Drive audit** row and the **score ribbon** bumps align with reconciled scoring — then add one **golden** integration test that freezes expected reconciled outcomes for the existing JSON fixture if you want CI lock-in.
