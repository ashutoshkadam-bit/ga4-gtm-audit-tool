"""GA4 + GTM Audit: a point-and-click tool. Start it with run.bat (Windows) or ./run.sh (Mac/Linux)."""
import collections
import datetime

import pandas as pd
import streamlit as st

from gga import auth, core, knowledge, report, site

st.set_page_config(page_title="GA4 & GTM Audit", page_icon=":mag:", layout="wide")
S = st.session_state
WEB = auth.is_web()


def intro():
    st.title("GA4 & GTM Audit")
    st.write("Audit any of your Google Analytics 4 properties and Tag Manager containers in a few clicks. "
             "You sign in with **your own Google account**, so you only see and audit what you already have access to. "
             "The tool is read-only: it never changes anything in Analytics or Tag Manager.")


def sign_in_screen_local():
    intro()
    if not auth.client_secret_path():
        st.error("This copy of the tool has no `client_secret.json` yet. Ask the person who shared it with you, "
                 "or see SETUP_ADMIN.md.")
        return
    if st.button("Sign in with Google", type="primary"):
        with st.spinner("Finish signing in in the browser window that just opened..."):
            try:
                auth.sign_in()
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(f"Sign-in did not complete: {e}")
    st.caption("Your login stays on this computer, in your user folder. Use Sign out in the sidebar to remove it.")


def sign_in_screen_web(error=""):
    intro()
    if error:
        st.error(error)
    if not auth.web_configured():
        st.error("This server is missing its Google sign-in settings (GGA_CLIENT_ID, GGA_CLIENT_SECRET, "
                 "GGA_REDIRECT_URI). See DEPLOY.md.")
        return
    st.link_button("Sign in with Google", auth.web_login_url(), type="primary")
    st.caption("Your Google login is kept only in this browser session on the server and is dropped when you "
               "sign out or close the tab. Nothing is saved to disk.")


if WEB:
    creds = S.get("creds")
    if not creds and "code" in st.query_params:  # Google just sent the user back with a sign-in code
        try:
            S.creds = creds = auth.web_finish(st.query_params["code"], st.query_params.get("state", ""))
            st.query_params.clear()
            st.rerun()
        except Exception as e:  # noqa: BLE001
            st.query_params.clear()
            sign_in_screen_web(f"Sign-in did not complete: {e}")
            st.stop()
    if not creds:
        sign_in_screen_web()
        st.stop()
else:
    creds = auth.load_credentials()
    if not creds:
        sign_in_screen_local()
        st.stop()

if "email" not in S:
    S.email = auth.user_email(creds)
with st.sidebar:
    st.markdown(f"**Signed in as**  \n{S.email or 'your Google account'}")
    if st.button("Sign out"):
        if not WEB:
            auth.sign_out()
        S.clear()
        st.rerun()
    st.markdown("---")
    st.caption("Read-only audit. GA4 data checks use the Analytics Data API; GTM checks read the live published "
               "version of each container.")

if "auditor" not in S:
    S.auditor = None
auditor_opts_key = None

st.title("GA4 & GTM Audit")

# ---------------------------------------------------------------- 1. accounts
st.header("1. Choose what to audit")
if st.button("Load my accounts", type="primary" if "ga4_rows" not in S else "secondary"):
    S.auditor = core.Auditor(creds)
    try:
        with st.spinner("Reading your GA4 accounts..."):
            S.ga4_rows = S.auditor.list_ga4()
        bar = st.progress(0.0, "Reading your GTM accounts...")
        S.gtm_rows = S.auditor.list_gtm(lambda i, n, name: bar.progress(i / n, f"GTM account {i}/{n}: {name}"))
        bar.empty()
        S.pop("results", None)
    except Exception as e:  # noqa: BLE001
        st.error(f"Could not read your accounts: {core.short_err(e)}")
        S.pop("ga4_rows", None)

