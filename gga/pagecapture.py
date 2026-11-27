"""Loads a web page in a real (headless) Chromium browser and records what happens.

It records every network request with timing, size, protocol, server IP, initiator and response headers, every console
message and script error, cookies and storage, JavaScript globals that identify technologies, dataLayer pushes,
performance metrics, and the HTML. The result is one JSON-friendly dict (the "capture") that pageanalysis.py turns into
technologies, tags, findings and tables. The Chrome extension in /extension produces the same format.

Safety: by default every request the page makes is checked and refused if it points to a private or internal network, so
a hosted copy cannot be aimed at internal services. Pages are not interacted with, except the optional consent test
which clicks a visible "accept" button.
"""
import datetime
import os
import re
import shutil
import subprocess
import sys
import time
from urllib.parse import urlparse

from . import log, site, techdb

SCHEMA = "gga-capture-1"
MAX_REQUESTS = 4000
MAX_HTML = 600_000
KEEP_HEADER = re.compile(r"^(content-|cache-control|expires|etag|last-modified|server|via|age|x-|cf-|akamai|fastly|"
                         r"strict-transport|referrer-policy|permissions-policy|access-control|timing-allow|link|vary|"
                         r"alt-svc|set-cookie|location|accept-ch|cross-origin|report-to|nel)", re.I)
BODY_URLS = re.compile(r"collect|/g/|/ee/|/tr[/?]|/b/ss/|/ccm/|analytics|event|track|pixel|/api/", re.I)

INIT_SCRIPT = r"""
(() => {
  if (window.__gga) return;
  const g = window.__gga = {lcp: null, cls: 0, fcp: null, longTasks: 0, dl: [], dlHooked: false};
  const obs = (type, fn) => { try { new PerformanceObserver(l => fn(l.getEntries())).observe({type, buffered: true}); } catch (e) {} };
  obs('largest-contentful-paint', es => { for (const e of es) g.lcp = e.startTime; });
  obs('layout-shift', es => { for (const e of es) if (!e.hadRecentInput) g.cls += e.value; });
  obs('paint', es => { for (const e of es) if (e.name === 'first-contentful-paint') g.fcp = e.startTime; });
  obs('longtask', es => { g.longTasks += es.length; });
  const clean = a => { try { return JSON.parse(JSON.stringify(Array.isArray(a) || (a && a.length !== undefined && typeof a !== 'string') ? Array.from(a) : a)); } catch (e) { return {_unserializable: true}; } };
  const hook = () => {
    const dl = window.dataLayer;
    if (!dl || typeof dl.push !== 'function' || g.dlHooked) return;
    g.dlHooked = true;
    for (const a of dl.slice(0, 200)) g.dl.push({t: performance.now(), v: clean(a), pre: true});
    const orig = dl.push;
    dl.push = function () { for (const a of arguments) { if (g.dl.length < 500) g.dl.push({t: performance.now(), v: clean(a)}); } return orig.apply(this, arguments); };
  };
  hook();
  const iv = setInterval(() => { hook(); if (g.dlHooked) clearInterval(iv); }, 100);
  setTimeout(() => clearInterval(iv), 15000);
})();
"""

COLLECT_SCRIPT = r"""
(names) => {
  const present = [];
  for (const n of names) {
    try { const v = n.split('.').reduce((o, k) => (o == null ? o : o[k]), window); if (v != null) present.push(n); } catch (e) {}
  }
  const nav = performance.getEntriesByType('navigation')[0] || {};
  const g = window.__gga || {};
  return {
    globals: present,
    perf: {ttfb: nav.responseStart || null, dcl: nav.domContentLoadedEventEnd || null, load: nav.loadEventEnd || null,
           fcp: g.fcp || null, lcp: g.lcp || null, cls: g.cls || 0, longTasks: g.longTasks || 0,
           transferSize: nav.transferSize || null, domNodes: document.getElementsByTagName('*').length},
    dataLayer: g.dl || [],
    storage: {local: Object.keys(localStorage || {}), session: Object.keys(sessionStorage || {})},
    title: document.title, lang: document.documentElement.lang || '',
    scripts: Array.from(document.scripts).map(s => ({src: s.src || '', inline: !s.src, async: s.async, defer: s.defer,
                                                  type: s.type || '', len: s.src ? 0 : (s.textContent || '').length})).slice(0, 400),
    meta: Array.from(document.querySelectorAll('meta[name],meta[property]')).slice(0, 60).map(m => [m.getAttribute('name') || m.getAttribute('property'), (m.content || '').slice(0, 200)]),
    iframes: Array.from(document.querySelectorAll('iframe')).map(f => f.src || '').filter(Boolean).slice(0, 60),
    links: {canonical: (document.querySelector('link[rel=canonical]') || {}).href || '', preconnect: Array.from(document.querySelectorAll('link[rel=preconnect],link[rel=dns-prefetch]')).map(l => l.href).slice(0, 40)}
  };
}
"""

