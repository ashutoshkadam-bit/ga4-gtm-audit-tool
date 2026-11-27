"""Turns a page capture (from the headless browser or the Chrome extension) into technologies, tags, tag hits, network and
performance summaries, and audit findings.
"""
import collections
import json
import re
import time
from urllib.parse import parse_qsl, urljoin, urlparse

from . import techdb

TMS = {"Google Tag Manager", "Adobe Launch (Tags)", "Tealium iQ", "Ensighten", "Segment", "Signal (BrightTag)",
       "GTM (first-party or server-side loader)"}
TRACKING_CATS = {"Analytics", "Advertising", "Customer data / marketing", "Session replay / UX", "A/B testing"}
TAG_CATS = TRACKING_CATS | {"Tag manager", "Consent management"}
STATIC_TYPES = {"Script", "Stylesheet", "Image", "Font", "Media"}
TEXT_MIME = re.compile(r"(javascript|json|html|css|xml|svg|text/)", re.I)
GA4_RE = re.compile(r"(google-analytics|analytics\.google)\.com/g/collect|/g/collect\?v=2", re.I)
UA_COLLECT_RE = re.compile(r"google-analytics\.com/(r/|j/)?collect\?|google-analytics\.com/(analytics|ga)\.js", re.I)
ADOBE_AA_RE = re.compile(r"/b/ss/([^/]+)/", re.I)
ADOBE_EDGE_RE = re.compile(r"edge\.adobedc\.net/ee/|/ee/([a-z0-9]+/)?v\d+/(interact|collect)", re.I)
META_RE = re.compile(r"facebook\.com/tr/?\?|facebook\.com/tr\b", re.I)
GTM_JS_RE = re.compile(r"/gtm\.js\?([^#]*\bid=(GTM-[A-Z0-9]+))", re.I)
GTAG_JS_RE = re.compile(r"googletagmanager\.com/gtag/js\?[^#]*\bid=([A-Z]+-[A-Z0-9-]+)", re.I)
COOKIE_VENDORS = [
    (r"^_ga(_|$)", "Google Analytics", "Analytics"), (r"^_gid$|^_gat", "Google Analytics (UA)", "Analytics"),
    (r"^_gcl_", "Google Ads", "Advertising"), (r"^IDE$|^test_cookie$|^DSID$|^NID$", "Google / DoubleClick", "Advertising"),
    (r"^_fbp$|^_fbc$|^fr$", "Meta", "Advertising"), (r"^_hj", "Hotjar", "Session replay / UX"),
    (r"^_clck$|^_clsk$|^CLID$|^MUID$", "Microsoft Clarity / Bing", "Analytics"), (r"^_uet", "Microsoft Advertising", "Advertising"),
    (r"^_ttp$|^_tt_", "TikTok", "Advertising"), (r"^li_|^bcookie$|^lidc$|^UserMatchHistory$", "LinkedIn", "Advertising"),
    (r"^_pin_|^_pinterest_", "Pinterest", "Advertising"), (r"^ajs_", "Segment", "Analytics"), (r"^mp_", "Mixpanel", "Analytics"),
    (r"^AMCV_|^AMCVS_|^s_cc$|^s_fid$|^s_vi$|^s_sq$|^s_ecid$|^mbox$", "Adobe", "Analytics"), (r"^hubspotutk$|^__hs|^__hstc|^__hssc", "HubSpot", "Customer data / marketing"),
    (r"^_ym_|^_ym", "Yandex Metrica", "Analytics"), (r"^_pk_", "Matomo", "Analytics"),
    (r"^OptanonConsent$|^OptanonAlertBoxClosed$|^CookieConsent$|^cookieyes-consent$|^didomi_token$|^cmplz_", "Consent management", "Consent management"),
]
_COOKIE_RX = [(re.compile(p), v, c) for p, v, c in COOKIE_VENDORS]
# tag script URLs that are loaded by a tag manager rather than hard-coded
LOADER_RULES = [(re.compile(r"googletagmanager\.com/gtm\.js|/gtm\.js\?id=GTM-", re.I), "Google Tag Manager"),
                (re.compile(r"assets\.adobedtm\.com", re.I), "Adobe Launch"), (re.compile(r"tiqcdn\.com", re.I), "Tealium"),
                (re.compile(r"nexus\.ensighten\.com", re.I), "Ensighten"), (re.compile(r"cdn\.segment\.(com|io)", re.I), "Segment")]


