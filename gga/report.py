"""Turns audit findings into CSV, Excel and a self-contained HTML report."""
import collections
import csv
import datetime
import html
import io

COLS = ["scope", "account", "entity", "entity_id", "check", "status", "detail"]
ORDER = ["FAIL", "WARN", "ERROR", "PASS", "INFO"]
COLORS = {"FAIL": "#f8d7da", "WARN": "#fff3cd", "ERROR": "#e2d9f3", "PASS": "#d4edda", "INFO": "#e9ecef"}


def summarize(findings):
    """One row per property or container with status counts and a 0-100 health score."""
    by = collections.defaultdict(collections.Counter)
    for r in findings:
        by[(r["scope"], r["account"], r["entity"], r["entity_id"])][r["status"]] += 1
    rows = []
    for (scope, acct, ent, eid), c in by.items():
        score = max(0, 100 - 20 * c["FAIL"] - 5 * c["WARN"] - 5 * c["ERROR"])
        rows.append(dict(scope=scope, account=acct, entity=ent, entity_id=eid, score=score,
                         FAIL=c["FAIL"], WARN=c["WARN"], ERROR=c["ERROR"], PASS=c["PASS"], INFO=c["INFO"]))
    rows.sort(key=lambda r: (r["score"], r["account"], r["entity"]))
    return rows


def by_check(findings):
    by = collections.defaultdict(collections.Counter)
    for r in findings:
        by[(r["scope"], r["check"])][r["status"]] += 1
    rows = [dict(scope=s, check=c, **{k: v[k] for k in ORDER}) for (s, c), v in by.items()]
    rows.sort(key=lambda r: (-(r["FAIL"] * 1000 + r["WARN"]), r["scope"], r["check"]))
    return rows


def by_account(findings):
    ent = collections.defaultdict(set)
    cnt = collections.defaultdict(collections.Counter)
    for r in findings:
        k = (r["scope"], r["account"])
        ent[k].add(r["entity_id"] or r["entity"])
        cnt[k][r["status"]] += 1
    rows = [dict(scope=s, account=a, entities=len(ent[(s, a)]), **{k: cnt[(s, a)][k] for k in ("FAIL", "WARN", "ERROR")})
            for (s, a) in ent]
    rows.sort(key=lambda r: (-(r["FAIL"] * 1000 + r["WARN"]), r["scope"], r["account"]))
    return rows


def rating(score):
    return "Good" if score >= 85 else "Fair" if score >= 70 else "Poor" if score >= 50 else "Critical"


def _first_sentence(text):
    text = (text or "").strip()
    cut = text.find(". ")
    return text[:cut + 1] if 0 < cut < 220 else text[:220]


def executive_summary(findings, top=8):
    """A plain-language overview of a whole audit: overall health, what to fix first, where, and what could not be checked."""
    from . import knowledge
    items = summarize(findings)
    tot = collections.Counter(r["status"] for r in findings)
    if not items:
        return dict(empty=True)
    avg = round(sum(i["score"] for i in items) / len(items))
    scopes = collections.Counter(i["scope"] for i in items)
    accounts = {(i["scope"], i["account"]) for i in items}
    dist = dict(healthy=sum(i["score"] >= 85 for i in items), attention=sum(50 <= i["score"] < 85 for i in items),
                critical=sum(i["score"] < 50 for i in items))
    guides = {g["check"]: g for g in knowledge.for_findings(findings)}
    affected = collections.defaultdict(lambda: collections.defaultdict(set))
    for r in findings:
        if r["status"] in ("FAIL", "WARN", "ERROR"):
            affected[r["check"]][r["status"]].add(r["entity_id"] or r["entity"])
    problems = []
    for chk, st_ in affected.items():
        g = guides.get(chk, {})
        problems.append(dict(check=chk, fails=len(st_["FAIL"]), warns=len(st_["WARN"]), errors=len(st_["ERROR"]),
                             items=len(set().union(*st_.values())), why=_first_sentence(g.get("why", "")), fix=g.get("fix", "")))
    problems.sort(key=lambda p: (-(p["fails"] * 3 + p["warns"] + p["errors"] * 0.5), p["check"]))
    fix_first = [p for p in problems if p["fails"]][:top]
    next_up = [p for p in problems if not p["fails"] and p["warns"]][:top]
    could_not = [p for p in problems if p["errors"]][:top]
    accts = by_account(findings)[:5]
    worst = [i for i in items if i["score"] < 85][:5]
    if dist["critical"]:
        headline = (f"{dist['critical']} of {len(items)} audited items are in critical shape. Start with the failures listed under "
                    "Fix first; they are broken or missing settings, not just best-practice gaps.")
    elif tot["FAIL"]:
        headline = f"No item is critical, but {tot['FAIL']} checks failed across {len(fix_first)} kinds of problem. Fix those first."
    elif tot["WARN"]:
        headline = f"Nothing is broken. {tot['WARN']} warnings are risks or best-practice gaps worth scheduling."
    else:
        headline = "No failures or warnings were found."
    return dict(empty=False, average=avg, rating=rating(avg), headline=headline, items=len(items), accounts=len(accounts),
                scopes=dict(scopes), checks=len(findings), totals={k: tot[k] for k in ORDER}, distribution=dist,
                fix_first=fix_first, next_up=next_up, could_not=could_not, accounts_top=accts, worst_items=worst)


