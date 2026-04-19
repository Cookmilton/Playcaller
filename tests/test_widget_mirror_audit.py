"""Registry consistency: sidebar ``ui_*`` keys vs ``GAME_UI_MIRROR_PAIRS``."""

from playcaller.streamlit_state.widget_backend_bridge import development_mirror_audit_messages


def test_sidebar_mirror_registry_has_no_issues() -> None:
    assert development_mirror_audit_messages() == []
