"""Command-line audit. Example:
    python cli.py --accounts "acme,globex" --out results
    python cli.py --list                      # show what you can access
"""
import argparse
import datetime
import pathlib
import collections

from gga import auth, core, report


def main():
    ap = argparse.ArgumentParser(description="Read-only GA4 + GTM audit")
    ap.add_argument("--accounts", default="", help="comma-separated parts of account names (default: all)")
    ap.add_argument("--only", choices=["ga4", "gtm", "all"], default="all")
    ap.add_argument("--limit", type=int, default=0, help="max items per account (quick test)")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--no-data", action="store_true", help="skip GA4 data checks (faster)")
    ap.add_argument("--out", default="audit_results")
    ap.add_argument("--list", action="store_true", help="list accessible accounts and exit")
    ap.add_argument("--sign-in", action="store_true", help="force a fresh Google sign-in")
    a = ap.parse_args()

    creds = None if a.sign_in else auth.load_credentials()
    if not creds:
        print("Opening your browser to sign in with Google...")
        creds = auth.sign_in()
    aud = core.Auditor(creds, dict(days=a.days, ga4_data=not a.no_data))
    words = [w.strip().lower() for w in a.accounts.split(",") if w.strip()]
    keep = lambda name: not words or any(w in name.lower() for w in words)  # noqa: E731

    ga4 = aud.list_ga4()
    gtm = aud.list_gtm()
    if a.list:
        for label, rows in (("GA4", ga4), ("GTM", gtm)):
            c = collections.Counter(r["account"] for r in rows)
            print(f"\n{label}: {len(rows)} items in {len(c)} accounts")
            for k, v in sorted(c.items()):
                print(f"  {k}: {v}")
        return

    def cap(rows):
        if not a.limit:
            return rows
        seen, out = collections.Counter(), []
        for r in rows:
            if seen[r["account"]] < a.limit:
                out.append(r)
                seen[r["account"]] += 1
        return out

    ga4_pick = cap([r for r in ga4 if keep(r["account"])]) if a.only in ("ga4", "all") else []
    gtm_pick = cap([r for r in gtm if keep(r["account"])]) if a.only in ("gtm", "all") else []
    print(f"Auditing {len(ga4_pick)} GA4 properties and {len(gtm_pick)} GTM containers")
    known = core.all_ga4_measurement_ids(aud, ga4) if gtm_pick else None
    findings, inventory = core.run_audit(aud, ga4_pick, gtm_pick, known,
                                         progress=lambda d, n, label: print(f"[{d}/{n}] {label}", flush=True))
    out = pathlib.Path(a.out) / datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    meta = dict(title="GA4 & GTM audit", user=auth.user_email(creds), scope_text=a.accounts or "all accounts", days=a.days)
    (out / "findings.csv").write_bytes(report.to_csv(findings, report.COLS))
    (out / "audit.xlsx").write_bytes(report.to_xlsx(findings, inventory))
    (out / "report.html").write_bytes(report.to_html(findings, meta))
    print("Saved to", out.resolve())


if __name__ == "__main__":
    main()
