"""Smoke tests for play-art figure builder (requires matplotlib)."""

from __future__ import annotations

from playcaller.library import PLAY_LIBRARY
from playcaller.play_art_render import build_play_art_figure


def test_build_play_art_pass_figure() -> None:
    play = PLAY_LIBRARY["quick_game"][0]
    fig = build_play_art_figure(play, "quick_game", "H")
    assert fig is not None
    import matplotlib.pyplot as plt

    plt.close(fig)


def test_build_play_art_run_figure() -> None:
    play = PLAY_LIBRARY["inside_zone"][0]
    fig = build_play_art_figure(play, "inside_zone", None)
    assert fig is not None
    import matplotlib.pyplot as plt

    plt.close(fig)
