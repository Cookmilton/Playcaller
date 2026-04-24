"""
streamlit_app.py — Football Play Predictor — Streamlit visual interface

Run with:
    streamlit run streamlit_app.py

After you change ``.env`` or env-loading code, stop and restart that Streamlit process so
``ensure_repo_dotenv_loaded`` runs again — refreshing the browser alone does not reload environment variables.

Install deps:
    pip install -r requirements.txt

The `playcaller` package lives next to this file (directory `playcaller/`, not `playcaller.py`).
Streamlit Cloud and some local runs do not guarantee the repo root on ``sys.path`` before
importing the main script, so we add it explicitly below.
"""

import logging
from pathlib import Path
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def _ensure_repo_root_on_sys_path() -> None:
    """Make `import playcaller` reliable on Streamlit Cloud and odd working directories."""
    root = Path(__file__).resolve().parent
    s = str(root)
    if s not in sys.path:
        sys.path.insert(0, s)


_ensure_repo_root_on_sys_path()

# Repo ``.env`` is loaded inside ``playcaller`` on first import (``env_bootstrap``), before
# other ``playcaller`` submodules. Do not move local imports above the first ``playcaller`` import
# or add a second ``load_dotenv`` — order matters for ``FOOTBALL_WAREHOUSE_DATABASE_URL``.
_REPO_ROOT = Path(__file__).resolve().parent

_log = logging.getLogger("playcaller.streamlit")
_log.setLevel(logging.INFO)
if not _log.handlers:
    _h = logging.StreamHandler()
    _h.setLevel(logging.INFO)
    _h.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    _log.addHandler(_h)
_log.propagate = False

from playcaller.debug.env_check import check_warehouse_env

_wh_env = check_warehouse_env(repo_root=_REPO_ROOT)
if _wh_env["present"]:
    _log.info(
        "FOOTBALL_WAREHOUSE_DATABASE_URL present source=%s scheme=%s masked=%s",
        _wh_env["source"],
        _wh_env.get("scheme"),
        _wh_env.get("masked_value"),
    )
    sp = _wh_env.get("sqlite_resolved_path")
    if sp:
        _log.info("Warehouse SQLite database file (absolute): %s", sp)
else:
    _log.info("FOOTBALL_WAREHOUSE_DATABASE_URL not set in process environment")

import streamlit as st

from playcaller import DriveLogger, FootballPlayPredictor, Game, GameContext
from playcaller.game_situation_input import context_quarter_from_period, score_diff_from_board
from playcaller.evaluation.snap_review_lifecycle import ensure_snap_review_list_on_game
from playcaller.services.game_controller import sync_wind_slider_with_weather_pre_widgets
from playcaller.streamlit_state.keys import (
    GAME_CLOCK_TOTAL_SECONDS,
    GAME_CONTEXT_QUARTER,
    GAME_SCORE_OURS,
    GAME_SCORE_THEIRS,
)
from playcaller.streamlit_state.pending import apply_all_pending
from playcaller.streamlit_state.session import ensure_play_caller_session_defaults
from playcaller.streamlit_state.ui_defaults import new_game_ui_values
from playcaller.streamlit_state.ui_write_guard import reset_ui_write_guard
from playcaller.streamlit_state.session_setup import apply_session_setup_widgets_to_game
from playcaller.streamlit_state.widget_backend_bridge import (
    log_development_mirror_audit,
    reconcile_widget_and_backend_state,
    refresh_derived_game_context_cache,
    sync_backend_from_widgets,
)
from playcaller.ui.main_console import render_main_content
from playcaller.ui.sidebar import populate_sidebar_export_slot, render_sidebar

