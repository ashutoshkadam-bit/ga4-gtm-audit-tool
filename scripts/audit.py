"""GA4 + GTM audit. Read-only. Uses Application Default Credentials.

Usage:
  python audit.py                    # everything
  python audit.py --only ga4 --limit 3
  python audit.py --only gtm --limit 5
Outputs CSVs into ./audit_output/<timestamp>/
"""
import argparse, csv, datetime, json, os, pathlib, re, time, collections
import google.auth
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

PROJECT = os.environ.get("AUDIT_PROJECT", "")  # your Google Cloud project ID (needed for gcloud ADC logins)
SCOPES = [
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/tagmanager.readonly",
]
GID = re.compile(r"^G-[A-Z0-9]{6,}$")
GID_ANY = re.compile(r"\bG-[A-Z0-9]{6,}\b")

ACCOUNT_FILTER = []   # lowercase substrings; empty = all accounts


def match_acct(name):
    return not ACCOUNT_FILTER or any(s in name.lower() for s in ACCOUNT_FILTER)


findings = []   # long format
inventory = {"GA4": [], "GTM": []}


def add(scope, account, entity, eid, check, status, detail=""):
    findings.append(dict(scope=scope, account=account, entity=entity, entity_id=eid,
                         check=check, status=status, detail=str(detail)[:500]))


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


