"""History: saved audits, comparison between two runs, and trends over time."""
import collections
import datetime

import pandas as pd
import streamlit as st

from gga import auth, compare, history, log, report, ui

S = st.session_state
if auth.is_web():
    ui.require_login("your history")  # on a hosted copy history belongs to a signed-in person, never to "everyone"
store, note = ui.get_store()
me = ui.owner()

ui.page_title("History", "Every audit you run is saved here, so you can see what got worse, what was fixed and how things trend over time.")

# ------------------------------------------------------------------ where history lives
where = store.describe()
with st.container(border=True):
    c1, c2 = st.columns([4, 1], vertical_alignment="center")
    c1.markdown(f"**Saved in:** {where}")
    ui.badges([({"database": "Database", "file": "On this computer", "session": "This session only"}[store.mode], "default" if store.mode != "session" else "secondary")],
              key="hist_mode")
if note:
    ui.notice("History is in a fallback mode", note, "warn")
if store.mode == "session":
    ui.notice("History is only kept for this visit",
              "This copy of the tool has no history database, so saved runs disappear when you close the tab. Comparing runs from one visit works, "
              "and you can compare against a findings file you downloaded earlier. The admin can keep history permanently by setting "
              "GGA_DATABASE_URL to a PostgreSQL database (see DEPLOY.md).", "info")

runs_all = store.list_runs(me)
if not runs_all:
    st.markdown("### Nothing saved yet")
    st.write("Run an audit on the **GA4 & GTM audit** page or the **Page audit** page. Results are saved here automatically. "
             "Run the same audit again later and you will see exactly what changed.")
    if store.mode == "session":
        st.caption("You can still compare a new audit against an earlier findings file: open the Compare tab after your next audit.")


def label(r):
    when = r["created_at"].replace("T", " ")[:16]
    return f"{when} Â· {history.KINDS.get(r['kind'], r['kind'])} Â· {r['n_entities']} items Â· {r['n_fail']} fail, {r['n_warn']} warn Â· {r['scope_text'][:60]}"


tab_cmp, tab_runs, tab_trend = st.tabs(["Compare", "Saved runs", "Trends"])