if "ga4_rows" in S:
    ga4_counts = collections.Counter(r["account"] for r in S.ga4_rows)
    gtm_counts = collections.Counter(r["account"] for r in S.gtm_rows)
    st.caption(f"You have access to {len(S.ga4_rows)} GA4 properties in {len(ga4_counts)} accounts and "
               f"{len(S.gtm_rows)} GTM containers in {len(gtm_counts)} accounts.")
    flt = st.text_input("Quick filter (optional): type part of one or more account names, separated by commas",
                        placeholder="for example: acme, globex")
    words = [w.strip().lower() for w in flt.split(",") if w.strip()]
    pick = lambda counts: [a for a in counts if words and any(w in a.lower() for w in words)]  # noqa: E731
    all_default = not words
    c1, c2 = st.columns(2)
    with c1:
        ga4_sel = st.multiselect("GA4 accounts", sorted(ga4_counts), default=sorted(ga4_counts) if all_default else pick(ga4_counts),
                                 format_func=lambda a: f"{a} ({ga4_counts[a]} properties)", key=f"ga4_{flt}")
    with c2:
        gtm_sel = st.multiselect("GTM accounts", sorted(gtm_counts), default=sorted(gtm_counts) if all_default else pick(gtm_counts),
                                 format_func=lambda a: f"{a} ({gtm_counts[a]} containers)", key=f"gtm_{flt}")
    ga4_pick = [r for r in S.ga4_rows if r["account"] in ga4_sel]
    gtm_pick = [r for r in S.gtm_rows if r["account"] in gtm_sel]
    limit = st.number_input("Limit per account (0 = no limit; use 2 or 3 for a quick test)", 0, 1000, 0)
    if limit:
        def cap(rows):
            seen = collections.Counter()
            out = []
            for r in rows:
                if seen[r["account"]] < limit:
                    out.append(r)
                    seen[r["account"]] += 1
            return out
        ga4_pick, gtm_pick = cap(ga4_pick), cap(gtm_pick)

    # ------------------------------------------------------------ 2. options + run
    st.header("2. Run the audit")
    with st.expander("Options", expanded=False):
        o1, o2 = st.columns(2)
        with o1:
            opt_settings = st.checkbox("GA4 settings checks", True, help="Retention, streams, key events, links, signals...")
            opt_data = st.checkbox("GA4 data checks (last N days)", True, help="Event volume, key events firing, unassigned traffic. Slower.")
            opt_gtm = st.checkbox("GTM container checks", True)
            opt_cross = st.checkbox("Cross-check GTM GA4 IDs against all my GA4 properties", True)
        with o2:
            days = st.number_input("Data window (days)", 7, 365, 30)
            unassigned = st.number_input("Warn when Unassigned traffic is above (%)", 1, 100, 10)
            html_thr = st.number_input("Warn when a container has more custom HTML tags than", 0, 500, 5)
    est = (len(ga4_pick) * (5 if opt_data else 2) + len(gtm_pick) * 1.2) / 60
    st.write(f"**{len(ga4_pick)} GA4 properties** and **{len(gtm_pick)} GTM containers** selected. "
             f"Estimated time: about {max(1, round(est))} min.")
    if st.button("Run audit", type="primary", disabled=not (ga4_pick or gtm_pick)):
        auditor = core.Auditor(creds, dict(ga4_settings=opt_settings, ga4_data=opt_data, gtm=opt_gtm, days=days,
                                           unassigned_threshold=unassigned, html_threshold=html_thr))
        bar, note = st.progress(0.0, "Starting..."), st.empty()
        known = None
        if opt_cross and gtm_pick:
            if "known_ids" not in S:
                note.info("Collecting measurement IDs from all your GA4 properties for the cross-check "
                          "(done once per session, about 1 to 2 minutes)...")
                S.known_ids = core.all_ga4_measurement_ids(
                    auditor, S.ga4_rows,
                    lambda d, n, name: bar.progress(d / n, f"Cross-check IDs {d}/{n}: {name}"))
            known = S.known_ids
        note.empty()
        t0 = datetime.datetime.now()
        findings, inventory = core.run_audit(
            auditor, ga4_pick if (opt_settings or opt_data) else [], gtm_pick if opt_gtm else [], known,
            progress=lambda d, n, label: bar.progress(d / max(n, 1), f"{d}/{n}  {label}"))
        bar.empty()
        scope_bits = [f"GA4: {', '.join(ga4_sel) or 'none'}", f"GTM: {', '.join(gtm_sel) or 'none'}"]
        S.results = dict(findings=findings, inventory=inventory, days=days,
                         meta=dict(title="GA4 & GTM audit", user=S.email, scope_text=" | ".join(scope_bits)[:400], days=days),
                         seconds=(datetime.datetime.now() - t0).seconds)