# ---------------------------------------------------------------- GA4
def audit_ga4(creds, limit):
    admin = build("analyticsadmin", "v1beta", credentials=creds, cache_discovery=False)
    alpha = build("analyticsadmin", "v1alpha", credentials=creds, cache_discovery=False)
    data = build("analyticsdata", "v1beta", credentials=creds, cache_discovery=False)
    props = []
    for a in paged(admin.accountSummaries().list, "accountSummaries", pageSize=200):
        for p in a.get("propertySummaries", []):
            props.append((a["displayName"], p["property"], p["displayName"]))
    props = [p for p in props if match_acct(p[0])]
    if limit:
        props = props[:limit]
    print(f"GA4: auditing {len(props)} properties")
    for i, (acct, pname, pdisp) in enumerate(props, 1):
        pid = pname.split("/")[1]
        print(f"  [{i}/{len(props)}] {acct} / {pdisp}", flush=True)

        def A(check, status, detail=""):
            add("GA4", acct, pdisp, pid, check, status, detail)

        def safe(check, fn):
            try:
                return fn()
            except Exception as e:
                A(check, "ERROR", short_err(e))
                return None

        info = safe("Property details", lambda: admin.properties().get(name=pname).execute(num_retries=5))
        if info:
            A("Property details", "INFO", f"tz={info.get('timeZone')} currency={info.get('currencyCode')} "
              f"industry={info.get('industryCategory')} level={info.get('serviceLevel')}")
            if info.get("currencyCode") == "USD" and info.get("timeZone", "").startswith("Asia/"):
                A("Currency vs timezone", "WARN", "USD currency with Asia timezone - confirm intended")

        ret = safe("Data retention", lambda: admin.properties().getDataRetentionSettings(
            name=pname + "/dataRetentionSettings").execute(num_retries=5))
        if ret:
            v = ret.get("eventDataRetention")
            A("Data retention", "PASS" if v == "FOURTEEN_MONTHS" else "WARN", f"event retention={v}")

        streams = safe("Data streams", lambda: paged(admin.properties().dataStreams().list,
                                                     "dataStreams", parent=pname)) or []
        mids = []
        if streams:
            A("Data streams", "PASS", ", ".join(f"{s.get('type','').replace('_DATA_STREAM','')}:{s.get('displayName')}"
                                                for s in streams)[:300])
        elif streams == []:
            A("Data streams", "FAIL", "no data streams")
        for s in streams:
            if s.get("type") == "WEB_DATA_STREAM":
                mid = s.get("webStreamData", {}).get("measurementId")
                if mid:
                    mids.append(mid)
                em = safe("Enhanced measurement", lambda s=s: alpha.properties().dataStreams()
                          .getEnhancedMeasurementSettings(name=s["name"] + "/enhancedMeasurementSettings")
                          .execute(num_retries=5))
                if em is not None:
                    A("Enhanced measurement", "PASS" if em.get("streamEnabled") else "WARN",
                      f"{s.get('displayName')}: enabled={em.get('streamEnabled')}")
        inventory["GA4"].append(dict(account=acct, property=pdisp, property_id=pid, measurement_ids=" ".join(mids)))

        ke = safe("Key events", lambda: paged(admin.properties().keyEvents().list, "keyEvents", parent=pname))
        ke_names = [k["eventName"] for k in ke] if ke is not None else []
        if ke is not None:
            A("Key events", "PASS" if ke else "FAIL", f"{len(ke)}: " + ", ".join(ke_names)[:300])

        cd = safe("Custom dimensions", lambda: paged(admin.properties().customDimensions().list,
                                                     "customDimensions", parent=pname))
        if cd is not None:
            A("Custom dimensions", "WARN" if len(cd) > 40 else "INFO", f"{len(cd)} defined (event-scope limit 50)")
        cm = safe("Custom metrics", lambda: paged(admin.properties().customMetrics().list,
                                                  "customMetrics", parent=pname))
        if cm is not None:
            A("Custom metrics", "INFO", f"{len(cm)} defined")

        ads = safe("Google Ads links", lambda: paged(admin.properties().googleAdsLinks().list,
                                                     "googleAdsLinks", parent=pname))
        if ads is not None:
            A("Google Ads links", "INFO", f"{len(ads)} linked")
        bq = safe("BigQuery links", lambda: paged(alpha.properties().bigQueryLinks().list,
                                                  "bigqueryLinks", parent=pname))
        if bq is not None:
            A("BigQuery links", "INFO", f"{len(bq)} linked")

        A("Internal traffic filter", "INFO", "not exposed by Google's API - verify manually")
        gs = safe("Google Signals", lambda: alpha.properties().getGoogleSignalsSettings(
            name=pname + "/googleSignalsSettings").execute(num_retries=5))
        if gs is not None:
            A("Google Signals", "INFO", f"state={gs.get('state')}")
        att = safe("Attribution settings", lambda: alpha.properties().getAttributionSettings(
            name=pname + "/attributionSettings").execute(num_retries=5))
        if att is not None:
            A("Attribution settings", "INFO", f"model={att.get('reportingAttributionModel')} "
              f"acquisition window={att.get('acquisitionConversionEventLookbackWindow')} "
              f"other window={att.get('otherConversionEventLookbackWindow')}")

        body = {"dateRanges": [{"startDate": "30daysAgo", "endDate": "yesterday"}],
                "dimensions": [{"name": "eventName"}], "metrics": [{"name": "eventCount"}], "limit": 1000}
        ev = safe("Events last 30d", lambda: data.properties().runReport(property=pname, body=body)
                  .execute(num_retries=5))
        if ev is not None:
            counts = {r["dimensionValues"][0]["value"]: int(r["metricValues"][0]["value"]) for r in ev.get("rows", [])}
            total = sum(counts.values())
            if total == 0:
                A("Events last 30d", "FAIL", "no events received in last 30 days")
            else:
                A("Events last 30d", "PASS", f"{total} events, {len(counts)} distinct")
                if "page_view" not in counts and any(s.get("type") == "WEB_DATA_STREAM" for s in streams):
                    A("page_view present", "WARN", "web stream but no page_view in 30d")
                silent = [k for k in ke_names if counts.get(k, 0) == 0]
                if silent:
                    A("Key events firing", "WARN", "no hits in 30d: " + ", ".join(silent)[:300])
                elif ke_names:
                    A("Key events firing", "PASS", "all key events seen in 30d")
                if "(not set)" in counts:
                    A("(not set) event names", "WARN", f"{counts['(not set)']} events")
            body2 = {"dateRanges": [{"startDate": "30daysAgo", "endDate": "yesterday"}],
                     "dimensions": [{"name": "sessionDefaultChannelGroup"}], "metrics": [{"name": "sessions"}]}
            ch = safe("Unassigned traffic", lambda: data.properties().runReport(property=pname, body=body2)
                      .execute(num_retries=5))
            if ch and ch.get("rows"):
                m = {r["dimensionValues"][0]["value"]: int(r["metricValues"][0]["value"]) for r in ch["rows"]}
                tot = sum(m.values()) or 1
                share = m.get("Unassigned", 0) / tot * 100
                A("Unassigned traffic", "WARN" if share > 10 else "PASS", f"{share:.1f}% of sessions")
        time.sleep(0.2)


