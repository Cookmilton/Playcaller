# Environment load order (warehouse / Play Caller)

## Canonical loader

| Location | Role |
|----------|------|
| `playcaller/env_bootstrap.py` | **Single** `load_dotenv(<repo>/.env)` implementation. |
| `playcaller/__init__.py` | Calls `ensure_repo_dotenv_loaded()` **before** any other `playcaller` imports. |

Any `import playcaller` or `from playcaller...` runs the bootstrap first, including Streamlit `pages/*.py` that never execute `streamlit_app.py` from the top on a given navigation.

## Streamlit entry (`streamlit_app.py`)

1. Stdlib: `logging`, `pathlib.Path`, `sys`.
2. `_ensure_repo_root_on_sys_path()` — only `sys.path`; **no** env reads.
3. Comment + `_REPO_ROOT` — path only.
4. Logger setup for `playcaller.streamlit`.
5. **First `playcaller` import** — `from playcaller.debug.env_check import check_warehouse_env` → runs `playcaller/__init__.py` → **`ensure_repo_dotenv_loaded()`** → then rest of package imports.
6. `check_warehouse_env` / INFO log (reads `os.environ` **after** dotenv).
7. `import streamlit` and remaining `playcaller.*` imports.

**Do not** add imports from `playcaller` (or `football_history_warehouse`) above step 5 without moving the first `playcaller` import up, or you risk using env-dependent code before `.env` is applied.

## Warehouse DB URL — where it is read

| Location | When | Notes |
|----------|------|--------|
| `football_history_warehouse/config/database.py` | `DatabaseConfig.from_env()`, `get_database_url()` | **Function** body — safe if caller imported after bootstrap. |
| `football_history_warehouse/api/app.py` | `lifespan` | **Runtime** — reads `FOOTBALL_WAREHOUSE_SQL_ECHO` at app startup. |
| `playcaller/debug/env_check.py` | `check_warehouse_env()` | **Function** — diagnostic. |
| `playcaller/warehouse/binding.py` | Functions using `os.environ.get` | **Function** — advisory IDs. |

No project module reads `FOOTBALL_WAREHOUSE_DATABASE_URL` at **import time** (module top-level).

## SQLite relative paths

| Mechanism | Behavior |
|-----------|----------|
| `normalize_warehouse_database_url()` / `DatabaseConfig` | File-based SQLite URLs with a **relative** database segment (e.g. `./warehouse.db`) are rewritten to an **absolute** path anchored at the **repository root** (directory containing `football_history_warehouse/`). |
| `:memory:` / PostgreSQL | Unchanged — no filesystem path to resolve. |

Engines, Alembic, and clients all receive the **normalized** URL from `DatabaseConfig` or `get_database_url()`. The dev sidebar / startup log show **`sqlite_resolved_path`** (absolute file) when the URL is file-based SQLite.

**Confirm locally:** `ls -la <path from log or dev panel>` (e.g. `ls -la ./warehouse.db` only matches if your shell cwd is the repo root and the file was created there before normalization; after normalization, trust the **absolute** path in the log).

## Non-Play Caller entry points

`football_history_warehouse` CLI / Uvicorn **do not** import `playcaller`; they do not run `env_bootstrap`. Use shell exports or run from an environment where the URL is already set.
