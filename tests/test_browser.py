"""Tests that drive a real headless Chromium against a small local test page. They skip when no browser can start."""
import pytest

from conftest import ROOT
from gga import pageanalysis, pagecapture, site

pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def cap(browser_ready, local_site):
    return pagecapture.capture(local_site + "/", wait_s=2, scroll=False, allow_private=True)


def test_capture_records_the_page_and_its_requests(cap):
    assert cap["schema"] == "gga-capture-1" and cap["status"] == 200 and not cap["nav_error"]
    urls = [r["url"] for r in cap["requests"]]
    assert any(u.endswith("/dyn.js") for u in urls) and any("/g/collect" in u for u in urls)
    doc = cap["requests"][0]
    assert doc["type"] == "Document" and doc["protocol"] and doc["ip"] == "127.0.0.1"


def test_capture_records_console_cookies_datalayer_and_html(cap):
    assert any(c["type"] == "error" and "boom from the test page" in c["text"] for c in cap["console"])
    assert any(c["name"] == "_ga" for c in cap["cookies"])
    assert any(isinstance(e["v"], dict) and e["v"].get("event") == "page_ready" for e in cap["datalayer"])
    assert "Hello" in cap["html"] and cap["title"] == "Test page"
    assert cap["perf"].get("fcp") is not None


def test_analysis_of_a_real_capture_finds_the_ga4_hit_and_the_loader(cap):
    an = pageanalysis.analyze(cap)
    assert [(e["tid"], e["en"]) for e in an["hits"]["ga4"]] == [("G-TEST123456", "page_view")]
    dyn = next(r for r in cap["requests"] if r["url"].endswith("/dyn.js"))
    assert pageanalysis.loader_of(dyn, an["page_reg"], cap["final_url"]).startswith("Inline script")
    f = {x["check"]: x for x in pageanalysis.to_findings(cap, an)}
    assert f["GA4 hits observed"]["status"] == "PASS"
    assert f["Console errors"]["status"] == "WARN"
    assert f["Cookies before consent"]["status"] == "WARN"


def test_private_addresses_are_refused_unless_explicitly_allowed(browser_ready):
    with pytest.raises(site.BlockedAddress):
        pagecapture.capture("http://127.0.0.1:9/")


def test_an_unreachable_page_gives_a_plain_failure_not_a_crash(browser_ready):
    c = pagecapture.capture("http://127.0.0.1:9/", wait_s=2, allow_private=True)
    assert c["nav_error"]
    f = {x["check"]: x for x in pageanalysis.to_findings(c, pageanalysis.analyze(c))}
    assert f["Page loads"]["status"] == "FAIL"


def test_extension_page_script_sees_the_same_page(browser_ready, local_site):
    """injected.js runs in the page the way the Chrome extension runs it, and reports console, dataLayer and who created each script."""
    from playwright.sync_api import sync_playwright
    ext = ROOT / "extension"
    with sync_playwright() as p:
        b = pagecapture.launch_browser(p)
        page = b.new_context().new_page()
        page.add_init_script(path=str(ext / "globals.js"))
        page.add_init_script(path=str(ext / "injected.js"))
        page.goto(local_site + "/", wait_until="load")
        page.wait_for_timeout(500)
        snap = page.evaluate("window.__ggaSnapshot()")
        b.close()
    assert any("boom from the test page" in c["text"] for c in snap["console"])
    assert any(isinstance(e["v"], dict) and e["v"].get("event") == "page_ready" for e in snap["dataLayer"])
    assert snap["creators"][local_site + "/dyn.js"] == "inline"
    assert "dataLayer" in snap["globals"] and "Hello" in snap["html"]
