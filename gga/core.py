"""Audit engine: read-only checks for Google Analytics 4 properties and Tag Manager containers."""
import collections
import json
import re
import time

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

GID = re.compile(r"^G-[A-Z0-9]{6,}$")
GID_ANY = re.compile(r"\bG-[A-Z0-9]{6,}\b")

DEFAULTS = {
    "ga4_settings": True,      # retention, streams, key events, links, signals, attribution...
    "ga4_data": True,          # event volume, key events firing, unassigned traffic (Data API)
    "gtm": True,               # container hygiene checks
    "days": 30,                # data window for GA4 data checks
    "unassigned_threshold": 10,
    "html_threshold": 5,
    "delay": 0.3,              # seconds between GTM containers (API rate limits)
}

CHECKS = {
    "GA4 settings": ["Property details", "Data retention", "Data streams", "Enhanced measurement", "Key events",
                     "Custom dimensions", "Custom metrics", "Google Ads links", "BigQuery links", "Google Signals",
                     "Attribution settings", "Currency vs timezone", "Internal traffic filter"],
    "GA4 data": ["Events last 30d", "page_view present", "Key events firing", "Unassigned traffic"],
    "GTM hygiene": ["Published version", "Tags present", "Paused tags", "Tags with no firing trigger", "Unused triggers",
                    "Unused variables", "Duplicate tags", "Universal Analytics remnants", "Hardcoded GA4 IDs in tags",
                    "Custom HTML tags", "Default/test tag names", "Tag consent settings", "GA4 IDs referenced"],
    "Cross-check": ["GA4 ID not in accessible properties"],
}


def short_err(e):
    if isinstance(e, HttpError):
        try:
            return json.loads(e.content)["error"]["message"][:200]
        except Exception:
            return str(e)[:200]
    return str(e)[:200]


def paged(method, key, **kw):
    out, tok = [], None
    while True:
        r = method(pageToken=tok, **kw).execute(num_retries=5)
        out += r.get(key, [])
        tok = r.get("nextPageToken")
        if not tok:
            return out


def tparam(tag, key):
    for p in tag.get("parameter", []):
        if p.get("key") == key:
            return p.get("value")
    return None


