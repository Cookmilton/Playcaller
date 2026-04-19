# Drive archive + model replay + product naming

## What changed

### Rich “Actual” formatting

- **`format_actual_play_analysis_primary`** / **`format_actual_play_analysis_detail`** in `playcaller/actual_result.py` — category + detail (e.g. `Pass complete — …`, `Run — …`, sack / punt / FG / penalty paths).
- **`actual_play_structured_dict`** — `dataclasses.asdict` snapshot for JSON/analysis.
- Root **`playcaller`** package exports the above.

### Structured replay & comparison (analysis-ready)

- **`ActualVsReplayComparisonRow`** (`playcaller/replay/analysis_types.py`): `pre_snap_context`, actual summaries + `actual_structured_result`, `model_replay_summary`, `model_replay_structured` (`ModelReplayStructuredResult`: family, call name, bucket, run/pass, confidence, model id), `actual_run_pass` / `model_run_pass`, `run_pass_match`, `family_match`, chain/replay errors. **`to_dict()`** for pipelines / future Post-game review.
- **`comparison_rows_for_archived_drive`** (alias **`replay_rows_for_archived_drive`**) builds rows; helpers in `playcaller/replay/comparison.py`.

### Stronger pre-snap reconstruction

- **`best_presnap_chain_for_drive_plays`** tries touchback anchors **own 20 / 25 / 30 / 35**, picks the chain with the best error rank (full > TD mid-drive > advance failed). `PreSnapContextRecord.reconstruction_anchor` + notes document overlay vs history.

### UI

- **`playcaller/ui/previous_drives_render.py`** — `render_drive_archive_with_replay`: side-by-side **Actual** vs **Model replay *(current engine)***, badges (RP/family match), expander with **`row.to_dict()`** (not export, not historical model).
- **`playcaller/ui/helpers.py`** — delegates to render module.
- Section title: **Archived drives** (`product_copy.SECTION_DRIVE_ARCHIVE`).

### Naming / copy (`playcaller/ui/product_copy.py`)

- Centralized page/section strings; wired into `streamlit_app.py`, `main_console.py`, sidebar (app title, Presets, Quick adjust, Drive & session, Export), `pages/History_library.py` (**Play Caller — Game library**), `pages/Review_session.py` (**Play Caller — Post-game review**, **Post-game review** title, section headers).
- Sidebar: **Corpus nudge** (was Historical nudge); **Game library** in corpus help text.
- Main console: session expander **Session record (identity & export)**; copy distinguishes **snap review** vs **retroactive replay**.

## Files touched (high level)

| Area | Files |
|------|--------|
| Actual formatting | `playcaller/actual_result.py`, `playcaller/__init__.py` |
| Replay / comparison | `playcaller/replay/analysis_types.py`, `comparison.py`, `previous_drive_replay.py`, `replay/__init__.py` |
| UI | `playcaller/ui/previous_drives_render.py`, `helpers.py`, `product_copy.py`, `main_console.py`, `sidebar.py` |
| App / pages | `streamlit_app.py`, `pages/History_library.py`, `pages/Review_session.py` |
| Tests | `tests/test_previous_drive_replay.py`, `tests/test_actual_play_analysis_format.py` |

## Comparison object shape (for Review Session later)

Use **`ActualVsReplayComparisonRow.to_dict()`** or **`comparison_table_to_dicts(rows)`**. Distinguish:

- **Post-game review** timeline = stored **`snap_review_log`** / Generate-time model.
- **Drive archive model replay** = `model_replay_structured` here = **current** engine on reconstructed presnap only.

## Limitations

- Drive start is still **inferred** (touchback grid); overlay fields are **current console**, not per-snap history.
- **Retroactive replay** is explicitly **not** audit history and **not** exported in game JSON in this step.
- Core **recommend** scoring logic unchanged.

## Next step

- In **Post-game review**, optional panel: load `comparison_rows_for_archived_drive` for selected archived drive (same session) to contrast **Generate-time** audit vs **replay** side-by-side.
- Optional: persist operator-chosen drive start anchor on archive (would require export schema discussion).
