"""
History library UI: persistent ingest, indexed metadata, and situation matching (validation).

Repository persistence is implemented in ``playcaller.history``; this module is Streamlit wiring.
"""

from __future__ import annotations

from typing import Any, List, Mapping, Optional

import streamlit as st

from playcaller.history import (
    HistoryCorpus,
    IngestReport,
    SimilarSituationResult,
    attach_outcome_summary,
    ingest_directory,
    ingest_file_bytes,
    ingest_zip_bytes,
    list_game_records,
    load_history_directory,
    load_history_repository_settings,
    query_similar_plays_from_context,
    read_manifest,
    resolve_history_repository_root,
    result_to_debug_dict,
    update_game_record_fields,
)
from playcaller.history.buckets import situation_signature_from_context
from playcaller.history.library_display import (
    aggregate_ingest_reports,
    build_library_table_row,
    compact_context_lines,
    duplicate_hint_for_new_imports,
    filter_game_records,
    human_readable_game_title,
    import_batches_by_id,
    session_game_id_duplicate_repo_ids,
    sort_games_for_library,
    sorted_distinct_str,
)
from playcaller.history.normalize import derive_play_success
from playcaller.history.outcome_aggregates import CAUTION_N, OutcomeTotals, VERY_SMALL_N
from playcaller.history.repository_corpus import load_repository_plays
from playcaller.streamlit_state.keys import (
    HV_CORPUS_SOURCE,
    HV_REPO_SELECTED_GAME_IDS,
    HV_REPO_USE_ALL_GAMES,
    HV_SESSION_CORPUS_KEY,
    HV_SESSION_CORPUS_PATH_KEY,
)
from playcaller.ui.live_session_context import build_game_context_from_session_state
from playcaller.ui.product_copy import HISTORY_PAGE_TITLE

_SESSION_LAST_INGEST = "hv_history_last_ingest_summary"

_CORPUS_SOURCE_LABELS = {
    "folder_session": "Folder → session (legacy)",
    "repository": "Repository (persistent)",
}


def _pct(x: Optional[float]) -> str:
    if x is None:
        return "—"
    return f"{100.0 * float(x):.1f}%"


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


def _success_cell(row_play_success: Optional[bool], derived: Optional[bool]) -> str:
    if row_play_success is not None:
        return "Y" if row_play_success else "N"
    if derived is not None:
        return "Y (est.)" if derived else "N (est.)"
    return "—"


def _tier_step_explanation(tier_name: str, step: Mapping[str, Any]) -> str:
    parts: List[str] = []
    if step.get("relax_distance"):
        parts.append("distance bucket neighborhood (adjacent to-go bands allowed)")
    if step.get("relax_field"):
        parts.append("field zone neighborhood (adjacent field bands allowed)")
    ytol = int(step.get("yardline_tolerance") or 0)
    if ytol > 0:
        parts.append(f"yardline band within ±{ytol} yards of the query (in addition to zones)")
    if not parts:
        parts.append("strict buckets only (no neighbor widening; yardline filter off)")
    return f"**{tier_name}:** " + "; ".join(parts) + "."


def _fallback_banner(result: SimilarSituationResult) -> None:
    trace = result.trace
    tier = str(result.tier or "")
    min_req = int(trace.get("min_matches_requested") or 0)
    n = len(result.matches)
    tiers_tried = trace.get("tiers_tried") or []
    selected = next((t for t in tiers_tried if str(t.get("tier")) == tier), None)

    if tier == "strict" and n < min_req:
        st.warning(
            f"**Strict buckets** matched **{n}** play(s), below the requested minimum (**{min_req}**). "
            "Showing the best available strict-tier slice — rates are **low confidence**."
        )
        return

    if tier != "strict":
        st.warning(
            "**Exact strict bucket match did not reach the target sample (or a wider tier yielded more matches).** "
            f"Using widened tier **`{tier}`**."
        )
        if selected:
            st.caption(_tier_step_explanation(tier, selected))
        first = tiers_tried[0] if tiers_tried else None
        if first and str(first.get("tier")) == "strict":
            st.caption(
                f"Strict tier had **{int(first.get('match_count') or 0)}** match(es) before widening."
            )
        return

    st.success("Using **strict** similarity tier (no bucket widening; yardline tolerance 0).")