class Auditor:
    def __init__(self, creds, options=None):
        self.o = {**DEFAULTS, **(options or {})}
        kw = dict(credentials=creds, cache_discovery=False)
        self.admin = build("analyticsadmin", "v1beta", **kw)
        self.alpha = build("analyticsadmin", "v1alpha", **kw)
        self.data = build("analyticsdata", "v1beta", **kw)
        self.gtm = build("tagmanager", "v2", **kw)

    # ------------------------------------------------------------ discovery
    def list_ga4(self):
        rows = []
        for a in paged(self.admin.accountSummaries().list, "accountSummaries", pageSize=200):
            for p in a.get("propertySummaries", []):
                rows.append(dict(account=a["displayName"], account_id=a["account"], property=p["displayName"],
                                 property_name=p["property"]))
        return rows

    def list_gtm(self, progress=None):
        rows = []
        accounts = paged(self.gtm.accounts().list, "account")
        for i, a in enumerate(accounts, 1):
            if progress:
                progress(i, len(accounts), a["name"])
            for c in paged(self.gtm.accounts().containers().list, "container", parent=a["path"]):
                rows.append(dict(account=a["name"], account_id=a["accountId"], container=c["name"],
                                 public_id=c["publicId"], path=c["path"],
                                 usage=",".join(c.get("usageContext", []))))
            time.sleep(0.3)
        return rows

    # ------------------------------------------------------------ GA4
    def audit_ga4_property(self, p):
        """Returns (findings, inventory_row)."""
        out = []
        pname, pdisp, acct = p["property_name"], p["property"], p["account"]
        pid = pname.split("/")[1]

        def A(check, status, detail=""):
            out.append(dict(scope="GA4", account=acct, entity=pdisp, entity_id=pid, check=check,
                            status=status, detail=str(detail)[:500]))

        def safe(check, fn):
            try:
                return fn()
            except Exception as e:  # noqa: BLE001
                A(check, "ERROR", short_err(e))
                return None

        mids, ke_names, has_web = [], [], False
        if self.o["ga4_settings"]:
            info = safe("Property details", lambda: self.admin.properties().get(name=pname).execute(num_retries=5))
            if info:
                A("Property details", "INFO", f"tz={info.get('timeZone')} currency={info.get('currencyCode')} "
                  f"industry={info.get('industryCategory')} level={info.get('serviceLevel')}")
                if info.get("currencyCode") == "USD" and info.get("timeZone", "").startswith("Asia/"):
                    A("Currency vs timezone", "WARN", "USD currency with Asia timezone - confirm intended")
            ret = safe("Data retention", lambda: self.admin.properties().getDataRetentionSettings(
                name=pname + "/dataRetentionSettings").execute(num_retries=5))
            if ret:
                v = ret.get("eventDataRetention")
                A("Data retention", "PASS" if v == "FOURTEEN_MONTHS" else "WARN", f"event retention={v}")
            streams = safe("Data streams", lambda: paged(self.admin.properties().dataStreams().list,
                                                         "dataStreams", parent=pname))
            if streams is not None:
                if streams:
                    A("Data streams", "PASS", ", ".join(
                        f"{s.get('type', '').replace('_DATA_STREAM', '')}:{s.get('displayName')}" for s in streams)[:300])
                else:
                    A("Data streams", "FAIL", "no data streams")
                for s in streams:
                    if s.get("type") == "WEB_DATA_STREAM":
                        has_web = True
                        mid = s.get("webStreamData", {}).get("measurementId")
                        if mid:
                            mids.append(mid)
                        em = safe("Enhanced measurement", lambda s=s: self.alpha.properties().dataStreams()
                                  .getEnhancedMeasurementSettings(name=s["name"] + "/enhancedMeasurementSettings")
                                  .execute(num_retries=5))
                        if em is not None:
                            A("Enhanced measurement", "PASS" if em.get("streamEnabled") else "WARN",
                              f"{s.get('displayName')}: enabled={bool(em.get('streamEnabled'))}")
            ke = safe("Key events", lambda: paged(self.admin.properties().keyEvents().list, "keyEvents", parent=pname))
            if ke is not None:
                ke_names = [k["eventName"] for k in ke]
                A("Key events", "PASS" if ke else "FAIL", f"{len(ke)}: " + ", ".join(ke_names)[:300])
            cd = safe("Custom dimensions", lambda: paged(self.admin.properties().customDimensions().list,
                                                         "customDimensions", parent=pname))
            if cd is not None:
                A("Custom dimensions", "WARN" if len(cd) > 40 else "INFO",
                  f"{len(cd)} defined (event-scope limit 50, user-scope 25)")
            cm = safe("Custom metrics", lambda: paged(self.admin.properties().customMetrics().list,
                                                      "customMetrics", parent=pname))
            if cm is not None:
                A("Custom metrics", "INFO", f"{len(cm)} defined")
            ads = safe("Google Ads links", lambda: paged(self.admin.properties().googleAdsLinks().list,
                                                         "googleAdsLinks", parent=pname))
            if ads is not None:
                A("Google Ads links", "INFO", f"{len(ads)} linked")
            bq = safe("BigQuery links", lambda: paged(self.alpha.properties().bigQueryLinks().list,
                                                      "bigqueryLinks", parent=pname))
            if bq is not None:
                A("BigQuery links", "INFO", f"{len(bq)} linked")
            A("Internal traffic filter", "INFO", "not exposed by Google's API - verify manually")
            gs = safe("Google Signals", lambda: self.alpha.properties().getGoogleSignalsSettings(
                name=pname + "/googleSignalsSettings").execute(num_retries=5))
            if gs is not None:
                A("Google Signals", "INFO", f"state={gs.get('state')}")
            att = safe("Attribution settings", lambda: self.alpha.properties().getAttributionSettings(
                name=pname + "/attributionSettings").execute(num_retries=5))
            if att is not None:
                A("Attribution settings", "INFO", f"model={att.get('reportingAttributionModel')} "
                  f"acquisition window={att.get('acquisitionConversionEventLookbackWindow')} "
                  f"other window={att.get('otherConversionEventLookbackWindow')}")

        if self.o["ga4_data"]:
            days = int(self.o["days"])
            rng = [{"startDate": f"{days}daysAgo", "endDate": "yesterday"}]
            body = {"dateRanges": rng, "dimensions": [{"name": "eventName"}],
                    "metrics": [{"name": "eventCount"}], "limit": 1000}
            ev = safe("Events last 30d", lambda: self.data.properties().runReport(property=pname, body=body)
                      .execute(num_retries=5))
            if ev is not None:
                counts = {r["dimensionValues"][0]["value"]: int(r["metricValues"][0]["value"])
                          for r in ev.get("rows", [])}
                total = sum(counts.values())
                if total == 0:
                    A("Events last 30d", "FAIL", f"no events received in last {days} days")
                else:
                    A("Events last 30d", "PASS", f"{total} events, {len(counts)} distinct")
                    if has_web and "page_view" not in counts:
                        A("page_view present", "WARN", f"web stream but no page_view in {days}d")
                    silent = [k for k in ke_names if counts.get(k, 0) == 0]
                    if silent:
                        A("Key events firing", "WARN", f"no hits in {days}d: " + ", ".join(silent)[:300])
                    elif ke_names:
                        A("Key events firing", "PASS", f"all key events seen in {days}d")
                    body2 = {"dateRanges": rng, "dimensions": [{"name": "sessionDefaultChannelGroup"}],
                             "metrics": [{"name": "sessions"}]}
                    ch = safe("Unassigned traffic", lambda: self.data.properties().runReport(
                        property=pname, body=body2).execute(num_retries=5))
                    if ch and ch.get("rows"):
                        m = {r["dimensionValues"][0]["value"]: int(r["metricValues"][0]["value"]) for r in ch["rows"]}
                        share = m.get("Unassigned", 0) / (sum(m.values()) or 1) * 100
                        A("Unassigned traffic", "WARN" if share > self.o["unassigned_threshold"] else "PASS",
                          f"{share:.1f}% of sessions")
        time.sleep(0.15)
        return out, dict(scope="GA4", account=acct, entity=pdisp, entity_id=pid, ids=" ".join(mids))

    # ------------------------------------------------------------ GTM
    def audit_gtm_container(self, c):
        out = []
        acct, cname, cid = c["account"], c["container"], c["public_id"]
        ent = f"{cname} ({c.get('usage', '')})" if c.get("usage") else cname

        def A(check, status, detail=""):
            out.append(dict(scope="GTM", account=acct, entity=ent, entity_id=cid, check=check,
                            status=status, detail=str(detail)[:500]))

        try:
            v = self.gtm.accounts().containers().versions().live(parent=c["path"]).execute(num_retries=5)
        except HttpError as e:
            A("Published version", "FAIL" if e.resp.status == 404 else "ERROR",
              "container never published" if e.resp.status == 404 else short_err(e))
            return out, dict(scope="GTM", account=acct, entity=ent, entity_id=cid, ids="")
        tags, trigs, vars_ = v.get("tag", []), v.get("trigger", []), v.get("variable", [])
        A("Published version", "PASS", f"live v{v.get('containerVersionId')} '{v.get('name', '')}': "
          f"{len(tags)} tags, {len(trigs)} triggers, {len(vars_)} variables")
        if not tags:
            A("Tags present", "WARN", "live version has no tags")
        blob = json.dumps(v)
        ids = sorted(set(GID_ANY.findall(blob)))
        names = lambda xs: ", ".join(xs)[:300]  # noqa: E731

        paused = [t["name"] for t in tags if t.get("paused")]
        A("Paused tags", "WARN" if paused else "PASS", f"{len(paused)}: " + names(paused))
        used = set()
        for t in tags:
            used.update(t.get("firingTriggerId", []))
            used.update(t.get("blockingTriggerId", []))
        for t in trigs:
            if t.get("type") == "triggerGroup":
                used.update(re.findall(r"\d+", json.dumps(t.get("parameter", []))))
        notrig = [t["name"] for t in tags if not t.get("firingTriggerId") and not t.get("paused")
                  and not t.get("setupTag") and not t.get("teardownTag")]
        A("Tags with no firing trigger", "WARN" if notrig else "PASS", f"{len(notrig)}: " + names(notrig))
        ut = [t["name"] for t in trigs if t["triggerId"] not in used]
        A("Unused triggers", "WARN" if ut else "PASS", f"{len(ut)}: " + names(ut))
        uv = [x["name"] for x in vars_ if blob.count("{{" + x["name"] + "}}") == 0]
        A("Unused variables", "WARN" if uv else "PASS", f"{len(uv)}: " + names(uv))
        groups = collections.defaultdict(list)
        for t in tags:
            key = (t.get("type"), json.dumps(sorted(t.get("parameter", []), key=lambda p: p.get("key", "")),
                                             sort_keys=True), tuple(sorted(t.get("firingTriggerId", []))))
            groups[key].append(t["name"])
        dups = [" = ".join(n) for n in groups.values() if len(n) > 1]
        A("Duplicate tags", "WARN" if dups else "PASS", f"{len(dups)}: " + "; ".join(dups)[:300])
        ua = [t["name"] for t in tags if t.get("type") == "ua" or "UA-" in json.dumps(t.get("parameter", []))]
        A("Universal Analytics remnants", "FAIL" if ua else "PASS", names(ua))
        hard = [t["name"] for t in tags if t.get("type") in ("gaawe", "gaawc", "googtag")
                and GID.match(tparam(t, "measurementId") or tparam(t, "tagId") or "")]
        A("Hardcoded GA4 IDs in tags", "WARN" if hard else "PASS", f"{len(hard)}: " + names(hard))
        html = [t for t in tags if t.get("type") == "html"]
        A("Custom HTML tags", "WARN" if len(html) > self.o["html_threshold"] else "INFO", f"{len(html)} custom HTML tags")
        bad = [t["name"] for t in tags if re.match(r"^(New Tag|Untitled|Copy of|test)", t["name"], re.I)]
        A("Default/test tag names", "WARN" if bad else "PASS", names(bad))
        nc = [t for t in tags if t.get("consentSettings", {}).get("consentStatus", "notSet") == "notSet"]
        A("Tag consent settings", "INFO" if nc else "PASS", f"{len(nc)}/{len(tags)} tags have no additional consent settings")
        A("GA4 IDs referenced", "INFO", " ".join(ids))
        time.sleep(self.o["delay"])
        return out, dict(scope="GTM", account=acct, entity=ent, entity_id=cid, ids=" ".join(ids))


