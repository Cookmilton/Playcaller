"""Pytest session setup.

Enables the hydrate/ui→game tripwire raise for every test. Production code reads a
module-level flag — it does not inspect ``sys.modules`` for pytest.
"""

from __future__ import annotations

import playcaller.streamlit_state.hydrate_tripwire as hydrate_tripwire

hydrate_tripwire.RAISE_ON_UI_TO_GAME_WHILE_HYDRATE_PENDING = True