# ---------------------------------------------------------------- GTM
def tparam(tag, key):
    for p in tag.get("parameter", []):
        if p.get("key") == key:
            return p.get("value")
    return None


def audit_gtm(creds, limit):
    gtm = build("tagmanager", "v2", credentials=creds, cache_discovery=False)
    accounts = paged(gtm.accounts().list, "account")
    conts = []
    for a in accounts:
        if not match_acct(a["name"]):
            continue
        for c in paged(gtm.accounts().containers().list, "container", parent=a["path"]):
            conts.append((a["name"], c))
        time.sleep(0.3)
    if limit:
        conts = conts[:limit]
    print(f"GTM: auditing {len(conts)} containers")
    for i, (acct, c) in enumerate(conts, 1):
        cname, cid = c["name"], c["publicId"]
        print(f"  [{i}/{len(conts)}] {acct} / {cname} ({cid})", flush=True)

        def A(check, status, detail=""):
            add("GTM", acct, f"{cname} ({','.join(c.get('usageContext', []))})", cid, check, status, detail)

        try:
            v = gtm.accounts().containers().versions().live(parent=c["path"]).execute(num_retries=5)
        except HttpError as e:
            if e.resp.status == 404:
                A("Published version", "FAIL", "container never published")
            else:
                A("Published version", "ERROR", short_err(e))
            inventory["GTM"].append(dict(account=acct, container=cname, public_id=cid, ga4_ids=""))
            time.sleep(0.4)
            continue
        tags, trigs, vars_ = v.get("tag", []), v.get("trigger", []), v.get("variable", [])
        A("Published version", "PASS", f"live v{v.get('containerVersionId')} '{v.get('name','')}': "
          f"{len(tags)} tags, {len(trigs)} triggers, {len(vars_)} variables")
        if not tags:
            A("Tags present", "WARN", "live version has no tags")
        blob = json.dumps(v)
        ids = sorted(set(GID_ANY.findall(blob)))

        paused = [t["name"] for t in tags if t.get("paused")]
        A("Paused tags", "WARN" if paused else "PASS", f"{len(paused)}: " + ", ".join(paused)[:300])

        used_trig = set()
        for t in tags:
            used_trig.update(t.get("firingTriggerId", []))
            used_trig.update(t.get("blockingTriggerId", []))
        for t in trigs:
            if t.get("type") == "triggerGroup":
                used_trig.update(re.findall(r"\d+", json.dumps(t.get("parameter", []))))
        notrig = [t["name"] for t in tags if not t.get("firingTriggerId") and not t.get("paused")
                  and not t.get("setupTag") and not t.get("teardownTag")]
        A("Tags with no firing trigger", "WARN" if notrig else "PASS", f"{len(notrig)}: " + ", ".join(notrig)[:300])

        unused_t = [t["name"] for t in trigs if t["triggerId"] not in used_trig]
        A("Unused triggers", "WARN" if unused_t else "PASS", f"{len(unused_t)}: " + ", ".join(unused_t)[:300])
        unused_v = [x["name"] for x in vars_ if blob.count("{{" + x["name"] + "}}") == 0]
        A("Unused variables", "WARN" if unused_v else "PASS", f"{len(unused_v)}: " + ", ".join(unused_v)[:300])

        groups = collections.defaultdict(list)
        for t in tags:
            key = (t.get("type"), json.dumps(sorted(t.get("parameter", []), key=lambda p: p.get("key", "")),
                                             sort_keys=True), tuple(sorted(t.get("firingTriggerId", []))))
            groups[key].append(t["name"])
        dups = [" = ".join(n) for n in groups.values() if len(n) > 1]
        A("Duplicate tags", "WARN" if dups else "PASS", f"{len(dups)}: " + "; ".join(dups)[:300])

        ua = [t["name"] for t in tags if t.get("type") in ("ua",) or "UA-" in json.dumps(t.get("parameter", []))]
        A("Universal Analytics remnants", "FAIL" if ua else "PASS", ", ".join(ua)[:300])

        hard = []
        for t in tags:
            if t.get("type") in ("gaawe", "gaawc", "googtag"):
                val = tparam(t, "measurementId") or tparam(t, "tagId") or ""
                if GID.match(val):
                    hard.append(t["name"])
        A("Hardcoded GA4 IDs in tags", "WARN" if hard else "PASS", f"{len(hard)}: " + ", ".join(hard)[:300])

        html = [t["name"] for t in tags if t.get("type") == "html"]
        A("Custom HTML tags", "WARN" if len(html) > 5 else "INFO", f"{len(html)} custom HTML tags")

        default_names = [t["name"] for t in tags if re.match(r"^(New Tag|Untitled|Copy of|test)", t["name"], re.I)]
        A("Default/test tag names", "WARN" if default_names else "PASS", ", ".join(default_names)[:300])

        noconsent = [t for t in tags if t.get("consentSettings", {}).get("consentStatus", "notSet") == "notSet"]
        A("Tag consent settings", "INFO" if noconsent else "PASS",
          f"{len(noconsent)}/{len(tags)} tags have no additional consent settings")

        A("GA4 IDs referenced", "INFO", " ".join(ids))
        inventory["GTM"].append(dict(account=acct, container=cname, public_id=cid, ga4_ids=" ".join(ids)))
        time.sleep(0.4)