CONSENT_SELECTORS = [
    "#onetrust-accept-btn-handler", "#accept-recommended-btn-handler", "button#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    "#CybotCookiebotDialogBodyButtonAccept", ".cky-btn-accept", "button.cky-btn-accept", "#didomi-notice-agree-button",
    "button[data-testid='uc-accept-all-button']", "#truste-consent-button", ".iubenda-cs-accept-btn", ".osano-cm-accept-all",
    "button.cmplz-accept", "#wt-cli-accept-all-btn", "#cookie_action_close_header", "button[aria-label*='accept' i]",
    "[id*='accept' i][id*='cookie' i]", "[class*='accept' i][class*='cookie' i]", "[id*='consent' i] button:has-text('Accept')",
]
CONSENT_TEXT = re.compile(r"^\s*(accept( all| and continue| cookies)?|allow( all| cookies)?|i agree|agree|got it|ok(ay)?|"
                          r"accept & continue|yes,? i agree|consent)\s*$", re.I)


class BrowserUnavailable(RuntimeError):
    """No browser could be started on this machine. The message is plain language and safe to show."""


_install_tried = {"done": False}
_LAUNCH_ARGS = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"]


def find_system_browser():
    """A Chromium-based browser already installed on this machine (used when Playwright's own is missing)."""
    cands = [os.environ.get("GGA_BROWSER_PATH", "")]
    cands += [shutil.which(n) or "" for n in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "chrome", "msedge")]
    cands += [r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", "/usr/bin/chromium", "/usr/bin/chromium-browser",
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    return next((c for c in cands if c and os.path.exists(c)), "")


def launch_browser(p):
    """Starts a headless Chromium. Order: Playwright's own build, a browser already on the system, then a one-time install.
    Raises BrowserUnavailable with a plain message if none works."""
    last = ""
    if os.environ.get("GGA_TEST_NO_BROWSER"):  # lets tests rehearse a server without a browser
        raise BrowserUnavailable("A browser is not available on this server, so the full page audit cannot run here.")
    for attempt in range(2):
        try:
            return p.chromium.launch(headless=True, args=_LAUNCH_ARGS)
        except Exception as e:  # noqa: BLE001
            last = str(e)
        path = find_system_browser()
        if path:
            try:
                return p.chromium.launch(executable_path=path, headless=True, args=_LAUNCH_ARGS)
            except Exception as e:  # noqa: BLE001
                last = str(e)
        if attempt == 0 and not _install_tried["done"] and ("Executable doesn't exist" in last or "playwright install" in last):
            _install_tried["done"] = True
            try:
                subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], capture_output=True, timeout=600)
            except Exception:  # noqa: BLE001
                break
            continue
        break
    log.warning("browser_unavailable", detail=last.replace("\n", " ")[:200])
    raise BrowserUnavailable("A browser is not available on this server, so the full page audit cannot run here.")