def _sample_confidence_note(overall: OutcomeTotals) -> None:
    n = overall.n
    if n == 0:
        return
    caveats = list(overall.caveats)
    if n < VERY_SMALL_N:
        st.error(
            f"**Very small sample (n={n}).** Treat all rates as illustrative; one play moves percentages sharply."
        )
    elif n < CAUTION_N:
        st.warning(
            f"**Modest sample (n={n}).** Use rates as directional hints; wide confidence intervals."
        )
    for c in caveats:
        st.caption(c)


def _render_lane_card(title: str, ot: Optional[OutcomeTotals]) -> None:
    st.markdown(f"**{title}**")
    if ot is None or ot.n == 0:
        st.caption("No plays in this lane.")
        return
    c1, c2 = st.columns(2)
    with c1:
        st.metric("n", ot.n)
        st.metric("Success", _pct(ot.success_rate))
    with c2:
        st.metric("Avg yards", f"{ot.mean_yards:.1f}")
        st.metric("Turnover rate", _pct(ot.turnover_rate))
    for c in ot.caveats:
        st.caption(c)


def _resolve_validation_corpus(ss: Mapping[str, Any], repo_root) -> Optional[HistoryCorpus]:
    src = str(ss.get(HV_CORPUS_SOURCE) or "folder_session")
    if src == "repository":
        use_all = bool(ss.get(HV_REPO_USE_ALL_GAMES, True))
        raw_ids = ss.get(HV_REPO_SELECTED_GAME_IDS)
        ids = [str(x) for x in raw_ids] if isinstance(raw_ids, list) else []
        plays = load_repository_plays(
            repo_root,
            repo_game_ids=ids,
            use_all_games=use_all,
        )
        if plays:
            return HistoryCorpus(
                plays=plays,
                games=[],
                errors=[],
                notes=[f"Repository corpus: {len(plays)} normalized plays loaded."],
            )
    corp = ss.get(HV_SESSION_CORPUS_KEY)
    if isinstance(corp, HistoryCorpus):
        return corp
    return None


def _store_ingest_summary(ss: Mapping[str, Any], reports: List[IngestReport], repo_root) -> None:
    agg = aggregate_ingest_reports(reports)
    games = list_game_records(repo_root)
    newest = set(agg["game_repo_ids"])
    dup_hint = duplicate_hint_for_new_imports(games, newest)
    ss[_SESSION_LAST_INGEST] = {
        "files_found": agg["files_found"],
        "files_imported": agg["files_imported"],
        "files_rejected": agg["files_rejected"],
        "new_games": len(agg["game_repo_ids"]),
        "warnings": list(agg["warnings"]),
        "rejected": agg["rejected"][:40],
        "duplicate_hint": dup_hint,
    }


def _render_last_ingest_banner(ss: Mapping[str, Any]) -> None:
    summary = ss.get(_SESSION_LAST_INGEST)
    if not isinstance(summary, dict):
        return
    msg_col, dismiss_col = st.columns((5, 1))
    with dismiss_col:
        if st.button(
            "Dismiss summary",
            key="hv_dismiss_last_ingest_summary",
            help="Hide this import result from the page. The repository is unchanged; a new import shows a fresh summary.",
        ):
            ss.pop(_SESSION_LAST_INGEST, None)
            st.rerun()
    found = int(summary.get("files_found", 0) or 0)
    imp = int(summary.get("files_imported", 0) or 0)
    rej = int(summary.get("files_rejected", 0) or 0)
    new_g = int(summary.get("new_games", 0) or 0)
    with msg_col:
        if found == 0:
            st.info("**Last import:** no JSON files were found in the selection.")
        elif imp == 0:
            st.error(
                f"**Last import:** **0** imported of **{found}** file(s) found — see rejections below."
            )
        elif rej > 0:
            st.warning(
                f"**Last import (partial):** **{imp}** imported, **{rej}** rejected, "
                f"**{new_g}** new game index entr(y/ies) (from **{found}** file(s))."
            )
        else:
            st.success(
                f"**Last import:** **{imp}** file(s) imported from **{found}** found · "
                f"**{new_g}** new game index entr(y/ies)."
            )
    wn = summary.get("warnings") or []
    if wn:
        with st.expander("Validation notes from last import", expanded=True):
            for w in wn[:25]:
                st.caption(str(w))
    rj = summary.get("rejected") or []
    if rj:
        with st.expander("Rejected files (last import)", expanded=False):
            for name, reason in rj:
                st.text(f"{name}: {reason}")
    dh = summary.get("duplicate_hint")
    if dh:
        st.info(dh)


