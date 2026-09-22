# ADR 001 — Live ESPN polling

## Status

Accepted for Phase H. The 15-second interval is provisional.

## Context

Sideline operators need the board to track a live ESPN game without clicking **Sync from ESPN** every play. Streamlit 1.56 can rerun a `@st.fragment(run_every=…)` independently of the full script. A mid-script `st.rerun()` still wipes unmirrored sidebar widgets (see `tests/test_mid_script_rerun.py`). `maybe_rerun_after_widgets` is the sole `st.rerun` site in the main script body.

Sunday captures (MNF `401872931` and the live `401872657` scoreboard/summary pair) show ESPN situation and drive payloads moving on a tens-of-seconds cadence, not every second. That is the evidence for starting at 15 seconds and retuning from later Sunday captures, not from a guessed interval.

## Decision

### Narrow fragment exemption

`run_live_polling_fragment` in `streamlit_app.py` is the single documented exemption to the “no `st.rerun` in the main script body” rule. The fragment body may only:

1. evaluate the activation guards (via `maybe_request_live_poll`);
2. if they all pass on a **timer tick**, set `LIVE_SYNC_REQUESTED` (with initiator `poll`);
3. call `st.rerun(scope="app")`.

It must not write a `ui_*` key, call `apply_snapshot`, or compute board state. The pre-widget `run_requested_live_sync` path consumes the flag on the next full app run — the same path as **Sync from ESPN**.

The fragment’s **inline** execution (the call that happens while it is declared on a full app run) is a no-op for reruns. Streamlit 1.56 distinguishes that from a `run_every` tick by `ScriptRunContext.fragment_ids_this_run` (`fragment.py:189`, set from `fragment_id_queue` at `script_runner.py:550-552`). AppTest never fills that queue (`local_script_runner.py:139-145`).

The fragment is declared **after** `populate_sidebar_export_slot` and **before** `maybe_rerun_after_widgets`, so an accidental inline rerun cannot fire before sidebar widgets have instantiated.

### Activation guards

All of these must pass before a poll may queue a sync:

- `UI_LIVE_POLLING_ENABLED` is on
- `sync_readiness_from_session(...).can_sync`
- the persisted game-final flag (`LIVE_FEED_LAST_IS_FINAL`) is not `True` (absent/unknown is `None`, and `None` does not block)
- `LIVE_FEED_LAST_ORIGIN` is not `"manual"`
- the **tail** `game.recommendation_audit` row is not `status == "open"` (same tail-only rule as `trim_stale_open_audits`)

### 15-second provisional interval

`POLL_INTERVAL_SECONDS = 15` is the only place the cadence is defined. Sunday’s captures are the evidence for that starting value. Changing the interval is a one-line diff; retune from later Sunday captures, not from a second constant.

### Defer while a snap is open

An open tail audit row means the operator is mid-snap (Generate without a logged result). Polling would merge feed plays and hydrate the board under them. Defer until that row is closed, superseded, or trimmed.

### Force sync vs polling

**Force sync** (live console) and **Sync from ESPN** (sidebar) both call `request_live_sync()` — no new rerun site, no new sync path. They mark origin `feed`. **Force sync** is the prominent console control for “pull now”: it works whether polling is on or off, and it **ignores the polling guards**. That is the point of it.

**Mark manual** is not a third sync. It sets origin `manual` so a later poll cannot clobber operator edits. A poll-initiated `apply_snapshot` is passed `origin=None`; a manual / Force sync still passes `origin="feed"`.

### Kill switch

`UI_LIVE_POLLING_ENABLED` is a session-scoped toggle, default **off**, following `UI_WAREHOUSE_ADVISORY_ENABLED`. It is the mid-session kill switch — flip it without a redeploy.

## Rejected alternatives

1. **Hidden auto-click component** that synthesizes a click on **Sync from ESPN**. It would couple polling to widget identity, fight Streamlit’s button semantics, and still need a place to live in the script. The fragment + flag path reuses the existing pre-widget sync.
2. **Timed full-page `st.rerun()`** on an interval. A full-script timer either reruns from the top (expensive, and easy to fire mid-widget tree) or reintroduces the mid-script rerun that drops unmirrored sidebar keys. A fragment-scoped timer that only sets a flag, then requests one app-scope rerun, keeps `maybe_rerun_after_widgets` as the only main-body rerun.
