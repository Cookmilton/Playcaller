"""
Operator-facing titles and section labels — single place for consistent product naming.

Internal keys (``game_id``, ``snap_review_log``) stay stable in JSON; this module is UI copy only.
"""

# --- App / browser -----------------------------------------------------------
PAGE_TITLE_MAIN = "Play Caller — Sideline OC"
PAGE_TITLE_HISTORY = "Play Caller — Game library"
PAGE_TITLE_REVIEW = "Play Caller — Post-game review"

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
SIDEBAR_SECTION_LIVE_GAME = "Live Game"
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
REVIEW_MESSAGE_STORED = (
    "**Stored model decisions found.** True snap-by-snap review (Generate-time output vs logged actual)."
)
REVIEW_MESSAGE_REPLAY = (
    "**No stored model decisions in this file.** Showing **replay analysis** — **current** model vs recorded plays "
    "(fully functional; not historical Generate truth)."
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