# ---------------------------------------------------------------- output
def cross_check():
    known = set()
    for r in inventory["GA4"]:
        known.update(r["measurement_ids"].split())
    if not known:
        return
    for r in inventory["GTM"]:
        for gid in r["ga4_ids"].split():
            if gid not in known:
                add("GTM", r["account"], r["container"], r["public_id"], "GA4 ID not in accessible properties",
                    "WARN", f"{gid} not found among your GA4 web streams")


def write_all(outdir):
    outdir.mkdir(parents=True, exist_ok=True)
    cols = ["scope", "account", "entity", "entity_id", "check", "status", "detail"]
    with open(outdir / "findings.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, cols)
        w.writeheader()
        w.writerows(findings)
    summ = collections.defaultdict(collections.Counter)
    for r in findings:
        summ[(r["scope"], r["account"], r["entity"], r["entity_id"])][r["status"]] += 1
    with open(outdir / "summary.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["scope", "account", "entity", "entity_id", "FAIL", "WARN", "ERROR", "PASS", "INFO"])
        for k, c in sorted(summ.items(), key=lambda kv: (-kv[1]["FAIL"], -kv[1]["WARN"])):
            w.writerow(list(k) + [c["FAIL"], c["WARN"], c["ERROR"], c["PASS"], c["INFO"]])
    print("Wrote", outdir)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["ga4", "gtm", "all"], default="all")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="audit_output")
    ap.add_argument("--accounts", default="", help="comma-separated account-name substrings")
    a = ap.parse_args()
    ACCOUNT_FILTER.extend(s.strip().lower() for s in a.accounts.split(",") if s.strip())
    creds, _ = google.auth.default(scopes=SCOPES)
    if PROJECT:
        creds = creds.with_quota_project(PROJECT)
    outdir = pathlib.Path(a.out) / datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        if a.only in ("ga4", "all"):
            audit_ga4(creds, a.limit)
        if a.only in ("gtm", "all"):
            audit_gtm(creds, a.limit)
        cross_check()
    finally:
        write_all(outdir)


if __name__ == "__main__":
    main()