def _render_import_tab(repo_root, settings) -> None:
    st.markdown("### Import")
    st.caption(
        "Add former game JSON exports into your **local repository**. Raw files and normalized play rows are stored "
        f"under **`{repo_root}`** (override with env **`PLAYCALLER_HISTORY_REPO`**)."
    )

    _render_last_ingest_banner(st.session_state)

    st.markdown("#### Upload files")
    st.caption("Upload **one or more `.json`** files and/or a **`.zip`** of JSON exports, then run ingest.")

    st.text_input("Optional batch note (saved on the import record in `manifest.json`)", key="hv_import_note")

    uploaded = st.file_uploader(
        "JSON / ZIP",
        type=["json", "zip"],
        accept_multiple_files=True,
        key="hv_upload_batch",
        help="ZIP entries ending in `.json` are ingested. Nested paths are flattened for storage names.",
    )

    if st.button("Import uploads into repository", type="primary", key="hv_ingest_upload_btn"):
        note = str(st.session_state.get("hv_import_note") or "").strip()
        if not uploaded:
            st.warning("Choose at least one file.")
        else:
            batch_reports: List[IngestReport] = []
            json_pairs: List[tuple[str, bytes]] = []
            for uf in uploaded:
                raw = uf.getvalue()
                if uf.name.lower().endswith(".zip"):
                    batch_reports.append(ingest_zip_bytes(repo_root, raw, label=note))
                else:
                    json_pairs.append((uf.name, raw))
            if json_pairs:
                batch_reports.append(ingest_file_bytes(repo_root, json_pairs, source_kind="upload", label=note))
            if batch_reports:
                _store_ingest_summary(st.session_state, batch_reports, repo_root)
            st.rerun()

    st.divider()
    st.markdown("#### Optional: folder on disk")
    with st.expander("Ingest from a directory on this machine (not an upload)", expanded=False):
        path = st.text_input(
            "Directory path",
            placeholder="~/exports/game_json",
            key="hv_history_dir",
            help="Reads `*.json` from this path where Streamlit runs.",
        )
        recursive = st.checkbox("Include subfolders (`*.json`)", value=False, key="hv_recursive_disk")
        note2 = str(st.session_state.get("hv_import_note") or "").strip()
        if st.button("Import folder into repository", key="hv_ingest_folder_repo_btn"):
            root = (path or "").strip()
            if not root:
                st.warning("Enter a directory path.")
            else:
                rep = ingest_directory(
                    repo_root,
                    root,
                    recursive=bool(recursive),
                    max_json_files=settings.max_json_files,
                    label=note2,
                )
                _store_ingest_summary(st.session_state, [rep], repo_root)
                st.rerun()


