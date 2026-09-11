"""Field diagram omits the default marker when field position is not synced."""

from playcaller.domain import GameContext
from playcaller.ui_components import render_field


def _ctx() -> GameContext:
    return GameContext(down=1, distance=10, yardline=25, territory="own")


def test_render_field_marker_when_synced() -> None:
    svg = render_field(_ctx(), show_spot=True)
    assert "1&amp;10" in svg
    assert "ellipse" in svg


def test_render_field_no_marker_when_not_synced() -> None:
    svg = render_field(_ctx(), show_spot=False)
    assert "1&amp;10" not in svg
    assert "ellipse" not in svg
    assert "OWN" in svg