def ensure_browser():
    """Returns a short description of the browser that will be used. Raises BrowserUnavailable with a plain message."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise BrowserUnavailable("The browser engine (Playwright) is not installed on this copy of the tool.")
    with sync_playwright() as p:
        b = launch_browser(p)
        v = b.version
        b.close()
    return f"Chromium {v}"


def _globals_to_probe():
    names = set()
    for s in techdb.SIGNATURES:
        names.update(s["js"])
    names.update(["dataLayer", "google_tag_manager", "gtag", "ga", "fbq", "_satellite", "s", "utag", "analytics", "adobe"])
    return sorted(names)


def capture(url, device="desktop", wait_s=8, scroll=True, consent="none", timeout_s=60, allow_private=False,
            progress=lambda msg: None):
    """Loads url and returns a capture dict. consent: 'none' or 'accept' (also test behaviour after clicking accept)."""
    from playwright.sync_api import TimeoutError as PWTimeout, sync_playwright

    url = site.normalize(url)
    if not allow_private:
        site.check_public(url)
    t_start = time.time()
    left = lambda: max(2.0, timeout_s - (time.time() - t_start))  # noqa: E731
    recs, order, state = {}, [], {"phase": "load", "t0": None, "dropped": 0}
    console, errors = [], []
    host_ok = {}

    with sync_playwright() as p:
        browser = launch_browser(p)
        kw = dict(locale="en-US", timezone_id="Asia/Kolkata")
        if device == "mobile":
            kw.update(p.devices["Pixel 7"])
        else:
            kw.update(viewport={"width": 1366, "height": 800})
        ctx = browser.new_context(**kw)
        ctx.add_init_script(INIT_SCRIPT)
        page = ctx.new_page()
        page.set_default_timeout(15000)
        ua = page.evaluate("navigator.userAgent")

        if not allow_private:
            def guard(route):
                u = route.request.url
                if u.startswith(("data:", "blob:", "about:")):
                    return route.continue_()
                h = urlparse(u).hostname or ""
                if h not in host_ok:
                    try:
                        site.check_public(u)
                        host_ok[h] = True
                    except site.BlockedAddress:
                        host_ok[h] = False
                return route.continue_() if host_ok[h] else route.abort("blockedbyclient")
            page.route("**/*", guard)

        cdp = ctx.new_cdp_session(page)
        cdp.send("Network.enable")

        def rel(ts):
            if state["t0"] is None:
                state["t0"] = ts
            return round((ts - state["t0"]) * 1000, 1)

        def on_req(e):
            rid = e["requestId"]
            r = e["request"]
            ini = e.get("initiator", {}) or {}
            ini_url = ini.get("url", "")
            if not ini_url:
                for f in (ini.get("stack", {}) or {}).get("callFrames", [])[:1]:
                    ini_url = f.get("url", "")
            if e.get("redirectResponse") and rid in recs:  # the previous hop of a redirect
                prev = recs[rid]
                prev["status"] = e["redirectResponse"].get("status")
                prev["end_ms"] = rel(e["timestamp"])
                prev["resp_headers"] = {k.lower(): str(v)[:300] for k, v in (e["redirectResponse"].get("headers") or {}).items()
                                        if KEEP_HEADER.match(k)}
                new_id = f"{rid}#r{len(order)}"
                recs[new_id] = recs.pop(rid)
                order[order.index(rid)] = new_id
            if len(order) >= MAX_REQUESTS:
                state["dropped"] += 1
                return
            rec = dict(id=rid, url=r["url"][:2000], method=r["method"], type=e.get("type", ""), status=None, mime="",
                       initiator_type=ini.get("type", ""), initiator_url=ini_url[:500], from_cache=False, protocol="",
                       ip="", encoded_size=None, start_ms=rel(e["timestamp"]), end_ms=None, error="", resp_headers={},
                       post="", phase=state["phase"], tls="")
            if r.get("hasPostData") and BODY_URLS.search(r["url"]):
                rec["post"] = (r.get("postData") or "")[:4000]
                if not rec["post"]:
                    rec["_pending_post"] = True  # fetched from the browser at the end
            recs[rid] = rec
            order.append(rid)

        def on_resp(e):
            rec = recs.get(e["requestId"])
            if not rec:
                return
            resp = e["response"]
            rec["status"] = resp.get("status")
            rec["mime"] = resp.get("mimeType", "")
            rec["protocol"] = resp.get("protocol", "")
            rec["ip"] = resp.get("remoteIPAddress", "")
            rec["from_cache"] = bool(resp.get("fromDiskCache") or resp.get("fromPrefetchCache"))
            rec["resp_headers"] = {k.lower(): str(v)[:300] for k, v in (resp.get("headers") or {}).items() if KEEP_HEADER.match(k)}
            sd = resp.get("securityDetails") or {}
            rec["tls"] = sd.get("protocol", "")

        def on_done(e):
            rec = recs.get(e["requestId"])
            if rec:
                rec["encoded_size"] = e.get("encodedDataLength")
                rec["end_ms"] = rel(e["timestamp"])

        def on_fail(e):
            rec = recs.get(e["requestId"])
            if rec:
                rec["error"] = e.get("errorText", "failed") + (" (blocked: %s)" % e["blockedReason"] if e.get("blockedReason") else "")
                rec["end_ms"] = rel(e["timestamp"])

        cdp.on("Network.requestWillBeSent", on_req)
        cdp.on("Network.responseReceived", on_resp)
        cdp.on("Network.loadingFinished", on_done)
        cdp.on("Network.loadingFailed", on_fail)

        page.on("console", lambda m: console.append(dict(type=m.type, text=m.text[:500], url=(m.location or {}).get("url", "")[:300],
                                                          line=(m.location or {}).get("lineNumber"), phase=state["phase"])) if len(console) < 500 else None)
        page.on("pageerror", lambda e: errors.append(dict(text=str(e)[:500], phase=state["phase"])) if len(errors) < 200 else None)
        page.on("dialog", lambda d: d.dismiss())

        progress("Loading the page")
        main_resp, nav_error = None, ""
        try:
            main_resp = page.goto(url, wait_until="domcontentloaded", timeout=int(min(left(), 40) * 1000))
        except PWTimeout:
            nav_error = "the page did not finish loading in time"
        except Exception as e:  # noqa: BLE001
            nav_error = str(e).split("\n")[0][:300]
        if not nav_error:
            for state_name, cap in (("load", 20), ("networkidle", wait_s)):
                try:
                    page.wait_for_load_state(state_name, timeout=int(min(cap, left()) * 1000))
                except PWTimeout:
                    pass
            if scroll and left() > 6:
                progress("Scrolling to trigger lazy-loaded content")
                try:
                    page.evaluate("""async () => { const h = document.body ? document.body.scrollHeight : 0;
                        for (let y = 0; y < Math.min(h, 9000); y += 700) { window.scrollTo(0, y); await new Promise(r => setTimeout(r, 220)); }
                        window.scrollTo(0, 0); }""")
                    page.wait_for_timeout(1500)
                except Exception:  # noqa: BLE001
                    pass

        def snapshot():
            try:
                return page.evaluate(COLLECT_SCRIPT, _globals_to_probe())
            except Exception:  # noqa: BLE001
                return {}

        collected = snapshot() if not nav_error else {}
        cookies_before = [dict(name=c["name"], domain=c["domain"], path=c["path"], expires=c.get("expires", -1),
                               secure=c["secure"], httpOnly=c["httpOnly"], sameSite=c.get("sameSite", ""))
                          for c in ctx.cookies()]
        html = ""
        if not nav_error:
            try:
                html = page.content()[:MAX_HTML]
            except Exception:  # noqa: BLE001
                pass
        final_url = page.url if not nav_error else url
        doc_headers = {}
        if main_resp:
            try:
                doc_headers = {k.lower(): str(v)[:600] for k, v in main_resp.all_headers().items()}
            except Exception:  # noqa: BLE001
                pass

        # ---- optional consent test: click an accept button and record what changes
        consent_info = dict(tested=False, clicked="", cookies_after=[], new_requests=0)
        if consent == "accept" and not nav_error and left() > 8:
            progress("Looking for a cookie banner to accept")
            clicked = ""
            for sel in CONSENT_SELECTORS:
                try:
                    loc = page.locator(sel).first
                    if loc.count() and loc.is_visible():
                        loc.click(timeout=2500)
                        clicked = sel
                        break
                except Exception:  # noqa: BLE001
                    continue
            if not clicked:
                try:
                    for b in page.get_by_role("button").all()[:40]:
                        if CONSENT_TEXT.match((b.inner_text(timeout=300) or "")[:40]) and b.is_visible():
                            b.click(timeout=2500)
                            clicked = "button: " + (b.inner_text(timeout=300) or "")[:30]
                            break
                except Exception:  # noqa: BLE001
                    pass
            consent_info.update(tested=True, clicked=clicked)
            if clicked:
                n0 = len(order)
                state["phase"] = "after_consent"
                progress("Banner accepted, recording what loads afterwards")
                page.wait_for_timeout(int(min(7, left()) * 1000))
                consent_info["new_requests"] = len(order) - n0
                consent_info["cookies_after"] = [c["name"] for c in ctx.cookies()]

        # ---- fetch request bodies that were sent separately (GA4 batches, Adobe Web SDK, Meta)
        for rid in order:
            rec = recs[rid]
            if rec.pop("_pending_post", False):
                try:
                    rec["post"] = (cdp.send("Network.getRequestPostData", {"requestId": rec["id"]}).get("postData") or "")[:4000]
                except Exception:  # noqa: BLE001
                    pass

        # ---- finish
        try:
            cdp.detach()
        except Exception:  # noqa: BLE001
            pass
        browser.close()

    requests = [recs[i] for i in order]
    return dict(
        schema=SCHEMA, source="playwright", url=url, final_url=final_url, started=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z",
        seconds=round(time.time() - t_start, 1), device=device, user_agent=ua, nav_error=nav_error,
        status=main_resp.status if main_resp else None, doc_headers=doc_headers, requests=requests,
        requests_dropped=state["dropped"], console=console, errors=errors, cookies=cookies_before,
        storage=collected.get("storage", {}), globals=collected.get("globals", []), perf=collected.get("perf", {}),
        datalayer=collected.get("dataLayer", []), title=collected.get("title", ""), lang=collected.get("lang", ""),
        scripts=collected.get("scripts", []), meta=collected.get("meta", []), iframes=collected.get("iframes", []),
        links=collected.get("links", {}), html=html, consent=consent_info)