# ---------------------------------------------------------------- 3. results
if "results" in S:
    R = S.results
    # live site check and page audit results join the reports when present
    F = R["findings"] + S.get("site_findings", []) + S.get("page_findings", [])
    st.header("3. Results")
    tot = collections.Counter(r["status"] for r in F)
    ents = {(r["scope"], r["entity_id"] or r["entity"]) for r in F}
    m = st.columns(5)
    m[0].metric("Audited", len(ents))
    m[1].metric("Fail", tot["FAIL"])
    m[2].metric("Warn", tot["WARN"])
    m[3].metric("Errors", tot["ERROR"])
    m[4].metric("Pass", tot["PASS"])
    if tot["ERROR"]:
        st.warning("Some checks could not run (usually a permission or API limit on that item). "
                   "Filter the Findings tab by status ERROR to see which.")
    t1, t2, t3, t4, t6, t5 = st.tabs(["By check", "By account", "Items by health", "All findings", "How to fix", "Download"])
    with t6:
        guides = knowledge.for_findings(F)
        st.caption("Why each problem matters and how to fix it, worst first, with a link to the official source. "
                   "The full list of checks and the frameworks behind them are on the Frameworks and fix guides page.")
        if not guides:
            st.info("No failures or warnings to explain.")
        for g in guides:
            counts = ", ".join(f"{g[k]} {k.lower()}" for k in ("FAIL", "WARN", "ERROR") if g[k])
            with st.expander(f"{g['check']}  ·  {counts}"):
                st.markdown(f"**Why it matters.** {g['why']}")
                st.markdown(f"**How to fix.** {g['fix']}")
                if g["source"]:
                    st.markdown(f"**Source:** [{g['source'][0]}]({g['source'][1]})")
    with t1:
        st.dataframe(pd.DataFrame(report.by_check(F)), width="stretch", hide_index=True)
    with t2:
        st.dataframe(pd.DataFrame(report.by_account(F)), width="stretch", hide_index=True)
    with t3:
        st.caption("Health score = 100 minus 20 per fail and 5 per warn or error. Lowest first.")
        st.dataframe(pd.DataFrame(report.summarize(F)), width="stretch", hide_index=True)
    with t4:
        df = pd.DataFrame(F)
        f1, f2, f3 = st.columns(3)
        stat = f1.multiselect("Status", report.ORDER, default=["FAIL", "WARN", "ERROR"])
        chk = f2.multiselect("Check", sorted(df["check"].unique()))
        acc = f3.multiselect("Account", sorted(df["account"].unique()))
        q = st.text_input("Search in item name or detail")
        v = df[df["status"].isin(stat)]
        if chk:
            v = v[v["check"].isin(chk)]
        if acc:
            v = v[v["account"].isin(acc)]
        if q:
            v = v[v["entity"].str.contains(q, case=False, na=False) | v["detail"].str.contains(q, case=False, na=False)]
        st.caption(f"{len(v)} rows")
        st.dataframe(v, width="stretch", hide_index=True)
    with t5:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
        d1, d2, d3 = st.columns(3)
        d1.download_button("Excel report (.xlsx)", report.to_xlsx(F, R["inventory"]), f"ga4-gtm-audit-{stamp}.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        d2.download_button("HTML report (share or print to PDF)", report.to_html(F, R["meta"]), f"ga4-gtm-audit-{stamp}.html", "text/html")
        d3.download_button("All findings (.csv)", report.to_csv(F, report.COLS), f"ga4-gtm-audit-{stamp}.csv", "text/csv")
        st.caption("The HTML report is a single file with no external links. Open it in a browser and use Print > Save as PDF.")

# ---------------------------------------------------------------- 4. live site check
if "ga4_rows" in S:
    st.header("4. Live site check (optional)")
    st.write("Compares what your websites **really load** with what Google Analytics and Tag Manager say. It finds the "
             "Tag Manager containers and GA4 / Universal Analytics IDs on each page, reads what the published containers "
             "fire, and flags IDs that are not yours, double-loaded tags and leftover Universal Analytics. "
             "It reads public pages only. It cannot see tags injected by other scripts or test cookie consent.")
    if "site_fill" in S:
        S.site_urls = S.pop("site_fill")
    f1, f2 = st.columns([3, 1])
    with f2:
        if st.button("Fill from my selected GA4 accounts", help="Uses the website address of each GA4 web stream in the accounts chosen above."):
            bar = st.progress(0.0, "Reading GA4 web streams...")
            auditor_for_urls = core.Auditor(creds, dict(ga4_settings=False, ga4_data=False))
            urls_found = core.web_stream_urls(auditor_for_urls, ga4_pick, lambda d, n, name: bar.progress(d / n, f"{d}/{n}  {name}"))
            S.site_fill = "\n".join(urls_found[:site.MAX_URLS])
            S.pop("site_fill_note", None)
            if len(urls_found) > site.MAX_URLS:
                S.site_fill_note = f"{len(urls_found)} addresses found. Only the first {site.MAX_URLS} are filled in; run the rest in another batch."
            st.rerun()
    with f1:
        st.text_area(f"Website addresses, one per line (up to {site.MAX_URLS})", key="site_urls", height=160,
                     placeholder="https://www.example.com\nhttps://shop.example.com/landing")
    if S.get("site_fill_note"):
        st.info(S.site_fill_note)
    urls = [u for u in S.get("site_urls", "").splitlines() if u.strip()]
    if st.button("Run live site check", type="primary", disabled=not urls):
        known_c = {r["public_id"] for r in S.gtm_rows}
        if "known_ids" not in S:
            bar = st.progress(0.0, "Collecting your GA4 measurement IDs for the comparison (once per session)...")
            S.known_ids = core.all_ga4_measurement_ids(core.Auditor(creds, dict(ga4_settings=False, ga4_data=False)), S.ga4_rows,
                                                       lambda d, n, name: bar.progress(d / n, f"IDs {d}/{n}: {name}"))
            bar.empty()
        bar = st.progress(0.0, "Checking websites...")
        S.site_findings = site.run_site_check(urls, known_c, S.known_ids,
                                              progress=lambda d, n, u: bar.progress(d / n, f"{d}/{n}  {u}"))
        bar.empty()
        st.rerun()
    SF = S.get("site_findings")
    if SF:
        tot_s = collections.Counter(r["status"] for r in SF)
        st.write(f"**{len({r['entity'] for r in SF})} pages checked:** {tot_s['FAIL']} fail, {tot_s['WARN']} warn, {tot_s['PASS']} pass. "
                 "These results are also included in the Excel and HTML reports above.")
        view = pd.DataFrame([r for r in SF if r["status"] in ("FAIL", "WARN")] or SF)[["entity", "check", "status", "detail"]]
        st.dataframe(view, width="stretch", hide_index=True)
        st.download_button("Live site check (.csv)", report.to_csv(SF, report.COLS), "live-site-check.csv", "text/csv")