def summary_markdown(s):
    """The executive summary as Markdown (used on screen)."""
    if s.get("empty"):
        return "No findings to summarise."
    t = s["totals"]
    scope_txt = ", ".join(f"{n} {k}" for k, n in s["scopes"].items())
    out = [f"**{s['headline']}**", "",
           f"Overall health **{s['average']}/100 ({s['rating']})** across {s['items']} items ({scope_txt}) in {s['accounts']} accounts. "
           f"{s['checks']} checks ran: {t['FAIL']} fail, {t['WARN']} warn, {t['ERROR']} could not run, {t['PASS']} passed. "
           f"{s['distribution']['healthy']} items are healthy (85+), {s['distribution']['attention']} need attention, "
           f"{s['distribution']['critical']} are critical (under 50)."]

    def block(title, rows, fmt):
        if rows:
            out.extend(["", f"#### {title}"] + [fmt(p) for p in rows])

    block("Fix first (failures)", s["fix_first"], lambda p: f"- **{p['check']}**: {p['fails']} failing"
          + (f", {p['warns']} warning" if p["warns"] else "") + f" ({p['items']} items). {p['why']}")
    block("Schedule next (warnings)", s["next_up"], lambda p: f"- **{p['check']}**: {p['warns']} items. {p['why']}")
    block("Could not be checked", s["could_not"], lambda p: f"- **{p['check']}**: {p['errors']} items, usually a permission or API limit. Run these again.")
    block("Accounts needing most attention", s["accounts_top"],
          lambda a: f"- **{a['account']}** ({a['scope']}): {a['FAIL']} fail, {a['WARN']} warn across {a['entities']} items")
    block("Lowest-scoring items", s["worst_items"],
          lambda i: f"- **{i['entity']}** ({i['scope']}, {i['account']}): {i['score']}/100, {i['FAIL']} fail, {i['WARN']} warn")
    out.extend(["", "*Scope and limits: the audit is read-only, uses the live published GTM version and recent GA4 data, and cannot read "
                "GA4 internal traffic filters. The How to fix tab has the steps for each problem.*"])
    return "\n".join(out)


