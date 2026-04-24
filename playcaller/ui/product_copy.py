"""
Operator-facing titles and section labels — single place for consistent product naming.

Internal keys (``game_id``, ``snap_review_log``) stay stable in JSON; this module is UI copy only.
"""

# --- App / browser -----------------------------------------------------------
PAGE_TITLE_MAIN = "Play Caller — Sideline OC"
PAGE_TITLE_HISTORY = "Play Caller — Game library"
PAGE_TITLE_REVIEW = "Play Caller — Post-game review"
PAGE_TITLE_WAREHOUSE = "Play Caller — Warehouse"

# --- Main console ------------------------------------------------------------
HEADLINE_MAIN = "Play Caller — Sideline OC"
HEADLINE_LIVE_CONSOLE = "Live console"
EXPANDER_SESSION_RECORD = "Session record (identity & export)"
SECTION_DRIVE_ARCHIVE = "Archived drives"
SECTION_CURRENT_SERIES = "Current series"
CAPTION_POST_DRIVE_REPLAY = (
    "**Model replay** applies the **current** predictor to each **reconstructed** pre-snap. "
    "It is not what the model said at game time and is **not** written to exports or snap review."
)

# --- Sidebar -----------------------------------------------------------------
SIDEBAR_APP_TITLE = "Play Caller"
SIDEBAR_SECTION_SESSION = "Session"
SIDEBAR_SECTION_WAREHOUSE = "Warehouse (history DB)"
SIDEBAR_SECTION_LIVE_GAME = "Live Game"
# st.expander labels (exact strings — single source for sidebar.py)
SIDEBAR_SECTION_GAME_SETUP = "🎮  GAME SETUP"
SIDEBAR_SECTION_LIVE_SYNC = "📡  LIVE SYNC"
SIDEBAR_SECTION_PLAY_CALLS_EXPANDER = "🎯  PLAY CALLS"
SIDEBAR_SECTION_REVIEW_EXPORT_EXPANDER = "📋  REVIEW & EXPORT"
# Inner subsection headings (markdown inside expanders)
SIDEBAR_SECTION_PLAY_CALLS = "Play Calls"
SIDEBAR_SECTION_REVIEW_EXPORT = "Review & Export"
SIDEBAR_SECTION_ADVANCED = "Advanced"
SIDEBAR_SECTION_PRESETS = "Presets"
SIDEBAR_SECTION_QUICK_ADJUST = "Quick adjust"
SIDEBAR_SECTION_DRIVE_SESSION = "Drive & session"
SIDEBAR_SECTION_EXPORT = "Export"
SIDEBAR_CAPTION_EXPORT_REVIEW = (
    "Exports list **`snap_review_log`** first (then `recommendation_audit`). "
    "Files **with** that timeline support **full stored review**; files **without** it still support **replay review** "
    "when drives include logged plays."
)

# --- Review page (pages/Review_session.py) -----------------------------------
REVIEW_PAGE_TITLE = "Post-game review"
REVIEW_SECTION_SOURCE = "Review source"
REVIEW_SECTION_SESSION_RECORD = "Session record"
REVIEW_SECTION_OVERVIEW = "Game overview"
REVIEW_SECTION_DRIVE = "Drive summaries"
REVIEW_SECTION_PATTERNS = "Patterns & takeaways"
REVIEW_SECTION_SNAP = "Snap timeline & detail"
REVIEW_SECTION_REFERENCE = "Technical reference"
REVIEW_SECTION_FILM_ROOM = "Film room — play-by-play"
REVIEW_MODE_LABEL_TRUE = "Stored review (snap review log)"
REVIEW_MODE_LABEL_LEGACY = "Stored review (legacy audit export)"
REVIEW_MODE_LABEL_REPLAY = "Replay review (current model vs actual)"
REVIEW_MODE_LABEL_WAREHOUSE = "Warehouse history (actual-only)"
REVIEW_MESSAGE_STORED = (
    "**Stored model decisions found.** True snap-by-snap review (Generate-time output vs logged actual)."
)
REVIEW_MESSAGE_REPLAY = (
    "**No stored model decisions in this file.** Showing **replay analysis** — **current** model vs recorded plays "
    "(fully functional; not historical Generate truth)."
)
REVIEW_MESSAGE_WAREHOUSE = (
    "**Processed nflverse game** — play cards show **actual** situations and outcomes only. "
    "There is **no** model call to grade against in this source."
)
REVIEW_CAPTION_WAREHOUSE_MODEL_PANELS = (
    "**Historical source:** coaching and model diagnostic panels stay empty by design — there were no live predictions for this game."
)
REVIEW_WAREHOUSE_EMPTY_PROCESSED = (
    "No processed games found under **data/processed/**. From the repo root, run for example "
    "**`python -m warehouse.pipeline 2025 1`** (or **`python3 -m warehouse.bulk --season 2025 --weeks 1`** for checkpointed bulk), "
    "then reopen this page."
)
REVIEW_MESSAGE_NONE = "**No plays available to review.** Log plays or export a session with a snap timeline."
REVIEW_SECTION_ARCHIVED_REPLAY = "Archived drive: Generate-time vs model replay"
REVIEW_CAPTION_ARCHIVED_REPLAY = (
    "Compare **`snap_review_log`** (what the engine said at **Generate** time) with **retroactive** "
    "replay rows from the **current** model. Each **`play_index`** lines up with **`plays_at_recommend + 1`** "
    "on the audit row. Replay uses reconstructed pre-snap positions and your **current** sidebar overlay "
    "(defense, weather, clock) — same idea as **Archived drives** on the main console."
)

# --- History / library page --------------------------------------------------
HISTORY_PAGE_TITLE = "Game library"

# --- Warehouse inventory page -----------------------------------------------
WAREHOUSE_PAGE_INTRO = (
    "Read-only inventory of **games stored in the football history warehouse** (separate SQLite/DB). "
    "Use this to confirm imports before relying on **warehouse advisory** on Generate."
)
WAREHOUSE_ADVISORY_SIDEBAR_CAPTION = (
    "**Warehouse advisory** adds historical **context** on Generate (outcomes, tendencies, similar plays). "
    "It does **not** change ranked play-family scores. For score nudges from your corpus, use **Historical nudge** in Advanced."
)

WAREHOUSE_STATUS_ACTION_NOT_CONFIGURED = (
    "Set FOOTBALL_WAREHOUSE_DATABASE_URL in .env to enable warehouse advisory, "
    "or set PLAYCALLER_DEV_MODE=1 to use the local ./warehouse.db SQLite fallback (dev only)."
)
WAREHOUSE_STATUS_DOC_HINT = (
    "Docs: docs/ENV_LOAD_ORDER.md (environment load order and SQLite path resolution)."
)
WAREHOUSE_STATUS_ACTION_SCHEMA = (
    "Initialize the schema with Alembic: "
    "python -c \"from football_history_warehouse.storage.bootstrap import upgrade_to_head; upgrade_to_head()\" "
    "from the repo root with FOOTBALL_WAREHOUSE_DATABASE_URL set. "
    "The ESPN warehouse import CLI runs migrations before loading data."
)
WAREHOUSE_STATUS_ACTION_EMPTY = (
    "No games archived yet. Sync a game through the warehouse import flow (e.g. ESPN summary import) to populate."
)
WAREHOUSE_STATUS_ACTION_QUERY_FAILED = (
    "Fix the database file or URL, re-run migrations if needed, then reload this page."
)