def cross_check(inventory, known_ids):
    """Flag GTM containers whose GA4 IDs are not in any GA4 property the user can access."""
    out = []
    if not known_ids:
        return out
    for r in inventory:
        if r["scope"] != "GTM":
            continue
        for gid in r["ids"].split():
            if gid not in known_ids:
                out.append(dict(scope="GTM", account=r["account"], entity=r["entity"], entity_id=r["entity_id"],
                                check="GA4 ID not in accessible properties", status="WARN",
                                detail=f"{gid} not found among the GA4 web streams you can access"))
    return out


def run_audit(auditor, ga4_props, gtm_containers, known_ids=None, progress=None, should_stop=lambda: False):
    """Runs the audit. progress(done, total, label) is called after each entity."""
    findings, inventory = [], []
    total, done = len(ga4_props) + len(gtm_containers), 0
    jobs = [("GA4", p) for p in ga4_props] + [("GTM", c) for c in gtm_containers]
    for kind, item in jobs:
        if should_stop():
            break
        label = (item["property"] if kind == "GA4" else item["container"])
        try:
            f, inv = (auditor.audit_ga4_property(item) if kind == "GA4" else auditor.audit_gtm_container(item))
        except Exception as e:  # noqa: BLE001
            f = [dict(scope=kind, account=item["account"], entity=label, entity_id="", check="Audit",
                      status="ERROR", detail=short_err(e))]
            inv = None
        findings += f
        if inv:
            inventory.append(inv)
        done += 1
        if progress:
            progress(done, total, f"{kind}: {item['account']} / {label}")
    if known_ids is None:
        known_ids = {i for r in inventory if r["scope"] == "GA4" for i in r["ids"].split()}
    findings += cross_check(inventory, known_ids)
    return findings, inventory


def all_ga4_measurement_ids(auditor, ga4_rows, progress=None):
    """Measurement IDs of every accessible GA4 web stream (used by the cross-check)."""
    ids = set()
    for i, p in enumerate(ga4_rows, 1):
        if progress:
            progress(i, len(ga4_rows), p["property"])
        try:
            for s in paged(auditor.admin.properties().dataStreams().list, "dataStreams", parent=p["property_name"]):
                m = s.get("webStreamData", {}).get("measurementId")
                if m:
                    ids.add(m)
        except Exception:  # noqa: BLE001
            pass
    return ids
