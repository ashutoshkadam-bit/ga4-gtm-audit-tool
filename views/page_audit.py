"""Page audit: load any URL in a real browser and record network calls, console, tags, technologies, cookies and speed."""
import collections
import datetime
import json

import pandas as pd
import streamlit as st

from gga import auth, knowledge, log, pageanalysis, pagecapture, report, site, techdb, ui

S = st.session_state
WEB = auth.is_web()
if WEB:
    ui.require_login("the page audit")  # on a hosted copy only signed-in staff may open pages from the server

ui.page_title("Page audit", "Load any web page in a real browser and see everything it does: network calls, console, tags and hits, "
              "Tag Manager, GA4, Adobe and other vendors, how each tag loads, cookies, CDN, speed and security headers.")


def mb(n):
    return f"{(n or 0) / 1e6:.2f} MB" if (n or 0) >= 1e6 else f"{(n or 0) / 1e3:.0f} KB"


try:
    import playwright  # noqa: F401
    HAVE_PW = True
except ImportError:
    HAVE_PW = False


def limited_check(u):
    """No browser available: read the page HTML and the published GTM container instead (IDs, GTM, GA4, Universal Analytics)."""
    known_c = {r["public_id"] for r in S.get("gtm_rows", [])} or None
    return site.scan_url(u, known_containers=known_c, known_ga4=S.get("known_ids"))


# ------------------------------------------------------------------------------------------------ inputs
tab_run, tab_import, tab_status = st.tabs(["Audit a URL", "Import from the Chrome extension", "Browser status"])

with tab_run:
    urls_text = st.text_area("Page addresses, one per line (up to 5 per run)", key="pa_urls", height=110,
                             placeholder="https://www.example.com\nhttps://www.example.com/pricing")
    c1, c2, c3, c4 = st.columns(4)
    device = c1.selectbox("Device", ["desktop", "mobile"])
    wait_s = c2.number_input("Wait for network to settle (seconds)", 2, 30, 8)
    scroll = c3.checkbox("Scroll the page", True, help="Triggers lazy-loaded images and tags.")
    consent = c4.checkbox("Also test accepting the cookie banner", False,
                          help="Clicks a visible accept button and records what changes afterwards.")
    allow_private = False
    if not WEB:
        allow_private = st.checkbox("Allow local or internal addresses (this computer only)", False)
    save_hist = st.checkbox("Save results to history", True, help="Lets you compare this page with later audits on the History page.")
    if st.button("Run page audit", type="primary", disabled=not urls_text.strip()):
        urls = [u for u in urls_text.splitlines() if u.strip()][:5]
        runs, limited, skipped = [], [], []
        for u in urls:
            with st.status(f"Auditing {u}", expanded=True) as stat:
                try:
                    if not HAVE_PW:
                        raise pagecapture.BrowserUnavailable("The browser engine is not installed on this copy of the tool.")
                    cap = pagecapture.capture(u, device=device, wait_s=wait_s, scroll=scroll,
                                              consent="accept" if consent else "none", allow_private=allow_private,
                                              progress=lambda m: stat.write(m))
                    an = pageanalysis.analyze(cap)
                    runs.append(dict(cap=cap, an=an, findings=pageanalysis.to_findings(cap, an)))
                    log.event("page_audit", host=an["page_host"], requests=len(cap["requests"]), seconds=cap.get("seconds"),
                              user=log.who(S.get("email", "")))
                    stat.update(label=f"Done: {u}", state="complete")
                except site.BlockedAddress as e:
                    skipped.append((u, str(e)))
                    stat.update(label=f"Skipped: {u}", state="complete")
                    stat.write(f"This address is not allowed here: {e}.")
                except pagecapture.BrowserUnavailable:
                    stat.write("The full browser audit is not available on this server, so a limited check is running instead.")
                    try:
                        limited += limited_check(u)
                        stat.update(label=f"Limited check done: {u}", state="complete")
                    except Exception:  # noqa: BLE001
                        stat.update(label=f"Could not check {u}", state="complete")
                        stat.write("The page could not be read. Check the address and try again, or use the Chrome extension.")
                except Exception as e:  # noqa: BLE001
                    log.exception("page_audit_failed", e, host=(u.split("//")[-1].split("/")[0])[:80])
                    stat.update(label=f"Could not complete {u}", state="complete")
                    stat.write("Something unexpected stopped this audit. Your other results are not affected. "
                               "Try again, or use the Chrome extension for this page.")
                    with st.expander("Technical details"):
                        st.code(f"{type(e).__name__}: {str(e)[:400]}")
        if runs:
            if save_hist:
                for r in runs:
                    r["run_id"] = ui.save_history("page", r["an"]["page_host"], r["cap"].get("final_url", ""), r["findings"],
                                                  dict(device=device, requests=len(r["cap"]["requests"])))
            S.page_runs = runs
            S.page_findings = [f for r in runs for f in r["findings"]]
        if limited:
            S.limited_findings = limited
        if runs or limited:
            st.rerun()
    if S.get("limited_findings"):
        ui.notice("Limited check (no browser on this server)",
                  "These results come from reading the page HTML and each Tag Manager container's published script. For the full audit "
                  "(network calls, console, cookies, speed), run the tool on your own computer or capture the page with the Chrome extension "
                  "and import it in the next tab.", "info")
        lf = pd.DataFrame(S.limited_findings)[["entity", "check", "status", "detail"]]
        st.dataframe(lf, width="stretch", hide_index=True)