def _h(u):
    try:
        return (urlparse(u).hostname or "").lower()
    except ValueError:
        return ""


def _q(u):
    try:
        return dict(parse_qsl(urlparse(u).query, keep_blank_values=True))
    except ValueError:
        return {}


def loader_of(rec, page_reg, page_url=""):
    """How a request was initiated: by a tag manager, by the page HTML, or by some other script."""
    ini = rec.get("initiator_url") or ""
    for rx, name in LOADER_RULES:
        if ini and rx.search(ini):
            return name
    if re.search(r"googletagmanager\.com/gtag/js", ini):
        return "Google tag (gtag.js)"
    if "googletagmanager.com" in ini:
        return "Google Tag Manager"
    t = (rec.get("initiator_type") or "").lower()
    if ini:
        p = urlparse(ini)
        if p.path in ("", "/") and not p.query and not t:
            return "Unknown (only the page origin is known)"  # the Chrome extension cannot see the exact initiator for this request
    if t == "parser" or (not ini and t in ("", "other")):
        return "Page HTML (hard-coded)"
    if ini:
        h = _h(ini)
        same_doc = ini.split("#")[0].rstrip("/") == (page_url or "").split("#")[0].rstrip("/")
        if same_doc:
            return "Inline script in the page (hard-coded)"
        return "Page script (own site)" if techdb.registrable(h) == page_reg else f"Script from {h}"
    return "Script"


def is_hard_coded(loaded_by):
    return loaded_by.startswith(("Page HTML", "Inline script", "Page script"))


# ------------------------------------------------------------------------------------------------------------ hit parsing
def _ga4_events(rec):
    """GA4 sends one event in the URL, or several in the POST body (one per line)."""
    q = _q(rec["url"])
    base = {k: v for k, v in q.items() if k in ("tid", "gcs", "gcd", "dl", "sid", "_p", "dt")}
    events = []
    bodies = [b for b in (rec.get("post") or "").splitlines() if b.strip()]
    if q.get("en"):
        events.append(dict(base, en=q["en"], params={k[3:]: v for k, v in q.items() if k.startswith("ep.")}))
    for line in bodies:
        d = dict(parse_qsl(line, keep_blank_values=True))
        if d.get("en"):
            events.append(dict(base, en=d["en"], params={k[3:]: v for k, v in d.items() if k.startswith("ep.")}))
    if not events:
        events.append(dict(base, en=q.get("en", "(batched)"), params={}))
    for e in events:
        e["t"] = rec.get("start_ms")
        e["phase"] = rec.get("phase", "load")
        e["status"] = rec.get("status")
    return events


def parse_hits(requests):
    out = dict(ga4=[], ua=[], adobe_aa=[], adobe_edge=[], meta=[], ads=[], gtm=[], gtag=[])
    for r in requests:
        u = r["url"]
        if GA4_RE.search(u):
            out["ga4"] += _ga4_events(r)
        elif UA_COLLECT_RE.search(u):
            q = _q(u)
            out["ua"].append(dict(tid=q.get("tid", ""), t=r.get("start_ms"), hit=q.get("t", "script"), ea=q.get("ea", ""),
                                  phase=r.get("phase", "load")))
        m = ADOBE_AA_RE.search(u)
        if m and ("omtrdc" in u or "2o7" in u or r.get("type") in ("Image", "XHR", "Fetch", "Ping")):
            q = _q(u)
            out["adobe_aa"].append(dict(rsid=m.group(1), server=_h(u), page=q.get("pageName", q.get("gn", "")),
                                        events=q.get("events", ""), link=q.get("pe", ""), t=r.get("start_ms"),
                                        phase=r.get("phase", "load")))
        if ADOBE_EDGE_RE.search(u):
            q = _q(u)
            types = []
            try:
                body = json.loads(r.get("post") or "{}")
                for ev in body.get("events", []):
                    types.append((ev.get("xdm") or {}).get("eventType", "(no type)"))
            except ValueError:
                pass
            out["adobe_edge"].append(dict(config=q.get("configId", ""), types=types, t=r.get("start_ms"), phase=r.get("phase", "load")))
        if META_RE.search(u):
            q = _q(u)
            out["meta"].append(dict(pixel=q.get("id", ""), event=q.get("ev", ""), t=r.get("start_ms"), phase=r.get("phase", "load")))
        if re.search(r"googleadservices\.com/pagead/conversion/|/pagead/1p-conversion/|google\.com/pagead/", u, re.I):
            m2 = re.search(r"/conversion/(\d+)", u)
            q = _q(u)
            out["ads"].append(dict(id="AW-" + m2.group(1) if m2 else q.get("tid", ""), label=q.get("label", ""), t=r.get("start_ms"),
                                   phase=r.get("phase", "load")))
        m = GTM_JS_RE.search(u)
        if m and r.get("type") in ("Script", "script", "", None, "Other"):
            out["gtm"].append(dict(id=m.group(2), url=u, status=r.get("status"), t=r.get("start_ms"), t_end=r.get("end_ms"),
                                   size=r.get("encoded_size"), rec=r))
        m = GTAG_JS_RE.search(u)
        if m:
            out["gtag"].append(dict(id=m.group(1), status=r.get("status"), t=r.get("start_ms"), rec=r))
    return out