def _render_library_tab(repo_root) -> None:
    st.markdown("### Library")
    manifest = read_manifest(repo_root)
    batches = import_batches_by_id(manifest)
    games_raw = [g for g in list_game_records(repo_root) if isinstance(g, dict)]
    dup_repo_ids = session_game_id_duplicate_repo_ids(games_raw)

    st.markdown("#### Browse & filter")
    if not games_raw:
        st.info("No games in the index yet — use **Import** to add JSON exports.")
        return

    with st.expander("Search & filters", expanded=False):
        q1, q2 = st.columns(2)
        with q1:
            st.text_input("Search (title, teams, file, tags, ids)", key="hv_lib_search")
        with q2:
            st.selectbox(
                "Sort",
                options=["imported_desc", "date_desc", "date_asc", "title_asc"],
                format_func=lambda m: {
                    "imported_desc": "Newest import first",
                    "date_desc": "Game date (newest)",
                    "date_asc": "Game date (oldest)",
                    "title_asc": "Title A–Z",
                }[m],
                key="hv_lib_sort",
            )
        teams = sorted_distinct_str([str(g.get("team") or "") for g in games_raw])
        opps = sorted_distinct_str([str(g.get("opponent") or "") for g in games_raw])
        seasons = sorted_distinct_str([str(g.get("season") or "") for g in games_raw])
        rosters = sorted_distinct_str([str(g.get("roster_id") or "") for g in games_raw])
        imp_opts = [str(imp.get("import_id") or "") for imp in (manifest.get("imports") or []) if isinstance(imp, dict)]
        imp_opts = [x for x in imp_opts if x]
        c1, c2, c3 = st.columns(3)
        with c1:
            st.selectbox("Team", options=["", *teams], format_func=lambda x: x or "Any", key="hv_lib_team")
            st.selectbox("Opponent", options=["", *opps], format_func=lambda x: x or "Any", key="hv_lib_opp")
        with c2:
            st.selectbox("Season", options=["", *seasons], format_func=lambda x: x or "Any", key="hv_lib_season")
            st.selectbox("Roster id", options=["", *rosters], format_func=lambda x: x or "Any", key="hv_lib_roster")
        with c3:
            st.selectbox(
                "Validation",
                options=["all", "ok", "warnings"],
                format_func=lambda x: {"all": "Any", "ok": "OK only", "warnings": "Has warnings"}[x],
                key="hv_lib_val",
            )
            st.selectbox(
                "Import batch",
                options=["", *imp_opts],
                format_func=lambda x: (
                    (
                        str(batches[x].get("created_at_iso", ""))[:19].replace("T", " ")
                        + f" · {batches[x].get('source_kind', '')}"
                    )
                    if x and x in batches
                    else "Any batch"
                ),
                key="hv_lib_import",
            )
        st.text_input("Tag contains", key="hv_lib_tag")
        st.checkbox("Only possible duplicate session ids", key="hv_lib_dup_only")

    search = str(st.session_state.get("hv_lib_search") or "")
    filtered = filter_game_records(
        games_raw,
        search=search,
        team=str(st.session_state.get("hv_lib_team") or ""),
        opponent=str(st.session_state.get("hv_lib_opp") or ""),
        season=str(st.session_state.get("hv_lib_season") or ""),
        roster=str(st.session_state.get("hv_lib_roster") or ""),
        validation=str(st.session_state.get("hv_lib_val") or "all"),
        import_id=str(st.session_state.get("hv_lib_import") or ""),
        tag=str(st.session_state.get("hv_lib_tag") or ""),
        duplicates_only=bool(st.session_state.get("hv_lib_dup_only")),
        duplicate_repo_ids=dup_repo_ids,
    )
    sort_mode = str(st.session_state.get("hv_lib_sort") or "imported_desc")
    filtered_sorted = sort_games_for_library(filtered, batches=batches, sort_mode=sort_mode)

    m1, m2, m3 = st.columns(3)
    with m1:
        st.metric("Indexed games", len(games_raw))
    with m2:
        st.metric("Shown (after filters)", len(filtered_sorted))
    with m3:
        st.metric("Possible duplicate rows", len(dup_repo_ids))

    table_rows: List[dict[str, Any]] = []
    for g in filtered_sorted:
        row = build_library_table_row(g, batches=batches, duplicate_repo_ids=dup_repo_ids)
        table_rows.append(row)

    if not table_rows:
        st.info("No games match the current filters.")
    else:
        display_cols = [k for k in table_rows[0].keys() if not k.startswith("_")]
        st.dataframe(
            [{k: r[k] for k in display_cols} for r in table_rows],
            use_container_width=True,
            hide_index=True,
        )

    st.divider()
    st.markdown("#### Game details & metadata")
    st.caption("Pick a game to review context or enrich labels (saved to **`manifest.json`**).")

    labels: List[str] = []
    id_by_label: dict[str, str] = {}
    for g in filtered_sorted:
        rid = str(g.get("repo_game_id") or "")
        if not rid:
            continue
        title = human_readable_game_title(g)
        lbl = f"{title} — `{rid[:8]}…`"
        labels.append(lbl)
        id_by_label[lbl] = rid

    if not labels:
        st.caption("Adjust filters to select a game for metadata editing.")
        return

    pick = st.selectbox("Selected game", options=labels, key="hv_meta_pick")
    rid = id_by_label[pick]
    rec = next((x for x in games_raw if str(x.get("repo_game_id")) == rid), {})
    for line in compact_context_lines(rec, batches):
        st.markdown(line)

    tags_existing = rec.get("tags") if isinstance(rec.get("tags"), list) else []
    tag_str = ", ".join(str(t) for t in tags_existing)
    with st.form("hv_enrich_form"):
        st.markdown("**Edit index fields**")
        team = st.text_input("Team (ours)", value=str(rec.get("team") or ""))
        opponent = st.text_input("Opponent", value=str(rec.get("opponent") or ""))
        game_date = st.text_input("Game date", value=str(rec.get("game_date") or ""))
        season = st.text_input("Season", value=str(rec.get("season") or ""))
        roster_id = st.text_input("Roster id / version", value=str(rec.get("roster_id") or ""))
        tags = st.text_input("Tags (comma-separated)", value=tag_str)
        submitted = st.form_submit_button("Save to repository index")
    if submitted:
        tag_list = [x.strip() for x in tags.split(",") if x.strip()]
        ok = update_game_record_fields(
            repo_root,
            rid,
            {
                "team": team.strip(),
                "opponent": opponent.strip(),
                "game_date": game_date.strip(),
                "season": season.strip(),
                "roster_id": roster_id.strip(),
                "tags": tag_list,
            },
        )
        if ok:
            st.success("Metadata saved.")
            st.rerun()
        else:
            st.error("Update failed (game id not found).")

    st.divider()
    st.markdown("#### Validation overview")
    warn_games = [g for g in games_raw if str(g.get("validation_status") or "").lower() == "warnings"]
    if not warn_games:
        st.success("No indexed games are flagged with validation warnings.")
    else:
        st.warning(f"**{len(warn_games)}** game(s) have validation warnings — expand for a compact list.")
        with st.expander("Games with warnings", expanded=False):
            for g in sorted(warn_games, key=lambda x: human_readable_game_title(x).lower()):
                title = human_readable_game_title(g)
                st.markdown(f"**{title}** · `{str(g.get('repo_game_id'))[:8]}…`")
                for w in (g.get("validation_warnings") or [])[:8]:
                    st.caption(str(w))


