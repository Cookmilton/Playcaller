"""
Backward-compatible re-exports for controller + UI text helpers.

Prefer ``playcaller.services.game_controller`` and ``playcaller.ui.helpers``.
"""

from playcaller.services.game_controller import (
    apply_and_rerun,
    archive_current_drive_and_reset_session,
    on_ui_weather_changed,
    preset_snap_only,
    preset_two_minute_drill,
    run_generate_if_requested,
    sync_wind_slider_with_weather_pre_widgets,
    undo_last_logged_play,
)
from playcaller.ui.helpers import (
    LOG_OUTCOME_AUTO,
    LOG_OUTCOME_OPTIONS,
    LOG_TARGET_AUTO,
    LOG_TARGET_OPTIONS,
    _LOG_COMPLETE,
    _LOG_FG_GOOD,
    _LOG_FG_MISS,
    _LOG_RUN,
    fmt_local_epoch,
    net_yards_to_endzone,
    ordinal_down,
    post_log_summary_and_toast,
    render_current_series_live,
    render_previous_drives,
    safe_summary_html,
)

__all__ = [
    "LOG_OUTCOME_AUTO",
    "LOG_OUTCOME_OPTIONS",
    "LOG_TARGET_AUTO",
    "LOG_TARGET_OPTIONS",
    "_LOG_COMPLETE",
    "_LOG_FG_GOOD",
    "_LOG_FG_MISS",
    "_LOG_RUN",
    "apply_and_rerun",
    "archive_current_drive_and_reset_session",
    "fmt_local_epoch",
    "net_yards_to_endzone",
    "on_ui_weather_changed",
    "ordinal_down",
    "post_log_summary_and_toast",
    "preset_snap_only",
    "preset_two_minute_drill",
    "render_current_series_live",
    "render_previous_drives",
    "run_generate_if_requested",
    "safe_summary_html",
    "sync_wind_slider_with_weather_pre_widgets",
    "undo_last_logged_play",
]
