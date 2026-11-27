"""Live site check: compares what a website really loads with what Google Analytics and Tag Manager say.

For each address it reads the page HTML, finds Tag Manager containers and GA4 / Universal Analytics IDs, then reads
each container's public script (googletagmanager.com/gtm.js) to see which IDs the published container fires.
It uses plain HTTP requests, no browser, so it sees tags written into the HTML and those a published GTM container
loads. It cannot see tags injected later by other scripts, and it cannot test cookie consent behaviour.

Safety: addresses that resolve to private, local or reserved network ranges are refused (so a hosted copy cannot be
pointed at internal services), redirects are re-checked at every hop, and responses are size-limited.
"""
import ipaddress
import re
import socket
import time
from urllib.parse import urljoin, urlparse

import requests

USER_AGENT = "Mozilla/5.0 (compatible; GA4-GTM-Audit-Tool/1.0; +https://github.com/ashutoshkadam-bit/ga4-gtm-audit-tool)"
MAX_BYTES = 2_000_000
MAX_URLS = 60
MAX_REDIRECTS = 5

GTM_RE = re.compile(r"\bGTM-[A-Z0-9]{4,8}\b")
GA4_RE = re.compile(r"\bG-[A-Z0-9]{8,12}\b")
UA_RE = re.compile(r"\bUA-\d{4,10}-\d{1,4}\b")
AW_RE = re.compile(r"\bAW-\d{6,12}\b")
FBQ_RE = re.compile(r"fbq\(\s*['\"]init['\"]\s*,\s*['\"](\d{8,20})['\"]")
NOSCRIPT_RE = re.compile(r"googletagmanager\.com/ns\.html\?id=GTM-", re.I)


class BlockedAddress(Exception):
    pass


def normalize(url):
    url = url.strip()
    if not url:
        return ""
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    return url


def _check_public(url):
    """Refuses anything that is not a public http(s) address. (A determined DNS-rebinding attack could still race this
    check, so only expose the hosted tool to signed-in staff, as it is by default.)"""
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise BlockedAddress("only http and https addresses are allowed")
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80))
    except OSError:
        raise BlockedAddress("the address could not be resolved")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast
                or ip.is_unspecified):
            raise BlockedAddress("this address points to a private or internal network, which is not allowed")


def safe_fetch(url, session=None):
    """Returns (status_code, final_url, text, error). error is empty on success."""
    s = session or requests.Session()
    cur = normalize(url)
    try:
        for _ in range(MAX_REDIRECTS + 1):
            _check_public(cur)
            r = s.get(cur, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"}, timeout=(6, 15),
                      stream=True, allow_redirects=False)
            if r.is_redirect or r.is_permanent_redirect:
                loc = r.headers.get("Location")
                r.close()
                if not loc:
                    return r.status_code, cur, "", "redirect without a destination"
                cur = urljoin(cur, loc)
                continue
            body = r.raw.read(MAX_BYTES + 1, decode_content=True)
            r.close()
            text = body[:MAX_BYTES].decode(r.encoding or "utf-8", errors="replace")
            return r.status_code, cur, text, ""
        return 0, cur, "", "too many redirects"
    except BlockedAddress as e:
        return 0, cur, "", f"blocked: {e}"
    except requests.RequestException as e:
        return 0, cur, "", f"could not load: {type(e).__name__}"


def extract_ids(text):
    return dict(gtm=sorted(set(GTM_RE.findall(text))), ga4=sorted(set(GA4_RE.findall(text))),
                ua=sorted(set(UA_RE.findall(text))), aw=sorted(set(AW_RE.findall(text))),
                fbq=sorted(set(FBQ_RE.findall(text))))