with tab_import:
    st.write("Audit a page in **your own browser** with the Chrome extension (it sees logged-in pages and sites that block "
             "automated browsers), then import its capture file here. See the `extension` folder and its README.")
    up = st.file_uploader("Capture file (.json)", type=["json"])
    if up is not None:
        try:
            cap = json.load(up)
            if not isinstance(cap, dict) or cap.get("schema") != "gga-capture-1":
                ui.notice("Not a capture file", "This file is not a capture from the Page audit tool or its Chrome extension.", "warn")
            else:
                an = pageanalysis.analyze(cap)
                S.page_runs = [dict(cap=cap, an=an, findings=pageanalysis.to_findings(cap, an))]
                S.page_findings = S.page_runs[0]["findings"]
                st.success("Capture imported.")
        except (ValueError, KeyError, TypeError):
            ui.notice("Could not read the file", "The file is damaged or is not a capture. Record it again with the extension.", "warn")

with tab_status:
    st.write("The full page audit needs a browser on the machine that runs this tool. Check it here.")
    if st.button("Check the browser on this server"):
        with st.spinner("Checking. The first time on a new server can take a minute while a browser is set up..."):
            try:
                st.success("Ready: " + pagecapture.ensure_browser())
            except pagecapture.BrowserUnavailable as e:
                ui.notice("No browser on this server", f"{e} The tool will run a limited check instead, and the Chrome extension import "
                          "works everywhere.", "info")
            except Exception:  # noqa: BLE001
                ui.notice("The browser check could not finish", "Try again in a moment.", "info")
    import platform
    st.caption(f"Server: {platform.system()} {platform.machine()}, Python {platform.python_version()}")

# ------------------------------------------------------------------------------------------------ results
runs = S.get("page_runs")
if not runs:
    st.stop()

labels = [f"{r['cap'].get('final_url') or r['cap'].get('url')}" for r in runs]
pick = st.selectbox("Showing results for", range(len(runs)), format_func=lambda i: labels[i]) if len(runs) > 1 else 0
run = runs[pick]
cap, an, F = run["cap"], run["an"], run["findings"]
reqs = cap.get("requests", [])
nw = an["network"]

if (cap.get("status") or 0) in (401, 403, 429) or cap.get("nav_error"):
    ui.notice("This page blocked the automated browser",
              f"It answered {cap.get('nav_error') or 'HTTP ' + str(cap.get('status'))}. Some sites do this on purpose. Capture the page in your "
              "own browser with the Chrome extension and import it in the second tab.", "info")

if run.get("run_id"):
    ui.since_last_notice("page", cap.get("final_url", ""), run["run_id"], F, key="page_since")

ui.metrics([("Requests", nw["total_requests"], "network calls"), ("Transferred", mb(nw["total_bytes"]), "compressed size"),
            ("Third-party hosts", len(nw["third_party_hosts"]), "other domains contacted"),
            ("Console errors", sum(1 for c in cap.get("console", []) if c["type"] == "error") + len(cap.get("errors", [])), "from the page"),
            ("Cookies", len(cap.get("cookies", [])), "set during the visit"),
            ("Source", "Extension" if cap.get("source") == "extension" else "Browser", "how it was captured")], key="pa_kpi")