def _cookie_vendor(name):
    for rx, v, c in _COOKIE_RX:
        if rx.search(name):
            return v, c
    return "", ""


def _is_text_big(r):
    return bool(TEXT_MIME.search(r.get("mime") or "")) and (r.get("encoded_size") or 0) > 10_000


# ------------------------------------------------------------------------------------------------------------ analysis
def analyze(cap):
    reqs = cap.get("requests", [])
    final = cap.get("final_url") or cap.get("url", "")
    page_host = _h(final)
    page_reg = techdb.registrable(page_host)
    for r in reqs:
        r["host"] = _h(r["url"])
        r["third_party"] = techdb.registrable(r["host"]) != page_reg if r["host"] else False
    urls = [r["url"] for r in reqs]
    cookie_names = [c["name"] for c in cap.get("cookies", [])] + list(cap.get("consent", {}).get("cookies_after", []))
    # CDN and server evidence comes from the page's own responses only, so third-party assets do not leak in
    header_sets = [cap.get("doc_headers", {})] + [r.get("resp_headers", {}) for r in reqs[:600] if not r["third_party"]]
    techs = techdb.detect(urls, cap.get("html", ""), cap.get("globals", []), cookie_names, header_sets)
    hits = parse_hits(reqs)

    # per-vendor request attribution (URL signatures only), with first seen time, phase and loader
    vend = collections.OrderedDict()
    for sig, url_re, _h_re, _c_re, _hdr in techdb._COMPILED:  # noqa: SLF001
        if not url_re or sig["category"] not in TAG_CATS:
            continue
        mine = [r for r in reqs if url_re.search(r["url"])]
        if not mine:
            continue
        scripts = [r for r in mine if r.get("type") in ("Script", "script")]
        first = min(mine, key=lambda r: r.get("start_ms") or 0)
        lo = (scripts or [first])[0]
        vend[sig["name"]] = dict(name=sig["name"], category=sig["category"], requests=len(mine),
                                 first_ms=first.get("start_ms"), first_phase=first.get("phase", "load"),
                                 loaded_by=loader_of(lo, page_reg, final), hosts=sorted({r["host"] for r in mine})[:4],
                                 bytes=sum((r.get("encoded_size") or 0) for r in mine),
                                 before_consent=any(r.get("phase", "load") == "load" for r in mine))
    tags = sorted(vend.values(), key=lambda t: (techdb.CATEGORIES.index(t["category"]) if t["category"] in techdb.CATEGORIES else 99, t["name"]))

    # network
    by_type = collections.defaultdict(lambda: [0, 0])
    by_domain = collections.defaultdict(lambda: [0, 0])
    protocols = collections.Counter()
    status = collections.Counter()
    for r in reqs:
        by_type[r.get("type") or "Other"][0] += 1
        by_type[r.get("type") or "Other"][1] += r.get("encoded_size") or 0
        by_domain[r["host"]][0] += 1
        by_domain[r["host"]][1] += r.get("encoded_size") or 0
        if r.get("protocol"):
            protocols[r["protocol"]] += 1
        if r.get("status"):
            status[str(r["status"])[0] + "xx"] += 1
    total_bytes = sum(r.get("encoded_size") or 0 for r in reqs)
    third = [r for r in reqs if r["third_party"]]
    network = dict(
        total_requests=len(reqs), total_bytes=total_bytes, third_party_requests=len(third),
        third_party_hosts=sorted({r["host"] for r in third}), by_type={k: tuple(v) for k, v in by_type.items()},
        by_domain=sorted(((k, *v) for k, v in by_domain.items()), key=lambda x: -x[1])[:40], protocols=dict(protocols),
        status=dict(status), from_cache=sum(1 for r in reqs if r.get("from_cache")))

    # CDN evidence on first-party static assets
    cdn_hits = collections.Counter()
    static_first = [r for r in reqs if not r["third_party"] and r.get("type") in STATIC_TYPES]
    for sig, _u, _h2, _c, hdr in techdb._COMPILED:  # noqa: SLF001
        if sig["category"] != "CDN" or not hdr:
            continue
        for r in static_first:
            rh = r.get("resp_headers", {})
            if any(k in rh and rx.search(rh[k]) for k, rx in hdr.items()):
                cdn_hits[sig["name"]] += 1
    cdn = dict(static_total=len(static_first), by_cdn=dict(cdn_hits),
               detected=[t["name"] for t in techs if t["category"] == "CDN"])

    # cookies
    cookies = []
    for c in cap.get("cookies", []):
        v, cat = _cookie_vendor(c["name"])
        dom = (c.get("domain") or "").lstrip(".")
        cookies.append(dict(c, vendor=v, category=cat, third_party=techdb.registrable(dom) != page_reg,
                            days=(round((c["expires"] - time.time()) / 86400) if (c.get("expires") or -1) > 0 else None)))
    sec = {k: bool(cap.get("doc_headers", {}).get(k)) for k in
           ("strict-transport-security", "content-security-policy", "x-content-type-options", "referrer-policy", "permissions-policy")}
    sec["frame protection"] = bool(cap.get("doc_headers", {}).get("x-frame-options") or
                                   "frame-ancestors" in cap.get("doc_headers", {}).get("content-security-policy", ""))
    dl = collections.Counter()
    for e in cap.get("datalayer", []):
        v = e.get("v")
        if isinstance(v, dict) and v.get("event"):
            dl[str(v["event"])] += 1
        elif isinstance(v, list) and v and isinstance(v[0], str):
            dl[f"gtag:{v[0]}"] += 1
    return dict(page_host=page_host, page_reg=page_reg, technologies=techs, tags=tags, hits=hits, network=network, cdn=cdn,
                cookies=cookies, security=sec, datalayer_events=dict(dl), perf=cap.get("perf", {}))


