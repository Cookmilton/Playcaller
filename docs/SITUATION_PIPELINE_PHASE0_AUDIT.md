# Phase 0 — Pre-snap situation pipeline audit

References are to the repository state **before** the situation-resolver extension.

## 1. What ESPN provides per play (Packers–Lions `espn_summary_packers_lions_401772891.json`)

Representative rows from drive 0:

| Play kind | `start.down` | `start.distance` | `downDistanceText` | `shortDownDistanceText` | `yardLine` / `yardsToEndzone` | `start.team.id` | `homeScore` / `awayScore` |
|-----------|-------------|------------------|--------------------|-------------------------|------------------------------|-----------------|---------------------------|
| Kickoff | `0` | `0` | — | — | `35` / `65` (kicking team) | `8` (DET) | present |
| 1st scrimmage | `1` | `10` | `1st & 10 at GB 17` | `1st & 10` | `83` / `83` | `9` (GB) | present |
| 3rd & 1 | `3` | `1` | `3rd & 1 at GB 47` | `3rd & 1` | `53` / `53` | `9` | present |
| Opp territory | `1` | `10` | `1st & 10 at DET 40` | `1st & 10` | `40` / `40` | `9` | present |

**Findings**

- Structured `down` / `distance` are usually present for scrimmage plays; kickoff uses `0` / `0` (not a scrimmage down).
- Text fields `downDistanceText` / `shortDownDistanceText` are rich fallbacks when structured fields are missing or invalid.
- **`yardLine` equals `yardsToEndzone`** on sampled scrimmage snaps: both are **yards to the opponent’s goal** (100 − value = yards from offense’s own goal). Drive-level `start` uses the same convention (`yardLine` 83 ↔ GB 17).
- `start.team` identifies **possession** for that play.
- Per-play `homeScore` / `awayScore` are present on this fixture; if absent, nothing should invent 0–0.

## 2. Where situation values are parsed

| Field | Parser | Default if missing |
|-------|--------|-------------------|
| Down / distance / raw yard line / team id / scores | `apply_espn_feed_presnap_fields` in `playcaller/live_data/espn_play_normalize.py` (~374–438) | **None** (omitted keys; no `replace`) |
| Core play categorization | `_espn_play_to_actual_core` (same module) | N/A — does not set situation |

**Gaps (pre-fix)**

- No parsing of `downDistanceText` / `shortDownDistanceText` when structured fields are absent.
- `feed_start_yard_line` stored **raw** ESPN `yardLine` (ytez-style on this API), not canonical `(territory, yardline 1–50)`.
- Structured `down == 0` (kickoff) was eligible to pollute feed down if not filtered.
- No `& Goal` handling from text.

## 3. Where down / distance are reconstructed

| Site | Role |
|------|------|
| `presnap_chain_for_drive_plays` / `advance_game_state_after_actual` in `playcaller/situation.py` | Advances down/distance/field after each **logged** play; builds per-play presnap chain for replay. |
| `previous_drive_replay._pre_snap_for_archived_index` → `build_pre_snap_record_for_archived_replay` | Previously passed **chain** into `PreSnapContextRecord` but **always** filled timing via resolver; situation came straight from chain with **no provenance**. |
| `previous_drive_replay._pre_snap_for_archived_index` | When `i >= len(chain)`, passed **`DEFAULT_START_*` (1, 10, own 25)** into the builder — **fake precision** for broken/partial chains. |

## 4. Field position derivation

- **Chain / `GameContext` model** (`situation.py` docstring, `yards_from_own_goal`, `_abs_to_territory_yardline`): `territory` ∈ `own` | `opponents`, `yardline` 1–50.
- **ESPN play JSON**: `yardLine` / `yardsToEndzone` are **not** already in that form; conversion belongs at **parse or resolve** time, not scattered in UI.
- **Risk**: Using raw `feed_start_yard_line` as if it were “yards deep in own territory” would be wrong (e.g. 83 vs own 17).

## 5. Score at snap

- **Archived replay rows**: `build_pre_snap_record_for_archived_replay` (`play_context.py` ~162–164) set `home_score_snap` / `away_score_snap` from **`play.feed_home_score` / `feed_away_score` only** — no threading when missing.
- **No** reconciled drive threading for per-play score in that path (mid-drive defensive scores would need future work).

## 6. Display layers

- `playcaller/ui/previous_drives_render.py`: `_compact_snap_context_line` (~338–397) reads **`PreSnapContextRecord`** only (down, distance, territory, yardline, scores, quarter/clock).
- `_render_comparison_breakdown` (~400–437) same object.
- **Divergence (pre-fix)**: Data in `PreSnapContextRecord` mixed **chain defaults** with **feed timing** without situation provenance — operator could not tell which was authoritative.

## 7. Duplicated resolution logic

- Timing: centralized in `resolve_archived_pre_snap_timing`.
- Situation: effectively **only** the presnap chain + hardcoded defaults when the chain ended — **not** unified with ESPN-first precedence.

## 8. Fake-precision patterns

- `previous_drive_replay.py` ~239–244: `chain_tuple = (DEFAULT_START_TERRITORY, DEFAULT_START_YARDLINE, DEFAULT_START_DOWN, DEFAULT_START_DISTANCE)` when `i >= len(chain)`.
- `play_context.py` `build_pre_snap_record_for_archived_replay` ~153–156: when `chain_tuple is None`, same defaults were applied to **`PreSnapContextRecord`** — masked unknowns.

---

**Conclusion:** Timing was disciplined; situation was chain + silent defaults. The fix extends **`play_context`** with ESPN-first situation resolution, canonical field position at parse time, optional `PreSnapContextRecord` fields, removal of non–first-play defaults, and UI formatting + provenance aligned with timing.