def to_csv(rows, cols=None):
    buf = io.StringIO()
    w = csv.DictWriter(buf, cols or list(rows[0].keys()) if rows else [], extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    return ("﻿" + buf.getvalue()).encode("utf-8")


def to_xlsx(findings, inventory):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()

    def sheet(title, rows, cols, first=False):
        ws = wb.active if first else wb.create_sheet()
        ws.title = title
        ws.append(cols)
        for c in ws[1]:
            c.font = Font(bold=True)
        for r in rows:
            ws.append([r.get(c, "") for c in cols])
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for i, c in enumerate(cols, 1):
            width = max([len(str(c))] + [len(str(r.get(c, ""))) for r in rows[:300]])
            ws.column_dimensions[get_column_letter(i)].width = min(width + 2, 70)
        if "status" in cols:
            col = cols.index("status") + 1
            for row in ws.iter_rows(min_row=2, min_col=col, max_col=col):
                v = row[0].value
                if v in COLORS:
                    row[0].fill = PatternFill("solid", fgColor=COLORS[v][1:])
        return ws

    es = executive_summary(findings)
    rows = []
    if not es.get("empty"):
        rows = [dict(section="Overview", item=f"Health {es['average']}/100 ({es['rating']})", detail=es["headline"])]
        for sec, key in (("Fix first", "fix_first"), ("Schedule next", "next_up"), ("Could not check", "could_not")):
            rows += [dict(section=sec, item=p["check"], detail=f"{p['fails']} fail, {p['warns']} warn, {p['errors']} error ({p['items']} items). {p['why']}")
                     for p in es[key]]
        rows += [dict(section="Account", item=a["account"], detail=f"{a['FAIL']} fail, {a['WARN']} warn, {a['entities']} items") for a in es["accounts_top"]]
    sheet("Executive summary", rows, ["section", "item", "detail"], True)
    sheet("Items by health", summarize(findings), ["scope", "account", "entity", "entity_id", "score", "FAIL", "WARN", "ERROR", "PASS", "INFO"])
    sheet("By account", by_account(findings), ["scope", "account", "entities", "FAIL", "WARN", "ERROR"])
    sheet("By check", by_check(findings), ["scope", "check"] + ORDER)
    from . import knowledge
    guides = [dict(check=g["check"], fails=g["FAIL"], warns=g["WARN"], errors=g["ERROR"], why=g["why"], fix=g["fix"],
                   source=g["source"][0] if g["source"] else "", link=g["source"][1] if g["source"] else "")
              for g in knowledge.for_findings(findings)]
    sheet("How to fix", guides, ["check", "fails", "warns", "errors", "why", "fix", "source", "link"])
    sheet("Findings", findings, COLS)
    sheet("GA4 IDs", inventory, ["scope", "account", "entity", "entity_id", "ids"])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _table(rows, cols, status_col=None):
    h = "<table><tr>" + "".join(f"<th>{html.escape(c)}</th>" for c in cols) + "</tr>"
    for r in rows:
        h += "<tr>"
        for c in cols:
            v = html.escape(str(r.get(c, "")))
            style = f' style="background:{COLORS[r[c]]}"' if c == status_col and r.get(c) in COLORS else ""
            h += f"<td{style}>{v}</td>"
        h += "</tr>"
    return h + "</table>"


def _summary_html(findings):
    s = executive_summary(findings)
    if s.get("empty"):
        return "<p>No findings to summarise.</p>"
    t = s["totals"]
    h = (f"<p><b>{html.escape(s['headline'])}</b></p><p>Overall health <b>{s['average']}/100 ({s['rating']})</b> across {s['items']} items in "
         f"{s['accounts']} accounts. {t['FAIL']} fail, {t['WARN']} warn, {t['ERROR']} could not run, {t['PASS']} passed. "
         f"{s['distribution']['healthy']} healthy, {s['distribution']['attention']} need attention, {s['distribution']['critical']} critical.</p>")

    def ul(title, rows, fmt):
        return f"<h3>{title}</h3><ul>" + "".join(f"<li>{fmt(r)}</li>" for r in rows) + "</ul>" if rows else ""
    e = html.escape
    h += ul("Fix first (failures)", s["fix_first"], lambda p: f"<b>{e(p['check'])}</b>: {p['fails']} failing ({p['items']} items). {e(p['why'])}")
    h += ul("Schedule next (warnings)", s["next_up"], lambda p: f"<b>{e(p['check'])}</b>: {p['warns']} items. {e(p['why'])}")
    h += ul("Could not be checked", s["could_not"], lambda p: f"<b>{e(p['check'])}</b>: {p['errors']} items")
    h += ul("Accounts needing most attention", s["accounts_top"], lambda a: f"<b>{e(a['account'])}</b> ({e(a['scope'])}): {a['FAIL']} fail, {a['WARN']} warn")
    h += ul("Lowest-scoring items", s["worst_items"], lambda i: f"<b>{e(i['entity'])}</b> ({e(i['account'])}): {i['score']}/100")
    return h


def to_html(findings, meta):
    """Self-contained report. meta: dict(title, user, scope_text)."""
    total = collections.Counter(r["status"] for r in findings)
    ents = {(r["scope"], r["entity_id"] or r["entity"]) for r in findings}
    kpi = "".join(f'<div class="kpi" style="background:{COLORS[k]}"><b>{total[k]}</b><span>{k}</span></div>'
                  for k in ("FAIL", "WARN", "ERROR", "PASS"))
    problems = [r for r in findings if r["status"] in ("FAIL", "ERROR")]
    accounts = collections.defaultdict(list)
    for r in findings:
        if r["status"] in ("FAIL", "WARN", "ERROR"):
            accounts[(r["scope"], r["account"])].append(r)
    detail = ""
    for (scope, acct), rows in sorted(accounts.items(), key=lambda kv: -len(kv[1])):
        rows.sort(key=lambda r: (ORDER.index(r["status"]), r["entity"], r["check"]))
        detail += (f"<details><summary>{html.escape(scope)} · {html.escape(acct)} "
                   f"<small>({len(rows)} issues)</small></summary>"
                   + _table(rows, ["entity", "entity_id", "check", "status", "detail"], "status") + "</details>")
    from . import knowledge
    fixes = ""
    for g in knowledge.for_findings(findings):
        counts = ", ".join(f"{g[k]} {k.lower()}" for k in ("FAIL", "WARN", "ERROR") if g[k])
        src = (f' <a href="{html.escape(g["source"][1])}">{html.escape(g["source"][0])}</a>' if g["source"] else "")
        fixes += (f"<details><summary>{html.escape(g['check'])} <small>({counts})</small></summary>"
                  f"<p><b>Why it matters.</b> {html.escape(g['why'])}</p><p><b>How to fix.</b> {html.escape(g['fix'])}</p>"
                  + (f"<p><b>Source:</b>{src}</p>" if src else "") + "</details>")
    fixes = fixes or "<p>No failures or warnings to explain.</p>"
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(meta.get('title', 'Audit'))}</title>
<style>body{{font:14px system-ui,Segoe UI,Arial;margin:32px auto;max-width:1100px;color:#222;padding:0 16px}}
h1{{margin:0 0 4px}}h2{{margin-top:32px;border-bottom:1px solid #ddd;padding-bottom:4px}}
.kpis{{display:flex;gap:12px;margin:16px 0}}.kpi{{padding:12px 20px;border-radius:8px;min-width:90px}}
.kpi b{{display:block;font-size:26px}}table{{border-collapse:collapse;width:100%;margin:8px 0;font-size:13px}}
th,td{{border:1px solid #ddd;padding:4px 8px;text-align:left;vertical-align:top}}th{{background:#f4f4f4}}
details{{margin:6px 0}}summary{{cursor:pointer;font-weight:600;padding:4px 0}}small{{color:#666;font-weight:400}}
.meta{{color:#666}}</style></head><body>
<h1>{html.escape(meta.get('title', 'GA4 & GTM audit'))}</h1>
<div class="meta">{datetime.date.today():%d %b %Y} · run by {html.escape(meta.get('user', ''))} · {html.escape(meta.get('scope_text', ''))}</div>
<div class="kpis">{kpi}</div><p>{len(ents)} properties and containers audited, {len(findings)} checks run.</p>
<h2>Executive summary</h2>{_summary_html(findings)}
<h2>Results by check</h2>{_table(by_check(findings), ['scope', 'check'] + ORDER)}
<h2>Results by account</h2>{_table(by_account(findings), ['scope', 'account', 'entities', 'FAIL', 'WARN', 'ERROR'])}
<h2>Lowest health scores</h2>{_table(summarize(findings)[:25], ['scope', 'account', 'entity', 'entity_id', 'score', 'FAIL', 'WARN', 'ERROR'])}
<h2>Failures</h2>{_table(problems, ['scope', 'account', 'entity', 'check', 'status', 'detail'], 'status') if problems else '<p>None.</p>'}
<h2>How to fix</h2>{fixes}
<h2>All warnings and failures by account</h2>{detail}
<p class="meta">Score = 100 minus 20 per fail, 5 per warn or error. Read-only audit of live GTM versions and the last
{meta.get('days', 30)} days of GA4 data. GA4 internal traffic filters cannot be read through Google's API.</p>
</body></html>""".encode("utf-8")
