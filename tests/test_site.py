import pytest

from gga import site


@pytest.mark.parametrize("url", [
    "http://localhost:8501", "http://127.0.0.1/", "http://[::1]/", "http://0.0.0.0/", "http://10.0.0.5/", "http://192.168.1.10/admin",
    "http://169.254.169.254/latest/meta-data/", "http://172.16.0.1/",
])
def test_private_and_internal_addresses_are_refused(url):
    with pytest.raises(site.BlockedAddress):
        site.check_public(url)


@pytest.mark.parametrize("url", ["ftp://example.com/file", "file:///etc/passwd", "javascript:alert(1)", "gopher://example.com"])
def test_non_http_schemes_are_refused(url):
    status, _, text, err = site.safe_fetch(url)
    assert status == 0 and text == "" and err


def test_safe_fetch_reports_a_blocked_address_in_plain_words():
    _, _, _, err = site.safe_fetch("http://127.0.0.1:9/")
    assert err.startswith("blocked:") and "private or internal" in err


def test_normalize_adds_https_and_trims():
    assert site.normalize("  example.com/page ") == "https://example.com/page"
    assert site.normalize("http://example.com") == "http://example.com"
    assert site.normalize("   ") == ""


def test_extract_ids_finds_each_kind():
    text = "GTM-ABC123 and G-ABCDE12345, UA-1234567-1, AW-123456789, fbq('init','1234567890123')"
    ids = site.extract_ids(text)
    assert ids["gtm"] == ["GTM-ABC123"] and ids["ga4"] == ["G-ABCDE12345"] and ids["ua"] == ["UA-1234567-1"]
    assert ids["aw"] == ["AW-123456789"] and ids["fbq"] == ["1234567890123"]


def test_extract_ids_ignores_lookalikes():
    ids = site.extract_ids("Gabcde12345 xG-ABCDE12345x GTM_ABC123 UA-12-1")
    assert ids["ga4"] == [] and ids["gtm"] == [] and ids["ua"] == []


def _fake_fetch(pages):
    def fetch(url, session=None):
        for key, body in pages.items():
            if key in url:
                return 200, url, body, ""
        return 404, url, "", ""
    return fetch


def test_scan_url_flags_unknown_container_double_loaded_ga4_and_ua(monkeypatch):
    html = ('<script async src="https://www.googletagmanager.com/gtag/js?id=G-DUP1234567"></script>'
            "<script>(function(){})('GTM-NEW9999'); gtag('config','G-DUP1234567'); ga('create','UA-1111111-1')</script>")
    gtm_js = "gtag('config','G-DUP1234567'); var a='UA-2222222-1'"
    monkeypatch.setattr(site, "safe_fetch", _fake_fetch({"gtm.js?id=GTM-NEW9999": gtm_js, "shop.example.com": html}))
    out = {f["check"]: f for f in site.scan_url("https://shop.example.com/", known_containers={"GTM-MINE000"}, known_ga4={"G-OTHER00000"})}
    assert out["Page loads"]["status"] == "PASS"
    assert out["GTM container in your accounts"]["status"] == "WARN"
    assert out["GA4 loaded twice"]["status"] == "WARN"
    assert out["GA4 ID in your properties"]["status"] == "WARN"
    assert out["Universal Analytics"]["status"] == "FAIL"


def test_scan_url_on_a_failing_page_returns_one_fail(monkeypatch):
    monkeypatch.setattr(site, "safe_fetch", lambda url, session=None: (503, url, "", ""))
    out = site.scan_url("https://down.example.com/")
    assert [f["check"] for f in out] == ["Page loads"] and out[0]["status"] == "FAIL"


def test_run_site_check_dedupes_and_caps(monkeypatch):
    seen = []
    monkeypatch.setattr(site, "scan_url", lambda u, *a, **k: seen.append(u) or [])
    monkeypatch.setattr(site.time, "sleep", lambda s: None)
    site.run_site_check(["example.com", "https://example.com/", "example.org"] + [f"site{i}.com" for i in range(100)])
    assert len(seen) == site.MAX_URLS and len(set(seen)) == len(seen)