def scan_url(url, known_containers=None, known_ga4=None, session=None, gtm_cache=None):
    """Returns a list of findings for one website address."""
    s = session or requests.Session()
    gtm_cache = gtm_cache if gtm_cache is not None else {}
    status, final, html, err = safe_fetch(url, s)
    host = urlparse(final).hostname or urlparse(normalize(url)).hostname or ""
    out = []

    def A(check, st, detail=""):
        out.append(dict(scope="SITE", account=host, entity=final, entity_id=host, check=check, status=st,
                        detail=str(detail)[:500]))

    if err or status >= 400:
        A("Page loads", "FAIL", err or f"HTTP {status}")
        return out
    A("Page loads", "PASS", f"HTTP {status}")
    page = extract_ids(html)

    # What each GTM container on the page fires (its published public script)
    via_gtm = dict(ga4=set(), ua=set(), aw=set(), fbq=set())
    for cid in page["gtm"][:4]:
        if cid not in gtm_cache:
            st, _, js, e = safe_fetch(f"https://www.googletagmanager.com/gtm.js?id={cid}", s)
            gtm_cache[cid] = (st, extract_ids(js) if not e and st == 200 else None)
            time.sleep(0.2)
        st, ids = gtm_cache[cid]
        if ids is None:
            A("GTM container published", "WARN", f"{cid}: Google returned HTTP {st or 'an error'} for its public script, "
              "so it may not exist or be unpublished")
            continue
        for k in via_gtm:
            via_gtm[k].update(ids[k])

    # --- Tag Manager
    if not page["gtm"]:
        A("GTM installed", "WARN", "no GTM container ID found in the page HTML (it may be added by a plugin or script)")
    else:
        A("GTM installed", "PASS", ", ".join(page["gtm"]))
        if len(page["gtm"]) > 1:
            A("Multiple GTM containers", "WARN", f"{len(page['gtm'])} containers on one page: " + ", ".join(page["gtm"]))
        if not NOSCRIPT_RE.search(html):
            A("GTM noscript snippet", "INFO", "the <noscript> iframe from the GTM install guide was not found")
        if known_containers is not None:
            missing = [c for c in page["gtm"] if c not in known_containers]
            A("GTM container in your accounts", "WARN" if missing else "PASS",
              ("not in the GTM accounts you can open: " + ", ".join(missing)) if missing else "all found containers are yours")

    # --- GA4
    all_ga4 = sorted(set(page["ga4"]) | via_gtm["ga4"])
    if not all_ga4:
        A("GA4 tag present", "WARN", "no GA4 measurement ID found in the page or in its GTM containers")
    else:
        A("GA4 tag present", "PASS", ", ".join(all_ga4))
        if len(all_ga4) > 2:
            A("Many GA4 IDs", "WARN", f"{len(all_ga4)} different GA4 IDs: " + ", ".join(all_ga4))
        both = sorted(set(page["ga4"]) & via_gtm["ga4"])
        if both:
            A("GA4 loaded twice", "WARN", "same ID in the page HTML and inside GTM, which can double count: " + ", ".join(both))
        if known_ga4 is not None:
            missing = [g for g in all_ga4 if g not in known_ga4]
            A("GA4 ID in your properties", "WARN" if missing else "PASS",
              ("not in the GA4 properties you can open: " + ", ".join(missing)) if missing else "all found IDs are yours")

    # --- Universal Analytics and other vendors
    ua = sorted(set(page["ua"]) | via_gtm["ua"])
    A("Universal Analytics", "FAIL" if ua else "PASS", ", ".join(ua) if ua else "none found")
    other = []
    aw = sorted(set(page["aw"]) | via_gtm["aw"])
    fbq = sorted(set(page["fbq"]) | via_gtm["fbq"])
    if aw:
        other.append("Google Ads: " + ", ".join(aw))
    if fbq:
        other.append("Meta pixel: " + ", ".join(fbq))
    A("Other tracking IDs", "INFO", "; ".join(other) if other else "none found")
    return out


def run_site_check(urls, known_containers=None, known_ga4=None, progress=None, should_stop=lambda: False):
    seen, todo = set(), []
    for u in urls:
        n = normalize(u)
        key = (urlparse(n).hostname or "", urlparse(n).path.rstrip("/"))
        if n and key not in seen:
            seen.add(key)
            todo.append(n)
    todo = todo[:MAX_URLS]
    findings, cache = [], {}
    s = requests.Session()
    for i, u in enumerate(todo, 1):
        if should_stop():
            break
        if progress:
            progress(i, len(todo), u)
        findings += scan_url(u, known_containers, known_ga4, s, cache)
        time.sleep(0.4)
    return findings
