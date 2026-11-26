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

    sheet("Summary", summarize(findings), ["scope", "account", "entity", "entity_id", "score", "FAIL", "WARN", "ERROR", "PASS", "INFO"], True)
    sheet("By account", by_account(findings), ["scope", "account", "entities", "FAIL", "WARN", "ERROR"])
    sheet("By check", by_check(findings), ["scope", "check"] + ORDER)
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
<h2>Results by check</h2>{_table(by_check(findings), ['scope', 'check'] + ORDER)}
<h2>Results by account</h2>{_table(by_account(findings), ['scope', 'account', 'entities', 'FAIL', 'WARN', 'ERROR'])}
<h2>Lowest health scores</h2>{_table(summarize(findings)[:25], ['scope', 'account', 'entity', 'entity_id', 'score', 'FAIL', 'WARN', 'ERROR'])}
<h2>Failures</h2>{_table(problems, ['scope', 'account', 'entity', 'check', 'status', 'detail'], 'status') if problems else '<p>None.</p>'}
<h2>All warnings and failures by account</h2>{detail}
<p class="meta">Score = 100 minus 20 per fail, 5 per warn or error. Read-only audit of live GTM versions and the last
{meta.get('days', 30)} days of GA4 data. GA4 internal traffic filters cannot be read through Google's API.</p>
</body></html>""".encode("utf-8")