def _render_match_tab(
    ss: Mapping[str, Any],
    repo_root,
    settings,
) -> None:
    st.markdown("### Match & validate")
    st.caption(
        "Load historical plays (repository or folder), then compare similar situations to the **current** session."
    )

    st.markdown("#### Session folder (legacy, not persisted)")
    path = st.text_input(
        "Folder path",
        placeholder="~/exports/game_json",
        key="hv_history_dir_session",
        help="Loads JSON into **session memory** only. Use **Import** to persist to the repository.",
    )
    c_opt1, c_opt2, c_opt3 = st.columns(3)
    with c_opt1:
        recursive = st.checkbox("Recursive `*.json`", value=False, key="hv_recursive_session")
    with c_opt2:
        min_matches = st.number_input("Target min matches", 1, 500, 5, 1, key="hv_min_matches")
    with c_opt3:
        min_family_n = st.number_input(
            "Min n (per-family detail)", 1, 50, 3, 1, key="hv_min_family_n"
        )

    use_sd = st.checkbox(
        "Filter historical rows by score margin (± vs live)",
        value=False,
        key="hv_use_score_diff",
    )
    score_diff_max: Optional[int] = None
    if use_sd:
        score_diff_max = int(
            st.number_input(
                "± points",
                0,
                60,
                14,
                1,
                key="hv_score_diff_max",
                help="Keep rows whose `score_diff` is within this many points of the live margin.",
            )
        )

    b1, b2 = st.columns(2)
    with b1:
        load_clicked = st.button("Load / reload folder → session", key="hv_load_corpus")
    with b2:
        match_clicked = st.button("Match current situation", type="primary", key="hv_match_situation")

    if load_clicked:
        root = (path or "").strip()
        if not root:
            st.warning("Enter a history directory first.")
        else:
            with st.spinner("Loading JSON…"):
                corpus = load_history_directory(
                    root,
                    recursive=bool(recursive),
                    max_json_files=settings.max_json_files,
                )
            ss[HV_SESSION_CORPUS_KEY] = corpus
            ss[HV_SESSION_CORPUS_PATH_KEY] = root
            st.success(f"Loaded **{len(corpus.plays)}** plays from `{root}` into session.")

    corpus = _resolve_validation_corpus(ss, repo_root)
    loaded_from = ss.get(HV_SESSION_CORPUS_PATH_KEY)
    src = str(ss.get(HV_CORPUS_SOURCE) or "folder_session")

    st.markdown("#### Active corpus")
    if corpus is None or not corpus.plays:
        st.info("No corpus — choose **Repository** above (with indexed games) or load a **folder**.")
    else:
        if src == "repository":
            st.markdown(
                f"**Source:** repository · **{len(corpus.plays)}** plays "
                f"({'all indexed games' if ss.get(HV_REPO_USE_ALL_GAMES, True) else 'selected games only'})"
            )
        else:
            st.markdown(
                f"**Source:** session folder · **{len(corpus.plays)}** plays"
                + (f" · `{loaded_from}`" if loaded_from else "")
            )
        if corpus.notes:
            for note in corpus.notes:
                st.caption(note)
        if isinstance(ss.get(HV_SESSION_CORPUS_KEY), HistoryCorpus):
            sc = ss[HV_SESSION_CORPUS_KEY]
            if sc.errors:
                st.warning(f"{len(sc.errors)} file(s) failed in last folder load — see expander.")
                with st.expander("Folder load errors", expanded=False):
                    for err in sc.errors[:80]:
                        st.text(f"{err.path}: {err.message}")

    if not match_clicked:
        return

    if corpus is None or not corpus.plays:
        st.error("Load a corpus (repository or folder) before matching.")
        return

    try:
        ctx = build_game_context_from_session_state(st.session_state)
        sig = situation_signature_from_context(ctx)
    except Exception as e:
        st.error(f"Could not build situation from session: {e}")
        return

    raw = query_similar_plays_from_context(
        corpus.plays,
        ctx,
        min_matches=int(min_matches),
        score_diff_max=score_diff_max,
    )
    enriched = attach_outcome_summary(raw, min_family_report_n=int(min_family_n))
    summary = enriched.outcome_summary
    if summary is None:
        st.error("Outcome summary missing — attach_outcome_summary failed unexpectedly.")
        return

    overall = summary.overall
    qb = enriched.trace.get("query_buckets") or {}

    st.divider()
    st.markdown("##### Query situation (live)")
    st.markdown(
        f"**Down {qb.get('down', '—')} · distance bucket `{qb.get('distance_bucket', '—')}` · "
        f"field zone `{qb.get('field_zone', '—')}`** · yardline₁₀₀ `{qb.get('yardline_100', '—')}` · "
        f"score_diff `{qb.get('score_diff', '—')}`"
    )
    st.caption(sig.describe())

    st.markdown("##### Match")
    m1, m2, m3 = st.columns(3)
    with m1:
        st.metric("Matched plays", overall.n)
    with m2:
        st.metric("Similarity tier", enriched.tier or "—")
    with m3:
        st.metric("Unique games (matches)", enriched.aggregates.unique_source_games)

    _fallback_banner(enriched)

    if overall.n == 0:
        st.warning("**No historical rows** matched this situation (after filters). Check corpus coverage or widen options.")
        with st.expander("Debug trace", expanded=False):
            st.json(_json_safe(enriched.trace))
        return

    _sample_confidence_note(overall)

    st.markdown("##### Summary metrics (matched set)")
    s1, s2, s3, s4, s5 = st.columns(5)
    with s1:
        st.metric("Success rate", _pct(overall.success_rate))
    with s2:
        st.metric("Avg yards", f"{overall.mean_yards:.1f}")
    with s3:
        st.metric("Explosive rate", _pct(overall.explosive_rate))
    with s4:
        st.metric("Turnover rate", _pct(overall.turnover_rate))
    with s5:
        st.metric("1st down / TD rate", _pct(overall.conversion_rate))

    st.markdown("##### By actual play lane (run family vs pass family)")
    st.caption(
        "Lanes group **logged** result families (`actual.family`). This is **not** the recommendation family."
    )
    lane_run = summary.by_actual_lane.get("run_family")
    lane_pass = summary.by_actual_lane.get("pass_family")
    c_run, c_pass = st.columns(2)
    with c_run:
        _render_lane_card("Run family (actual)", lane_run)
    with c_pass:
        _render_lane_card("Pass family (actual)", lane_pass)

    if summary.global_caveats:
        with st.expander("Aggregation caveats", expanded=False):
            for g in summary.global_caveats:
                st.markdown(f"- {g}")

    with st.expander("Matched plays (sample)", expanded=False):
        n_m = len(enriched.matches)
        max_rows = max(1, min(50, n_m))
        default_rows = max(1, min(15, n_m))
        lim = int(st.slider("Rows to show", 1, max_rows, default_rows, key="hv_table_limit"))
        table_rows: List[dict[str, Any]] = []
        for m in enriched.matches[:lim]:
            derived = derive_play_success(m.actual, down=m.down, distance=m.distance)
            table_rows.append(
                {
                    "down": m.down,
                    "dist_bucket": m.distance_bucket,
                    "zone": m.field_zone,
                    "actual_family": m.actual.family,
                    "yards": m.actual.yards_gained,
                    "play_success_raw": m.play_success,
                    "success_display": _success_cell(m.play_success, derived),
                }
            )
        st.dataframe(table_rows, use_container_width=True, hide_index=True)
        st.caption(
            "**(est.)** success was **derived** when `play_success` was null (same heuristic as aggregation)."
        )

    with st.expander("Full debug JSON", expanded=False):
        st.json(_json_safe(result_to_debug_dict(enriched)))