# ------------------------------------------------------------------ compare
with tab_cmp:
    mode = st.radio("Compare", ["Two saved runs", "A saved run against a findings file I upload"], horizontal=True, key="cmp_mode")
    old, new, old_label, new_label = None, None, "", ""
    if mode == "Two saved runs":
        kinds = sorted({r["kind"] for r in runs_all})
        if len(runs_all) < 2:
            st.info("You need at least two saved runs of the same kind. Run the audit again later, then come back.")
        else:
            kind = st.selectbox("Type of audit", kinds, format_func=lambda k: history.KINDS.get(k, k), key="cmp_kind")
            runs = [r for r in runs_all if r["kind"] == kind]
            if len(runs) < 2:
                st.info("Only one saved run of this type so far.")
            else:
                default_old = next((i for i, r in enumerate(runs[1:], 1) if r["scope_text"] == runs[0]["scope_text"]), 1)
                a, b = st.columns(2)
                ni = a.selectbox("Newer run", range(len(runs)), index=0, format_func=lambda i: label(runs[i]), key="cmp_new")
                oi = b.selectbox("Older run (to compare against)", range(len(runs)), index=default_old, format_func=lambda i: label(runs[i]), key="cmp_old")
                if ni == oi:
                    st.warning("Pick two different runs.")
                else:
                    if runs[ni]["created_at"] < runs[oi]["created_at"]:
                        ni, oi = oi, ni
                    new, old = store.get_findings(me, runs[ni]["id"]), store.get_findings(me, runs[oi]["id"])
                    new_label, old_label = runs[ni]["created_at"][:16].replace("T", " "), runs[oi]["created_at"][:16].replace("T", " ")
    else:
        up = st.file_uploader("Earlier findings file (the 'All findings (.csv)' download from an audit)", type=["csv"], key="cmp_up")
        if up is not None and runs_all:
            try:
                old = compare.baseline_from_csv(up.getvalue())
                pick = st.selectbox("Compare it against", range(len(runs_all)), format_func=lambda i: label(runs_all[i]), key="cmp_vs")
                new = store.get_findings(me, runs_all[pick]["id"])
                old_label, new_label = "the uploaded file", runs_all[pick]["created_at"][:10]
            except ValueError as e:
                ui.notice("That file did not work", str(e), "warn")
        elif up is not None:
            ui.notice("Run an audit first", "Run an audit on the other pages, then upload the earlier findings file here to compare.", "info")

    if old is not None and new is not None:
        c = compare.compare(old, new)
        k = c["counts"]
        st.markdown(f"#### {new_label} compared with {old_label}")
        if k["new_problems"] or k["worsened"]:
            st.warning(f"{compare.headline(c).capitalize()}.")
        else:
            st.success(f"{compare.headline(c).capitalize()}.")
        delta = (c["score_new"] - c["score_old"]) if c["score_old"] is not None and c["score_new"] is not None else 0
        ui.metrics([("New problems", k["new_problems"], "were fine before"), ("Got worse", k["worsened"], "warn became fail"),
                    ("Fixed", k["resolved"], "no longer a problem"), ("Improved", k["improved"], "fail became warn"),
                    ("Average health", c["score_new"] if c["score_new"] is not None else "-", f"{delta:+.1f} since the older run")], key="cmp_kpi")
        st.caption(f"{c['compared_items']} items appear in both runs and were compared check by check."
                   + (f" {c['not_rechecked']} problem checks were not run the second time (different options) and are not counted as fixed." if c["not_rechecked"] else ""))

        def table(rows, empty):
            if not rows:
                st.info(empty)
                return
            st.dataframe(pd.DataFrame([dict(Account=r["account"], Item=r["entity"], Check=r["check"], Was=r["was"], Now=r["now"],
                                            Now_detail=r["now_detail"]) for r in rows]), width="stretch", hide_index=True)

        t1, t2, t3, t4, t5, t6 = st.tabs([f"New problems ({k['new_problems']})", f"Got worse ({k['worsened']})", f"Fixed ({k['resolved']})",
                                          f"Improved ({k['improved']})", f"Still open ({k['persisting']})", "Health by item"])
        with t1:
            table(c["new_problems"], "No new problems.")
        with t2:
            table(c["worsened"], "Nothing got worse.")
        with t3:
            table(c["resolved"], "Nothing was fixed in this period.")
        with t4:
            table(c["improved"], "Nothing improved from fail to warn.")
        with t5:
            table(c["persisting"], "No problems remain.")
            if k["changed"]:
                st.caption(f"{k['changed']} of these have different details than before (for example a different count). Open the CSV download for old and new details.")
        with t6:
            st.dataframe(pd.DataFrame([dict(Account=r["account"], Item=r["entity"], Was=r["was"], Now=r["now"], Change=r["change"]) for r in c["health"]]),
                         width="stretch", hide_index=True,
                         column_config={"Change": st.column_config.NumberColumn(format="%+d", help="Health score now minus health score then")})
        if c["added_items"] or c["removed_items"]:
            with st.expander(f"Items in only one run ({len(c['added_items'])} new, {len(c['removed_items'])} no longer audited)"):
                if c["added_items"]:
                    st.markdown("**Only in the newer run:** " + "; ".join(f"{a[2]} ({a[1]})" for a in c["added_items"][:40]))
                if c["removed_items"]:
                    st.markdown("**Only in the older run:** " + "; ".join(f"{a[2]} ({a[1]})" for a in c["removed_items"][:40]))
        st.download_button("Download this comparison (.csv)", compare.to_csv(c), f"comparison-{new_label}-vs-{old_label}.csv".replace(" ", "-").replace(":", ""), "text/csv")

