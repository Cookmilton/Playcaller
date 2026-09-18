"""G2.5: ui→game copy while hydrate is pending.

Production never raises — it logs and skips so feed/load ``game_*`` is not clobbered.
Under pytest, :mod:`tests.conftest` sets the module flag so a hit fails the test.
Do not sniff ``sys.modules`` for pytest.
"""

from __future__ import annotations

# Set True only from tests/conftest.py. Default False is the production path.
RAISE_ON_UI_TO_GAME_WHILE_HYDRATE_PENDING = False


class HydrateClobberError(RuntimeError):
    """``sync_backend_from_widgets`` ran while ``GAME_WIDGET_HYDRATE_PENDING`` was still set."""


def raise_on_hydrate_clobber() -> bool:
    """Whether a hydrate/ui→game tripwire hit should raise (tests) or warn-and-skip (prod)."""
    return bool(RAISE_ON_UI_TO_GAME_WHILE_HYDRATE_PENDING)