(t_over, t_tech, t_tags, t_net, t_con, t_ck, t_perf, t_sec, t_find, t_dl) = st.tabs(
    ["Overview", "Technologies", "Tags and hits", "Network", "Console", "Cookies and storage", "Performance",
     "Headers, CDN and security", "Findings and fixes", "Download"])

with t_over:
    st.markdown(f"**{cap.get('title') or '(no title)'}**  \n{cap.get('final_url')}  ·  HTTP {cap.get('status')}  ·  "
                f"{cap.get('device', '')}  ·  {cap.get('started', '')[:19].replace('T', ' ')} UTC")
    by_cat = collections.defaultdict(list)
    for t in an["technologies"]:
        by_cat[t["category"]].append(t["name"])
    for cat in techdb.CATEGORIES:
        if by_cat.get(cat):
            st.markdown(f"**{cat}:** " + ", ".join(by_cat[cat]))
    st.subheader("Summary")
    st.markdown(report.summary_markdown(report.executive_summary(F)))
    if reqs:
        df = pd.DataFrame([dict(t=(r.get("start_ms") or 0) / 1000, kb=(r.get("encoded_size") or 0) / 1024) for r in reqs])
        df = df.sort_values("t")
        df["Cumulative KB downloaded"] = df["kb"].cumsum()
        st.caption("Data downloaded over time (seconds from the first request)")
        st.line_chart(df.set_index("t")["Cumulative KB downloaded"])

with t_tech:
    st.dataframe(pd.DataFrame([dict(Category=t["category"], Technology=t["name"], Requests=t["hits"], Evidence="; ".join(t["evidence"])[:200])
                               for t in an["technologies"]]), width="stretch", hide_index=True)
    st.caption("Detected from network requests, response headers, page code, browser globals and cookies. Our own signature list "
               "in gga/techdb.py, easy to extend.")

with t_tags:
    st.markdown("**Tags and vendors** (what loaded, when, and how)")
    st.dataframe(pd.DataFrame([dict(Vendor=t["name"], Category=t["category"], Requests=t["requests"], First_ms=round(t["first_ms"] or 0),
                                    Phase=t["first_phase"], Loaded_by=t["loaded_by"], Before_consent="yes" if t["before_consent"] else "no",
                                    KB=round(t["bytes"] / 1024), Hosts=", ".join(t["hosts"])) for t in an["tags"]]),
                 width="stretch", hide_index=True)
    h = an["hits"]
    if h["gtm"] or h["gtag"]:
        st.markdown("**Tag Manager containers and Google tags**")
        st.dataframe(pd.DataFrame([dict(ID=g["id"], Status=g["status"], Starts_ms=round(g["t"] or 0),
                                        Loaded_by=pageanalysis.loader_of(g["rec"], an["page_reg"], cap.get("final_url", "")))
                                   for g in h["gtm"] + h["gtag"]]), width="stretch", hide_index=True)
    if h["ga4"]:
        st.markdown("**GA4 events sent**")
        st.dataframe(pd.DataFrame([dict(Measurement_ID=e.get("tid"), Event=e["en"], At_ms=round(e["t"] or 0), Phase=e["phase"],
                                        Consent_signal=e.get("gcs", ""), Page=(e.get("dl") or "")[:70], Params=json.dumps(e.get("params", {}))[:120])
                                   for e in h["ga4"]]), width="stretch", hide_index=True)
    if h["adobe_aa"] or h["adobe_edge"]:
        st.markdown("**Adobe**")
        if h["adobe_aa"]:
            st.dataframe(pd.DataFrame(h["adobe_aa"]).drop(columns=["phase"]), width="stretch", hide_index=True)
        if h["adobe_edge"]:
            st.dataframe(pd.DataFrame([dict(Config=e["config"], Event_types=", ".join(e["types"]), At_ms=round(e["t"] or 0)) for e in h["adobe_edge"]]),
                         width="stretch", hide_index=True)
    if h["meta"] or h["ads"] or h["ua"]:
        st.markdown("**Other hits**")
        rows = [dict(Vendor="Meta pixel", ID=m_["pixel"], Event=m_["event"], At_ms=round(m_["t"] or 0)) for m_ in h["meta"]]
        rows += [dict(Vendor="Google Ads", ID=a["id"], Event=a["label"], At_ms=round(a["t"] or 0)) for a in h["ads"]]
        rows += [dict(Vendor="Universal Analytics (obsolete)", ID=u["tid"], Event=u["hit"], At_ms=round(u["t"] or 0)) for u in h["ua"]]
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    st.markdown("**dataLayer**")
    if an["datalayer_events"]:
        st.dataframe(pd.DataFrame(sorted(an["datalayer_events"].items(), key=lambda kv: -kv[1]), columns=["Event", "Times pushed"]),
                     width="stretch", hide_index=True)
    with st.expander("Raw dataLayer pushes"):
        st.json(cap.get("datalayer", [])[:120])
    ci = cap.get("consent", {})
    if ci.get("tested"):
        st.info(f"Consent test: {'clicked ' + ci['clicked'] if ci.get('clicked') else 'no accept button found'}. "
                f"{ci.get('new_requests', 0)} new requests afterwards.")