# ------------------------------------------------------------------ saved runs
with tab_runs:
    if not runs_all:
        st.info("No saved runs.")
    else:
        df = pd.DataFrame([dict(Saved=r["created_at"].replace("T", " ")[:16], Type=history.KINDS.get(r["kind"], r["kind"]), Items=r["n_entities"],
                                Fail=r["n_fail"], Warn=r["n_warn"], Pass=r["n_pass"], Scope=r["scope_text"][:90], By=r["source"]) for r in runs_all])
        sel = st.dataframe(df, width="stretch", hide_index=True, on_select="rerun", selection_mode="multi-row", key="runs_table")
        rows = sel.selection.rows if sel and sel.selection else []
        picked = [runs_all[i] for i in rows]
        a, b, c3 = st.columns([1, 1, 3])
        if picked:
            if len(picked) == 1:
                fnd = store.get_findings(me, picked[0]["id"])
                a.download_button("Download findings (.csv)", report.to_csv(fnd, report.COLS), f"findings-{picked[0]['created_at'][:10]}.csv", "text/csv")
            if b.button(f"Delete {len(picked)} selected", key="del_sel"):
                for r in picked:
                    store.delete_run(me, r["id"])
                log.event("history_deleted", count=len(picked), user=log.who(ui.email()))
                st.rerun()
        else:
            st.caption("Select rows to download or delete them.")
        with st.expander("Delete all my history"):
            sure = st.checkbox("Yes, delete every saved run that belongs to me. This cannot be undone.", key="del_all_ok")
            if st.button("Delete all", disabled=not sure, key="del_all"):
                n = store.delete_all(me)
                log.event("history_deleted_all", count=n, user=log.who(ui.email()))
                st.rerun()
        st.caption("Saved runs contain the findings text of your audits, which can include account, container and website names. "
                   "Only you can see your runs. The oldest runs are removed automatically once you have more than "
                   f"{getattr(store, 'keep', 20)}.")

# ------------------------------------------------------------------ trends
with tab_trend:
    if len(runs_all) < 2:
        st.info("Trends appear once you have at least two saved runs of the same kind.")
    else:
        kinds = sorted({r["kind"] for r in runs_all})
        tk = st.selectbox("Type of audit", kinds, format_func=lambda k: history.KINDS.get(k, k), key="trend_kind")
        scopes = sorted({r["scope_text"] for r in runs_all if r["kind"] == tk})
        ts = st.selectbox("Scope", scopes, format_func=lambda s_: (s_ or "(no scope)")[:110], key="trend_scope")
        series = [r for r in runs_all if r["kind"] == tk and r["scope_text"] == ts][::-1]
        if len(series) < 2:
            st.info("Only one saved run for this scope so far.")
        else:
            chart = pd.DataFrame([dict(Date=datetime.datetime.fromisoformat(r["created_at"]), Fail=r["n_fail"], Warn=r["n_warn"]) for r in series]).set_index("Date")
            st.caption("Fail and warn counts per saved run")
            st.line_chart(chart, color=["#dc2626", "#f59e0b"])
            recent = series[-8:]
            seen = collections.Counter()
            names = {}
            for r in recent:
                for f in store.get_findings(me, r["id"]):
                    if f["status"] in ("FAIL", "WARN"):
                        key = (f["account"], f["entity"], f["check"])
                        seen[key] += 1
                        names[key] = f["status"]
            rec = [(k, n) for k, n in seen.items() if n >= max(2, len(recent) - 1)]
            st.markdown(f"**Problems present in almost every one of the last {len(recent)} runs**")
            if rec:
                rec.sort(key=lambda kv: (-kv[1], kv[0]))
                st.dataframe(pd.DataFrame([dict(Account=k[0], Item=k[1], Check=k[2], Status=names[k], Runs=f"{n} of {len(recent)}") for k, n in rec[:60]]),
                             width="stretch", hide_index=True)
            else:
                st.success("No problem has stayed open across all recent runs.")