def render_history_validation_page() -> None:
    st.title(HISTORY_PAGE_TITLE)
    st.caption(
        "**Import** former games into a persistent library, **browse** with clear titles and filters, then **match** "
        "the live situation for validation. Point the sidebar **Historical nudge** at repository or folder data."
    )

    settings = load_history_repository_settings()
    repo_root = resolve_history_repository_root(settings)

    st.subheader("Corpus source (sidebar + matching)")
    r1, r2, r3 = st.columns((2, 1, 2))
    with r1:
        st.radio(
            "Where to load plays from",
            options=["folder_session", "repository"],
            format_func=lambda x: _CORPUS_SOURCE_LABELS.get(x, x),
            key=HV_CORPUS_SOURCE,
            horizontal=True,
        )
    with r2:
        use_all = st.checkbox(
            "All repo games",
            key=HV_REPO_USE_ALL_GAMES,
            help="When off, restrict to the games selected in the next column.",
        )
    with r3:
        games_meta = list_game_records(repo_root)
        opts = [str(g.get("repo_game_id")) for g in games_meta if g.get("repo_game_id")]

        def _fmt_rid(rid: str) -> str:
            g = next((x for x in games_meta if str(x.get("repo_game_id")) == rid), {})
            return human_readable_game_title(g) + f" (`{str(rid)[:8]}…`)"

        _repo_src = str(st.session_state.get(HV_CORPUS_SOURCE)) == "repository"
        if _repo_src and not opts:
            st.caption("No indexed games yet — use **Import**.")
        elif opts:
            st.multiselect(
                "Repository games (when not using all)",
                options=opts,
                format_func=_fmt_rid,
                key=HV_REPO_SELECTED_GAME_IDS,
                disabled=bool(use_all) or not _repo_src,
            )
        else:
            st.caption("—")

    st.divider()

    tab_import, tab_lib, tab_match = st.tabs(["Import", "Library", "Match & validate"])
    with tab_import:
        _render_import_tab(repo_root, settings)
    with tab_lib:
        _render_library_tab(repo_root)
    with tab_match:
        _render_match_tab(st.session_state, repo_root, settings)
