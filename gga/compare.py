"""Compares two audits: what got worse, what was fixed, what is new, and how each item's health score moved.

Only items present in both audits are compared check by check, so choosing different accounts in two runs does not create false
"fixed" or "new problem" noise. Items present in only one run are listed separately.
"""
import csv
import io

from . import report

SEV = {"PASS": 0, "INFO": 0, "WARN": 1, "ERROR": 1, "FAIL": 2}
REQUIRED = {"scope", "account", "entity", "check", "status"}


def entity_key(f):
    """Identity of one audited item. Page audits and site checks are per address, so the address is part of it."""
    return (f["scope"], f["account"], f.get("entity_id") or f["entity"], f["entity"] if f["scope"] in ("PAGE", "SITE") else "")


def check_key(f):
    return entity_key(f) + (f["check"],)


def _collapse(findings):
    """Several rows can share a key (for example one per data stream). Keep the worst status and join the details."""
    out = {}
    for f in findings:
        k = check_key(f)
        cur = out.get(k)
        if cur is None:
            out[k] = dict(f, _d=[f.get("detail", "")])
        else:
            if SEV.get(f["status"], 0) > SEV.get(cur["status"], 0):
                cur["status"] = f["status"]
            if f.get("detail") and f["detail"] not in cur["_d"]:
                cur["_d"].append(f["detail"])
    for v in out.values():
        v["detail"] = " | ".join(d for d in v.pop("_d") if d)[:500]
    return out


def _row(nf, of):
    return dict(scope=nf["scope"], account=nf["account"], entity=nf["entity"], check=nf["check"],
                was=of["status"] if of else "-", now=nf["status"], was_detail=of["detail"] if of else "", now_detail=nf["detail"])


def compare(old, new):
    """old and new are lists of finding dicts. Returns a dict of buckets, counts and per-item health changes."""
    o, n = _collapse(old), _collapse(new)
    oe, ne = {entity_key(f) for f in o.values()}, {entity_key(f) for f in n.values()}
    both = oe & ne
    b = dict(new_problems=[], worsened=[], resolved=[], improved=[], persisting=[], changed=[])
    skipped = 0
    for k, nf in n.items():
        if entity_key(nf) not in both:
            continue
        of = o.get(k)
        sn = SEV.get(nf["status"], 0)
        if of is None:
            if sn > 0:
                b["new_problems"].append(_row(nf, None))
            continue
        so = SEV.get(of["status"], 0)
        if sn > so:
            b["new_problems" if so == 0 else "worsened"].append(_row(nf, of))
        elif sn < so:
            b["resolved" if sn == 0 else "improved"].append(_row(nf, of))
        elif sn > 0:
            b["persisting"].append(_row(nf, of))
            if of["detail"] != nf["detail"]:
                b["changed"].append(_row(nf, of))
    for k, of in o.items():
        if entity_key(of) in both and k not in n and SEV.get(of["status"], 0) > 0:
            skipped += 1  # a check that did not run this time (different options): not counted as fixed

    def label(f):
        return dict(scope=f["scope"], account=f["account"], entity=f["entity"])

    added = sorted({tuple(label(f).values()) for f in n.values() if entity_key(f) not in oe})
    removed = sorted({tuple(label(f).values()) for f in o.values() if entity_key(f) not in ne})

    so_, sn_ = {(r["scope"], r["account"], r["entity"]): r["score"] for r in report.summarize(old)}, {(r["scope"], r["account"], r["entity"]): r["score"] for r in report.summarize(new)}
    health = [dict(scope=k[0], account=k[1], entity=k[2], was=so_[k], now=sn_[k], change=sn_[k] - so_[k]) for k in so_ if k in sn_]
    health.sort(key=lambda r: (r["change"], r["entity"]))
    return dict(
        **b, added_items=added, removed_items=removed, health=health, not_rechecked=skipped, compared_items=len(both),
        counts={k: len(v) for k, v in b.items()},
        score_old=_avg(list(so_.values())), score_new=_avg(list(sn_.values())))


def _avg(xs):
    return round(sum(xs) / len(xs), 1) if xs else None


def headline(c):
    k = c["counts"]
    parts = []
    if k["new_problems"] or k["worsened"]:
        parts.append(f"{k['new_problems']} new problem{'s' if k['new_problems'] != 1 else ''}" + (f" and {k['worsened']} worse" if k["worsened"] else ""))
    if k["resolved"] or k["improved"]:
        parts.append(f"{k['resolved']} fixed" + (f" and {k['improved']} improved" if k["improved"] else ""))
    return ", ".join(parts) or "no change in problems"


def baseline_from_csv(data):
    """Reads a findings.csv downloaded from this tool. Raises ValueError with a plain message if it is not one."""
    text = data.decode("utf-8-sig", errors="replace") if isinstance(data, (bytes, bytearray)) else str(data)
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows or not REQUIRED <= set(rows[0].keys()):
        raise ValueError("This is not a findings file from this tool. Download 'All findings (.csv)' from an audit and upload that.")
    out = []
    for r in rows:
        if r["status"] not in SEV:
            continue
        out.append(dict(scope=r["scope"], account=r["account"], entity=r["entity"], entity_id=r.get("entity_id", ""), check=r["check"],
                        status=r["status"], detail=r.get("detail", "")))
    if not out:
        raise ValueError("The file has no usable findings.")
    return out


def to_csv(c):
    """The comparison as one CSV: every changed row with its bucket."""
    rows = []
    for bucket in ("new_problems", "worsened", "resolved", "improved", "persisting"):
        for r in c[bucket]:
            rows.append(dict(change=bucket.replace("_", " "), **r))
    buf = io.StringIO()
    w = csv.DictWriter(buf, ["change", "scope", "account", "entity", "check", "was", "now", "was_detail", "now_detail"])
    w.writeheader()
    w.writerows(rows)
    return ("﻿" + buf.getvalue()).encode("utf-8")
