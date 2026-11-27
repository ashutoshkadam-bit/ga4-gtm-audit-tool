import io

import openpyxl

from gga import report

F = [
    dict(scope="GA4", account="Acme", entity="Acme web", entity_id="1", check="Data retention", status="WARN", detail="event retention=TWO_MONTHS"),
    dict(scope="GA4", account="Acme", entity="Acme web", entity_id="1", check="Data streams", status="PASS", detail="WEB:Acme"),
    dict(scope="GTM", account="Acme", entity="Acme site (web)", entity_id="GTM-1", check="Universal Analytics remnants", status="FAIL", detail="UA tag"),
    dict(scope="GTM", account="Globex", entity="<script>alert(1)</script>", entity_id="GTM-2", check="Paused tags", status="WARN", detail="3: a, b, c"),
    dict(scope="GA4", account="Globex", entity="Globex app", entity_id="2", check="Key events", status="INFO", detail="1"),
]
META = dict(title="Test audit", user="tester", scope_text="Acme, Globex", days=30)


def test_summary_scores_worst_first():
    rows = report.summarize(F)
    assert rows[0]["entity"] == "Acme site (web)" and rows[0]["score"] == 80
    assert all(0 <= r["score"] <= 100 for r in rows)


def test_by_check_and_by_account_count_statuses():
    by_check = {r["check"]: r for r in report.by_check(F)}
    assert by_check["Universal Analytics remnants"]["FAIL"] == 1
    by_acct = {(r["scope"], r["account"]): r for r in report.by_account(F)}
    assert by_acct[("GTM", "Acme")]["FAIL"] == 1 and by_acct[("GA4", "Acme")]["WARN"] == 1


def test_csv_has_a_byte_order_mark_and_all_rows():
    data = report.to_csv(F, report.COLS)
    assert data.startswith(b"\xef\xbb\xbf") and data.decode("utf-8-sig").count("\n") >= len(F) + 1


def test_excel_has_the_expected_sheets_and_row_counts():
    wb = openpyxl.load_workbook(io.BytesIO(report.to_xlsx(F, [dict(scope="GA4", account="Acme", entity="x", entity_id="1", ids="G-X")])))
    assert wb.sheetnames == ["Executive summary", "Items by health", "By account", "By check", "How to fix", "Findings", "GA4 IDs"]
    assert wb["Findings"].max_row == len(F) + 1
    assert wb["How to fix"].max_row >= 2  # fail and warn checks have guides


def test_html_report_escapes_page_content_and_stays_self_contained():
    html = report.to_html(F, META).decode()
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    assert "How to fix" in html and "Test audit" in html
    assert "src=" not in html.replace("<script", "")  # no external resources


def test_reports_handle_an_empty_audit():
    assert report.to_csv([], report.COLS)
    assert report.to_html([], META)
    openpyxl.load_workbook(io.BytesIO(report.to_xlsx([], [])))


def test_executive_summary_orders_problems_and_explains_them():
    s = report.executive_summary(F)
    assert not s["empty"] and 0 <= s["average"] <= 100 and s["rating"] in ("Good", "Fair", "Poor", "Critical")
    assert s["fix_first"][0]["check"] == "Universal Analytics remnants"
    assert {p["check"] for p in s["next_up"]} == {"Data retention", "Paused tags"}
    md = report.summary_markdown(s)
    assert "Fix first" in md and "Overall health" in md


def test_executive_summary_handles_empty_and_clean_audits():
    assert report.executive_summary([])["empty"]
    assert "No findings" in report.summary_markdown(report.executive_summary([]))
    clean = [dict(F[1])]
    assert "No failures or warnings" in report.executive_summary(clean)["headline"]


def test_html_report_includes_the_summary_and_escapes_it():
    html_ = report.to_html(F, META).decode()
    assert "Executive summary" in html_ and "Fix first" in html_ and "<script>alert(1)</script>" not in html_