with t_net:
    rows = []
    for i, r in enumerate(reqs, 1):
        dur = round((r["end_ms"] - r["start_ms"]), 0) if r.get("end_ms") is not None and r.get("start_ms") is not None else None
        rows.append(dict(No=i, Start_ms=round(r.get("start_ms") or 0), Dur_ms=dur, Status=str(r.get("status") or ("ERR" if r.get("error") else "")),
                         Type=r.get("type", ""), Method=r.get("method", ""), Protocol=r.get("protocol", ""), KB=round((r.get("encoded_size") or 0) / 1024, 1),
                         Party="third" if r.get("third_party") else "first", Host=r.get("host", ""),
                         Loaded_by=pageanalysis.loader_of(r, an["page_reg"], cap.get("final_url", "")), Phase=r.get("phase", ""),
                         Cached="yes" if r.get("from_cache") else "", IP=r.get("ip", ""), Error=r.get("error", ""), URL=r["url"][:220]))
    ndf = pd.DataFrame(rows)
    f1, f2, f3, f4 = st.columns(4)
    ftype = f1.multiselect("Type", sorted(ndf["Type"].unique()) if len(ndf) else [])
    fparty = f2.multiselect("Party", ["first", "third"])
    fstat = f3.multiselect("Status", sorted({str(s) for s in ndf["Status"].unique()}) if len(ndf) else [])
    fq = f4.text_input("Search URL or host")
    v = ndf
    if len(v):
        if ftype:
            v = v[v["Type"].isin(ftype)]
        if fparty:
            v = v[v["Party"].isin(fparty)]
        if fstat:
            v = v[v["Status"].astype(str).isin(fstat)]
        if fq:
            v = v[v["URL"].str.contains(fq, case=False, na=False) | v["Host"].str.contains(fq, case=False, na=False)]
    st.caption(f"{len(v)} of {len(ndf)} requests")
    st.dataframe(v, width="stretch", hide_index=True, height=480)

with t_con:
    cons = cap.get("console", [])
    errs = cap.get("errors", [])
    k1, k2, k3 = st.columns(3)
    k1.metric("Errors", sum(1 for c in cons if c["type"] == "error") + len(errs))
    k2.metric("Warnings", sum(1 for c in cons if c["type"] == "warning"))
    k3.metric("Other messages", sum(1 for c in cons if c["type"] not in ("error", "warning")))
    if errs:
        st.markdown("**Uncaught script errors**")
        st.dataframe(pd.DataFrame(errs), width="stretch", hide_index=True)
    st.markdown("**Console messages**")
    st.dataframe(pd.DataFrame(cons) if cons else pd.DataFrame(columns=["type", "text"]), width="stretch", hide_index=True, height=360)

with t_ck:
    ck = an["cookies"]
    st.markdown("**Cookies set during the visit** (before any consent choice)")
    st.dataframe(pd.DataFrame([dict(Name=c["name"], Domain=c["domain"], Vendor=c["vendor"], Category=c["category"],
                                    Party="third" if c["third_party"] else "first", Secure=c["secure"], HttpOnly=c["httpOnly"],
                                    SameSite=c["sameSite"], Days_left=c["days"]) for c in ck]), width="stretch", hide_index=True)
    if cap.get("consent", {}).get("cookies_after"):
        st.markdown("**Cookie names after accepting the banner:** " + ", ".join(cap["consent"]["cookies_after"][:60]))
    stor = cap.get("storage", {})
    st.markdown(f"**Local storage keys ({len(stor.get('local', []))}):** " + (", ".join(stor.get("local", [])[:60]) or "none"))
    st.markdown(f"**Session storage keys ({len(stor.get('session', []))}):** " + (", ".join(stor.get("session", [])[:60]) or "none"))