# ------------------------------------------------------------------------------------------------------------ findings
def to_findings(cap, an):
    host = an["page_host"]
    final = cap.get("final_url") or cap.get("url", "")
    out = []

    def A(check, status, detail=""):
        out.append(dict(scope="PAGE", account=host, entity=final, entity_id=host, check=check, status=status, detail=str(detail)[:500]))

    reqs = cap.get("requests", [])
    if cap.get("nav_error") or (cap.get("status") or 0) >= 400 or not reqs:
        A("Page loads", "FAIL", cap.get("nav_error") or f"HTTP {cap.get('status')}")
        return out
    A("Page loads", "PASS", f"HTTP {cap.get('status')}, {len(reqs)} requests, {cap.get('seconds', '?')}s to audit")
    https = final.startswith("https://")
    A("HTTPS", "PASS" if https else "WARN", "served over https" if https else "the page is served over plain http")
    if https:
        mixed = [r["url"] for r in reqs if r["url"].startswith("http://") and not r["host"].startswith(("localhost", "127."))]
        A("Mixed content", "WARN" if mixed else "PASS", f"{len(mixed)} insecure requests, e.g. {mixed[0][:100]}" if mixed else "none")

    # console and errors
    errs = [c for c in cap.get("console", []) if c["type"] == "error"] + [dict(text=e["text"]) for e in cap.get("errors", [])]
    warns = [c for c in cap.get("console", []) if c["type"] == "warning"]
    A("Console errors", "WARN" if errs else "PASS", (f"{len(errs)} errors, e.g. " + errs[0]["text"][:150]) if errs else f"none ({len(warns)} warnings)")
    failed = [r for r in reqs if r.get("error") and "ERR_ABORTED" not in r["error"] and "blockedbyclient" not in r["error"].lower()]
    A("Failed requests", "WARN" if failed else "PASS", f"{len(failed)} failed, e.g. {failed[0]['url'][:90]} ({failed[0]['error']})" if failed else "none")
    bad = [r for r in reqs if (r.get("status") or 0) >= 400 and r.get("type") not in ("Document",)]
    A("HTTP errors on resources", "WARN" if bad else "PASS", f"{len(bad)} with status 4xx or 5xx, e.g. {bad[0]['url'][:90]} ({bad[0]['status']})" if bad else "none")
    # follow only the page's own redirect chain (other frames, such as ad sync pixels, also redirect)
    doc_redirects, cur = [], next((r for r in reqs if r.get("type") == "Document"), None)
    while cur and 300 <= (cur.get("status") or 0) < 400 and len(doc_redirects) < 12:
        doc_redirects.append(cur)
        loc = cur.get("resp_headers", {}).get("location", "")
        nxt = urljoin(cur["url"], loc) if loc else ""
        cur = next((r for r in reqs if r.get("type") == "Document" and r is not cur and r["url"] == nxt
                    and (r.get("start_ms") or 0) >= (cur.get("start_ms") or 0)), None)
    if doc_redirects:
        A("Redirect chain", "WARN" if len(doc_redirects) > 2 else "INFO", f"{len(doc_redirects)} redirect(s) before the page: " +
          " > ".join(r["url"][:60] for r in doc_redirects[:3]))

    # technologies
    by_cat = collections.defaultdict(list)
    for t in an["technologies"]:
        by_cat[t["category"]].append(t["name"])
    A("Technology stack", "INFO", "; ".join(f"{c}: {', '.join(n)}" for c, n in by_cat.items()) or "nothing recognised")
    consent_tools = [n for n in by_cat.get("Consent management", []) if n != "Google Consent Mode signals"]
    mode = "Google Consent Mode signals" in by_cat.get("Consent management", [])
    A("Consent management", "PASS" if consent_tools else "WARN",
      (", ".join(consent_tools) + ("; Google Consent Mode signals are also sent" if mode else "")) if consent_tools else
      ("only Google Consent Mode signals found, no consent banner tool detected" if mode else "no consent management tool detected"))

    hits = an["hits"]
    # tag managers
    tms = [n for n in by_cat.get("Tag manager", []) if n in TMS]
    gtm_ids = {g["id"] for g in hits["gtm"]}
    html_gtm = set(re.findall(r"\bGTM-[A-Z0-9]{4,8}\b", cap.get("html", "")))
    for g in hits["gtm"][:6]:
        rec = g["rec"]
        dur = round((g["t_end"] or 0) - (g["t"] or 0)) if g.get("t_end") else None
        A("GTM container loads", "PASS" if (g["status"] or 0) == 200 else "WARN",
          f"{g['id']} loaded by {loader_of(rec, an['page_reg'], final)}, starts {round(g['t'] or 0)} ms, took {dur if dur is not None else '?'} ms, "
          f"HTTP {g['status']}")
    for gid in sorted(html_gtm - gtm_ids):
        A("GTM container loads", "WARN", f"{gid} is mentioned in the page HTML but its script was never requested (blocked, waiting for consent, or only referenced in code)")
    if len(gtm_ids) > 1:
        A("Multiple GTM containers", "WARN", f"{len(gtm_ids)} containers loaded: " + ", ".join(sorted(gtm_ids)))
    if len({t for t in tms if t in ("Google Tag Manager", "Adobe Launch (Tags)", "Tealium iQ", "Ensighten")}) > 1:
        A("Multiple tag managers", "WARN", ", ".join(tms))

    # GA4
    ga4_by = collections.defaultdict(list)
    for e in hits["ga4"]:
        ga4_by[e.get("tid", "")].append(e)
    gtag_ids = {g["id"] for g in hits["gtag"] if g["id"].startswith("G-")}
    for tid, evs in ga4_by.items():
        names = collections.Counter(e["en"] for e in evs)
        pv = names.get("page_view", 0)
        A("GA4 hits observed", "PASS" if pv else "INFO", f"{tid}: " + ", ".join(f"{n} x{c}" for n, c in names.most_common(8)))
        seen, dups = {}, []
        for e in evs:
            if e["en"] in ("page_view", "view_item", "purchase", "generate_lead", "form_submit", "form_start"):
                key = (tid, e["en"], e.get("dl", ""))
                if key in seen and abs((e["t"] or 0) - seen[key]) < 3000 and e["phase"] == "load":
                    dups.append(e["en"])
                seen[key] = e["t"] or 0
        if dups:
            A("GA4 duplicate hits", "WARN", f"{tid} received {', '.join(sorted(set(dups)))} more than once within 3 seconds, which double counts")
    for tid in sorted(gtag_ids - set(ga4_by)):
        A("GA4 hits observed", "WARN", f"{tid} is loaded but sent no hit (it may be waiting for consent)")
    if len(ga4_by) > 1:
        A("GA4 properties receiving hits", "INFO", f"{len(ga4_by)} GA4 IDs receive hits from this page: " + ", ".join(sorted(ga4_by)))
    ua = hits["ua"]
    A("Universal Analytics", "FAIL" if ua else "PASS", f"{len(ua)} request(s) to Universal Analytics: {', '.join(sorted({u['tid'] for u in ua if u['tid']})) or 'script only'}" if ua else "none")
    adobe = hits["adobe_aa"] or hits["adobe_edge"]
    if adobe:
        rs = sorted({h["rsid"] for h in hits["adobe_aa"]})
        A("Adobe Analytics hits", "INFO", f"{len(hits['adobe_aa'])} AppMeasurement hit(s) for report suite(s) {', '.join(rs) or '-'}; "
          f"{len(hits['adobe_edge'])} Web SDK edge call(s)")
        if ga4_by:
            A("GA4 and Adobe together", "INFO", "both GA4 and Adobe collect this page's data, so expect numbers to differ between them")
    if hits["meta"]:
        A("Meta pixel hits", "INFO", ", ".join(sorted({f"{m['pixel']}:{m['event']}" for m in hits['meta']}))[:300])

    # tags outside the tag manager
    if tms:
        hard = [t["name"] for t in an["tags"] if t["category"] in TRACKING_CATS and is_hard_coded(t["loaded_by"])]
        A("Tags outside the tag manager", "WARN" if hard else "PASS",
          ("loaded directly from the page, not through the tag manager: " + ", ".join(hard)) if hard else "all tags load through the tag manager")

    # consent behaviour
    pre = [t for t in an["tags"] if t["category"] in TRACKING_CATS and t["before_consent"]]
    pre_names = []
    for t in pre:
        if t["name"] == "Google Analytics 4":
            all_evs = [e for evs in ga4_by.values() for e in evs if e["phase"] == "load"]
            if all_evs and all(e.get("gcs") == "G100" for e in all_evs):
                continue  # Consent Mode with everything denied: only cookieless pings, so not counted as tracking
        pre_names.append(t["name"])
    if pre_names:
        A("Tracking before consent", "WARN", ("a consent tool is present, but " if consent_tools else "no consent tool detected, and ") +
          f"{len(pre_names)} tracking vendor(s) sent requests before any choice: " + ", ".join(pre_names[:10]))
    else:
        A("Tracking before consent", "PASS", "no analytics or advertising vendor made requests before a consent choice")
    track_ck = [c for c in an["cookies"] if c["category"] in TRACKING_CATS]
    if track_ck:
        A("Cookies before consent", "WARN", f"{len(track_ck)} tracking cookies set before any choice: " + ", ".join(c["name"] for c in track_ck[:10]))
    ci = cap.get("consent", {})
    if ci.get("tested"):
        if ci.get("clicked"):
            after = [n for n in ci.get("cookies_after", []) if n not in {c["name"] for c in cap.get("cookies", [])}]
            late = [t["name"] for t in an["tags"] if t["first_phase"] == "after_consent"]
            A("Consent test", "INFO", f"accepted via {ci['clicked'][:60]}; {ci.get('new_requests', 0)} new requests; {len(after)} new cookies"
              + (f"; vendors that only appeared after accepting: {', '.join(late)}" if late else ""))
        else:
            A("Consent test", "INFO", "no visible accept button was found, so behaviour after consent was not tested")

    # data layer
    if cap.get("datalayer"):
        top = sorted(an["datalayer_events"].items(), key=lambda kv: -kv[1])[:8]
        A("dataLayer", "INFO", f"{len(cap['datalayer'])} pushes; events: " + ", ".join(f"{k} x{v}" for k, v in top))
    elif "Google Tag Manager" in by_cat.get("Tag manager", []):
        A("dataLayer", "INFO", "GTM is present but nothing was pushed to dataLayer")

    # third parties, weight, performance
    nw = an["network"]
    th = len(nw["third_party_hosts"])
    A("Third-party requests", "WARN" if th > 30 else "INFO",
      f"{nw['third_party_requests']} of {nw['total_requests']} requests go to {th} third-party hosts")
    mb = nw["total_bytes"] / 1e6
    A("Page weight", "WARN" if mb > 5 else "INFO", f"{mb:.2f} MB transferred over {nw['total_requests']} requests")
    big = sorted((r for r in reqs if (r.get("encoded_size") or 0) > 1_500_000), key=lambda r: -(r["encoded_size"] or 0))
    if big:
        A("Large resources", "WARN", f"{len(big)} over 1.5 MB, largest {big[0]['url'][:80]} ({big[0]['encoded_size'] / 1e6:.1f} MB)")
    p = cap.get("perf", {})
    lcp, fcp, ttfb, cls = p.get("lcp"), p.get("fcp"), p.get("ttfb"), p.get("cls") or 0
    if lcp or fcp or ttfb:
        bad_ = (lcp or 0) > 4000 or (fcp or 0) > 3000 or (ttfb or 0) > 1800
        ok_ = (lcp or 0) <= 2500 and (fcp or 0) <= 1800 and (ttfb or 0) <= 800
        A("Loading speed", "WARN" if bad_ else ("PASS" if ok_ else "INFO"),
          f"server response {round(ttfb or 0)} ms, first paint {round(fcp or 0)} ms, largest paint {round(lcp or 0)} ms (lab test, one run)")
        A("Layout stability", "WARN" if cls > 0.25 else ("INFO" if cls > 0.1 else "PASS"), f"layout shift score {cls:.3f}")
    unc = [r for r in reqs if _is_text_big(r) and not r.get("from_cache") and not r.get("resp_headers", {}).get("content-encoding")
           and r.get("type") in ("Script", "Stylesheet", "Document", "XHR", "Fetch")]
    A("Compression", "WARN" if unc else "PASS", f"{len(unc)} text resources over 10 KB sent uncompressed, e.g. {unc[0]['url'][:80]}" if unc else "text resources are compressed")
    nocache = [r for r in reqs if not r["third_party"] and r.get("type") in STATIC_TYPES and not r.get("from_cache") and r.get("status") == 200
               and "max-age" not in r.get("resp_headers", {}).get("cache-control", "") and not r.get("resp_headers", {}).get("expires")]
    A("Caching", "WARN" if len(nocache) >= 5 else "PASS", f"{len(nocache)} first-party static files have no cache lifetime" if len(nocache) >= 5 else "static files are cacheable")
    pr = nw["protocols"]
    if pr:
        A("HTTP protocol", "INFO", ", ".join(f"{k}: {v}" for k, v in sorted(pr.items(), key=lambda kv: -kv[1])))
    cdn = an["cdn"]
    if cdn["detected"] or cdn["by_cdn"]:
        A("CDN", "INFO", "; ".join(f"{k}: {v} of {cdn['static_total']} first-party static files" for k, v in cdn["by_cdn"].items())
          or "detected: " + ", ".join(cdn["detected"]))
    else:
        A("CDN", "INFO", "no CDN or edge network evidence found for first-party assets")
    blockers = [s for s in cap.get("scripts", []) if s.get("src") and not s.get("async") and not s.get("defer") and s.get("type") != "module"
                and techdb.registrable(_h(s["src"])) != an["page_reg"]]
    if cap.get("scripts"):
        A("Blocking scripts", "WARN" if len(blockers) >= 3 else "INFO", f"{len(blockers)} third-party scripts without async or defer" +
          (": " + ", ".join(_h(s["src"]) for s in blockers[:4]) if blockers else ""))

    # security
    sec = an["security"]
    missing = [k for k, v in sec.items() if not v]
    A("Security headers", "WARN" if len(missing) >= 3 else ("INFO" if missing else "PASS"),
      ("missing: " + ", ".join(missing)) if missing else "all common security headers present")
    ck = an["cookies"]
    if ck:
        insecure = [c["name"] for c in ck if https and not c.get("secure")]
        A("Cookie security", "WARN" if insecure else "PASS", f"{len(insecure)} of {len(ck)} cookies lack the Secure flag: {', '.join(insecure[:6])}" if insecure else f"{len(ck)} cookies, all Secure")
        thirdp = [c["name"] for c in ck if c["third_party"]]
        if thirdp:
            A("Third-party cookies", "INFO", f"{len(thirdp)} cookies from other domains: {', '.join(thirdp[:8])}")
    return out
