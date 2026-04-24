# Multi-season processed data — decision memo

**Context:** After ingesting **2025 regular season weeks 1–18** into `data/processed/2025/`, this document records storage math, git/Streamlit constraints, options, and a recommendation. **No multi-season ingest was run.**

## D1 — Storage projections (from observed 2025)

| Scope | Size (approx.) |
|--------|----------------|
| **2025 regular season processed** (`data/processed/2025/`) | **~72 MB** (observed post-ingest, Apr 2026) |
| **5 seasons** (linear extrapolation of same playbook density) | **~360 MB** |
| **10 seasons** | **~720 MB** |

*Assumption:* Rough linear scaling with seasons; real growth may differ (rule changes, play volume, optional fields).

## D2 — Git feasibility

- **2025 alone (~72 MB text JSON)** is trivially below common pain thresholds for clone/diff on developer machines.
- **~360 MB–720 MB** of many small JSON files starts to hurt **clone time**, **repo browser performance**, and **noisy diffs** if data is tracked in the main tree. Past **~1 GB** total repo size (code + data + history), git operations become noticeably sluggish for typical laptops; multi-season processed JSON can push there **without** other large assets.
- **Comfort threshold:** Staying **under a few hundred MB** of tracked processed data is usually fine; **multiple seasons at full granularity in plain git** is where teams typically reach for LFS, exclusion, or external storage.

## D3 — Streamlit Community Cloud

- Published app **runtime storage** is often quoted on the order of **~50 GB max** for Community Cloud (resource ceiling for the running app — *not* a git repo size limit).
- **Repository size** is not a separate hard “50 MB” cap in official docs; practical limits come from **GitHub** (e.g. **100 MB per file** push block**, **LFS** for larger blobs) and **clone/checkout** time on deploy. **Git LFS** works with Community Cloud but adds operational overhead (credits/large pulls per community reports).
- For this project: **verify `data/processed` is gitignored or shipped via another channel** before assuming Cloud will clone multi-season JSON.

## D4 — Alternatives if multi-season is pursued

1. **Git-tracked JSON (current pattern)** — simplest; best for one season or small corpora.
2. **Parquet (same folder layout)** — smaller files, faster scans; requires reader changes.
3. **`data/processed/` outside git + object storage (S3/R2)** — fetch/cache at runtime; repo stays small.
4. **Git LFS** for `data/processed/` — keeps git layout; pays LFS bandwidth/cost complexity.

## D5 — Recommender value curve

Tier-1 viability (% of distinct 5-field keys with ≥10 plays) **rises quickly** as weeks accumulate, then **diminishing returns** appear as many common situation tuples are already well sampled. Adding **five seasons** does **not** multiply Tier-1 density by 5×; new data mostly refines rare tuples and season-specific effects rather than unlocking a proportional number of new high-*n* cells.

*(Empirical snapshot from this repo after full 2025 ingest: Tier-1 viable share of distinct situation keys moved from **~19.5%** on a smaller pre-run corpus to **~72%** with all regular-season weeks loaded — diminishing returns are expected beyond this as tuples saturate.)*

## D6 — Recommendation

**Stay on git-tracked JSON for 2025 only. Revisit if and when recommender hit rates warrant more data.**

2025 regular-season processed data fits comfortably in a normal repo footprint; expanding to multiple seasons in-repo will approach git-unfriendly size and friction before the recommender’s marginal Tier-1 gain justifies it. When more years are needed, **plan a Stage 6: storage migration** (Parquet and/or object storage + deterministic fetch) before bulk-ingest additional seasons into git history.