with t_perf:
    p = cap.get("perf", {})
    q = st.columns(5)
    q[0].metric("Server response (TTFB)", f"{round(p.get('ttfb') or 0)} ms")
    q[1].metric("First paint", f"{round(p.get('fcp') or 0)} ms")
    q[2].metric("Largest paint (LCP)", f"{round(p.get('lcp') or 0)} ms")
    q[3].metric("Layout shift (CLS)", f"{(p.get('cls') or 0):.3f}")
    q[4].metric("Page loaded", f"{round(p.get('load') or 0)} ms")
    st.caption("One lab run from the machine running this tool. Real-user data (field data) can differ a lot.")
    st.markdown("**By type**")
    st.dataframe(pd.DataFrame([dict(Type=k, Requests=v[0], Size=mb(v[1])) for k, v in sorted(nw["by_type"].items(), key=lambda kv: -kv[1][1])]),
                 width="stretch", hide_index=True)
    st.markdown("**Biggest hosts**")
    st.dataframe(pd.DataFrame([dict(Host=h_, Requests=n, Size=mb(b)) for h_, n, b in nw["by_domain"][:20]]), width="stretch", hide_index=True)
    slow = sorted((r for r in reqs if r.get("end_ms") and r.get("start_ms") is not None), key=lambda r: -(r["end_ms"] - r["start_ms"]))[:12]
    st.markdown("**Slowest requests**")
    st.dataframe(pd.DataFrame([dict(Dur_ms=round(r["end_ms"] - r["start_ms"]), Type=r.get("type", ""), Status=r.get("status"), URL=r["url"][:150]) for r in slow]),
                 width="stretch", hide_index=True)

with t_sec:
    st.markdown("**Security headers on the page**")
    st.dataframe(pd.DataFrame([dict(Header=k, Present="yes" if v else "NO") for k, v in an["security"].items()]), width="stretch", hide_index=True)
    st.markdown("**CDN and hosting evidence**")
    cdn = an["cdn"]
    st.write("First-party static files by CDN: " + (", ".join(f"{k} {v}/{cdn['static_total']}" for k, v in cdn["by_cdn"].items()) or "no evidence"))
    st.write("Detected: " + (", ".join(cdn["detected"]) or "none") + "  ·  Protocols: " + ", ".join(f"{k} {v}" for k, v in nw["protocols"].items()))
    with st.expander("All response headers of the page"):
        st.json(cap.get("doc_headers", {}))
    if cap.get("scripts"):
        with st.expander(f"Scripts in the page ({len(cap['scripts'])})"):
            st.dataframe(pd.DataFrame(cap["scripts"]), width="stretch", hide_index=True)
    if cap.get("iframes"):
        with st.expander(f"Frames and embeds ({len(cap['iframes'])})"):
            st.write(cap["iframes"])

with t_find:
    st.dataframe(pd.DataFrame(F)[["check", "status", "detail"]], width="stretch", hide_index=True)
    st.markdown("**How to fix**")
    for g in knowledge.for_findings(F):
        counts = ", ".join(f"{g[k]} {k.lower()}" for k in ("FAIL", "WARN", "ERROR") if g[k])
        with st.expander(f"{g['check']}  ·  {counts}"):
            st.markdown(f"**Why it matters.** {g['why']}")
            st.markdown(f"**How to fix.** {g['fix']}")
            if g["source"]:
                st.markdown(f"**Source:** [{g['source'][0]}]({g['source'][1]})")
    st.caption("These findings are also added to the reports on the main page.")

with t_dl:
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    host = an["page_host"] or "page"
    d1, d2, d3, d4 = st.columns(4)
    slim = {k: v for k, v in cap.items() if k != "html"}
    d1.download_button("Full capture (.json)", json.dumps(cap, default=str), f"capture-{host}-{stamp}.json", "application/json",
                       help="Every request, console message, cookie and the HTML. Can contain personal identifiers such as client IDs.")
    d2.download_button("Findings (.csv)", report.to_csv(F, report.COLS), f"page-findings-{host}-{stamp}.csv", "text/csv")
    d3.download_button("Report (.html)", report.to_html(F, dict(title=f"Page audit: {host}", user=S.get("email", ""), scope_text=cap.get("final_url", ""), days=0)),
                       f"page-audit-{host}-{stamp}.html", "text/html")
    d4.download_button("Network log (.csv)", ndf.to_csv(index=False).encode("utf-8-sig"), f"network-{host}-{stamp}.csv", "text/csv")