st.set_page_config(
    page_title="Play Caller",
    page_icon="🏈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  .block-container { padding-top: 1.5rem; }
  .stMetric label { font-size: 0.7rem !important; text-transform: uppercase; letter-spacing: 0.06em; }
  div[data-testid="column"] button { padding-top: 0.35rem; padding-bottom: 0.35rem; }
  section[data-testid="stSidebar"] button[kind="primary"] {
    background-color: #C8102E !important;
    border-color: #C8102E !important;
    color: #ffffff !important;
  }
</style>
""", unsafe_allow_html=True)

# ── Session state ────────────────────────────────────────────────────────────

reset_ui_write_guard()

# Session / Game ordering (avoid metadata drift): defaults → pending merges → push session-setup
# widgets onto ``game`` before sidebar, export, ESPN, or audit paths read ``session_metadata``.
def _init_session_state() -> None:
    """Declare session defaults in one place (cold start and widget key safety)."""
    ensure_play_caller_session_defaults(st.session_state)


_init_session_state()

# Merge pending UI before any ``key="ui_*"`` widgets render (Streamlit forbids mutating widget keys mid-run).
apply_all_pending(st.session_state)
# ``game_*`` backend mirrors ↔ ``ui_*`` (hydrate after ESPN / load JSON, else push widgets → backend).
reconcile_widget_and_backend_state(st.session_state)
log_development_mirror_audit()

predictor = st.session_state.predictor
drive_log = st.session_state.drive_log
game = st.session_state.game
ensure_snap_review_list_on_game(game)
apply_session_setup_widgets_to_game(game, st.session_state)
# Possession from the sidebar radio (prior run's value). Applied here so **New drive** / captions see it.
game.possession = (
    "offense" if str(st.session_state.get("ui_possession_side", "Our team")) == "Our team" else "defense"
)

# Wind: sync before sidebar + ``on_change`` on weather when leaving "wind" (see ``game_controller``).
sync_wind_slider_with_weather_pre_widgets()

sidebar_generate, sidebar_export_slot = render_sidebar(game=game, drive_log=drive_log)

# Sidebar may replace ``st.session_state.game`` (e.g. **Load game JSON** without rerun in edge paths).
# Always re-bind so Generate / Log / Export mutate and read the **same** object as session state.
game = st.session_state.game
ensure_snap_review_list_on_game(game)
drive_log = st.session_state.drive_log
apply_session_setup_widgets_to_game(game, st.session_state)
game.possession = (
    "offense" if str(st.session_state.get("ui_possession_side", "Our team")) == "Our team" else "defense"
)

# Copy operator edits into ``game_*`` (safe: only non-widget backend keys are written).
sync_backend_from_widgets(st.session_state)
refresh_derived_game_context_cache(st.session_state)

# Pull the latest UI state (``.get`` mirrors :func:`new_game_ui_values` so missing keys never 500).
_ui = new_game_ui_values()
down = int(st.session_state.get("ui_down", _ui["ui_down"]))
distance = int(st.session_state.get("ui_distance", _ui["ui_distance"]))
territory = str(st.session_state.get("ui_territory", _ui["ui_territory"]))
yardline = int(st.session_state.get("ui_yardline", _ui["ui_yardline"]))
def_personnel = str(st.session_state.get("ui_def_personnel", _ui["ui_def_personnel"]))
box_count = int(st.session_state.get("ui_box_count", _ui["ui_box_count"]))
coverage_shell = str(st.session_state.get("ui_coverage_shell", _ui["ui_coverage_shell"]))
safeties = str(st.session_state.get("ui_safeties", _ui["ui_safeties"]))
blitz_likely = bool(st.session_state.get("ui_blitz_likely", _ui["ui_blitz_likely"]))
period = int(st.session_state.get("ui_game_period", 1))
quarter = int(st.session_state.get(GAME_CONTEXT_QUARTER, context_quarter_from_period(period)))
seconds_remaining = int(st.session_state.get(GAME_CLOCK_TOTAL_SECONDS, 0))
# Scoreboard: backend mirrors updated from widgets above (and by ESPN / load before hydrate).
game.offense_points = int(st.session_state.get(GAME_SCORE_OURS, 0))
game.defense_points = int(st.session_state.get(GAME_SCORE_THEIRS, 0))
score_diff = score_diff_from_board(our_score=game.offense_points, their_score=game.defense_points)
game.quarter = quarter
game.clock_seconds_remaining = seconds_remaining
own_timeouts = int(st.session_state.get("ui_own_tos", _ui["ui_own_tos"]))
opp_timeouts = int(st.session_state.get("ui_opp_tos", _ui["ui_opp_tos"]))
weather = str(st.session_state.get("ui_weather", _ui["ui_weather"]))
wind_mph = int(st.session_state.get("ui_wind_mph", _ui["ui_wind_mph"])) if weather == "wind" else 0
qb_limited = bool(st.session_state.get("ui_qb_limited", _ui["ui_qb_limited"]))
game_mode = str(st.session_state.get("ui_game_mode", _ui["ui_game_mode"]))
mismatch = str(st.session_state.get("ui_mismatch", _ui["ui_mismatch"]))

ctx = GameContext(
    down=down, distance=distance, yardline=yardline, territory=territory,
    def_personnel=def_personnel, box_count=box_count, coverage_shell=coverage_shell,
    blitz_likely=blitz_likely, safeties=safeties,
    score_diff=score_diff, quarter=quarter, seconds_remaining=seconds_remaining,
    own_timeouts=own_timeouts, opp_timeouts=opp_timeouts,
    weather=weather, wind_mph=wind_mph, qb_limited=qb_limited,
    mismatch=mismatch or None, game_mode=game_mode,
    plays_this_drive=len(drive_log.results),
    shown_concepts=list(drive_log.family_counts.keys()),
    run_plays_this_drive=drive_log.run_count(),
)

render_main_content(
    ctx=ctx,
    game=game,
    drive_log=drive_log,
    predictor=predictor,
    sidebar_generate=sidebar_generate,
)
populate_sidebar_export_slot(sidebar_export_slot)
