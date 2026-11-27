from conftest import DOC, GA4, GTM, doc_request, make_capture, req
from gga import pageanalysis


def findings(cap):
    an = pageanalysis.analyze(cap)
    return {f["check"]: f for f in pageanalysis.to_findings(cap, an)}, an


def gtm_loaded_page(extra=()):
    return make_capture([
        doc_request(),
        req(GTM, initiator_type="script", initiator_url=DOC, start=100),
        req(GA4.format(en="page_view"), type="Ping", start=500, method="POST"),
        *extra,
    ])


def test_healthy_gtm_and_ga4_page_passes_the_core_checks():
    f, an = findings(gtm_loaded_page())
    assert f["Page loads"]["status"] == "PASS"
    assert f["GA4 hits observed"]["status"] == "PASS" and "page_view" in f["GA4 hits observed"]["detail"]
    assert f["GTM container loads"]["status"] == "PASS" and "GTM-TEST123" in f["GTM container loads"]["detail"]
    assert f["Universal Analytics"]["status"] == "PASS"
    assert {"Google Tag Manager", "Google Analytics 4"} <= {t["name"] for t in an["technologies"]}


def test_failed_page_load_stops_early_with_fail():
    cap = make_capture([doc_request(status=403)], status=403)
    f, _ = findings(cap)
    assert f["Page loads"]["status"] == "FAIL" and "403" in f["Page loads"]["detail"]
    assert len(f) == 1


def test_navigation_error_is_a_fail_not_a_crash():
    f, _ = findings(make_capture([], nav_error="the page did not finish loading in time"))
    assert f["Page loads"]["status"] == "FAIL"


def test_universal_analytics_is_a_fail():
    cap = make_capture([doc_request(), req("https://www.google-analytics.com/collect?v=1&t=pageview&tid=UA-1234567-1", type="Image")])
    f, _ = findings(cap)
    assert f["Universal Analytics"]["status"] == "FAIL" and "UA-1234567-1" in f["Universal Analytics"]["detail"]


def test_duplicate_ga4_page_view_is_flagged():
    cap = gtm_loaded_page([req(GA4.format(en="page_view"), type="Ping", start=900, method="POST")])
    f, _ = findings(cap)
    assert f["GA4 duplicate hits"]["status"] == "WARN"


def test_ga4_events_in_a_batched_post_body_are_decoded():
    body = "en=page_view&dl=x\nen=scroll&epn.percent_scrolled=90"
    cap = make_capture([doc_request(), req("https://www.google-analytics.com/g/collect?v=2&tid=G-BATCH12345", type="Ping", method="POST", post=body)])
    an = pageanalysis.analyze(cap)
    assert [e["en"] for e in an["hits"]["ga4"]] == ["page_view", "scroll"]


def test_tag_loaded_by_gtm_versus_hard_coded_in_the_page():
    cap = gtm_loaded_page([
        req("https://cdn.taboola.com/libtrc/unip/1/tfa.js", initiator_type="script", initiator_url=GTM, start=700),
        req("https://connect.facebook.net/en_US/fbevents.js", initiator_type="parser", start=300),
    ])
    f, an = findings(cap)
    by = {t["name"]: t["loaded_by"] for t in an["tags"]}
    assert by["Taboola"] == "Google Tag Manager"
    assert by["Meta (Facebook) Pixel"].startswith("Page HTML")
    assert f["Tags outside the tag manager"]["status"] == "WARN" and "Meta" in f["Tags outside the tag manager"]["detail"]


def test_tracking_before_consent_without_a_consent_tool():
    cap = gtm_loaded_page([req("https://connect.facebook.net/en_US/fbevents.js", initiator_type="parser", start=300)])
    f, _ = findings(cap)
    assert f["Tracking before consent"]["status"] == "WARN"
    assert f["Consent management"]["status"] == "WARN"


def test_consent_tool_present_but_tracking_still_loads_early():
    cap = gtm_loaded_page([req("https://cdn.cookielaw.org/scripttemplates/otSDKStub.js", start=50),
                           req("https://connect.facebook.net/en_US/fbevents.js", initiator_type="parser", start=300)])
    f, _ = findings(cap)
    assert f["Consent management"]["status"] == "PASS"
    assert "a consent tool is present" in f["Tracking before consent"]["detail"]


def test_ga4_with_all_consent_denied_is_not_counted_as_tracking():
    denied = GA4.format(en="page_view") + "&gcs=G100"
    cap = make_capture([doc_request(), req(denied, type="Ping", start=400, method="POST")])
    f, _ = findings(cap)
    assert f["Tracking before consent"]["status"] == "PASS"


def test_tracking_cookies_before_consent_are_listed():
    cap = gtm_loaded_page()
    cap["cookies"] = [dict(name="_ga", domain=".example.com", path="/", expires=-1, secure=False, httpOnly=False, sameSite="")]
    f, _ = findings(cap)
    assert f["Cookies before consent"]["status"] == "WARN" and "_ga" in f["Cookies before consent"]["detail"]
    assert f["Cookie security"]["status"] == "WARN"


def test_adobe_analytics_hit_reports_its_report_suite():
    cap = make_capture([doc_request(), req("https://smetrics.shop.example.com/b/ss/myrsid/1/JS-2.26.0/s123?pageName=home&events=event1", type="Image")])
    f, an = findings(cap)
    assert an["hits"]["adobe_aa"][0]["rsid"] == "myrsid"
    assert "myrsid" in f["Adobe Analytics hits"]["detail"]


def test_multiple_gtm_containers_are_warned():
    other = "https://www.googletagmanager.com/gtm.js?id=GTM-OTHER99"
    f, _ = findings(gtm_loaded_page([req(other, initiator_type="script", initiator_url=DOC, start=150)]))
    assert f["Multiple GTM containers"]["status"] == "WARN"


def test_gtm_in_html_but_never_loaded_is_warned():
    cap = make_capture([doc_request()], html="<script>GTM-ABCD123</script>")
    f, _ = findings(cap)
    assert f["GTM container loads"]["status"] == "WARN"


def test_redirect_chain_follows_only_the_pages_own_redirects():
    r1 = doc_request(status=301, headers={"location": "https://shop.example.com/home"}, start=0)
    r2 = req("https://shop.example.com/home", type="Document", status=302, headers={"location": "https://shop.example.com/en"}, start=60)
    r3 = req("https://shop.example.com/en", type="Document", start=120)
    ad = req("https://sync.adtech.net/a", type="Document", status=302, headers={"location": "https://sync.other.net/b"}, start=200)
    f, _ = findings(make_capture([r1, r2, r3, ad]))
    assert "2 redirect(s)" in f["Redirect chain"]["detail"]


def test_plain_http_and_mixed_content():
    cap = make_capture([doc_request(), req("http://cdn.insecure.net/x.js")], final_url="https://shop.example.com/")
    f, _ = findings(cap)
    assert f["Mixed content"]["status"] == "WARN"
    cap2 = make_capture([doc_request()], final_url="http://shop.example.com/")
    assert findings(cap2)[0]["HTTPS"]["status"] == "WARN"


def test_console_errors_and_failed_requests():
    cap = make_capture([doc_request(), req("https://x.example.net/a.js", status=None, error="net::ERR_CONNECTION_REFUSED"),
                        req("https://shop.example.com/missing.png", type="Image", status=404)],
                       console=[dict(type="error", text="Uncaught TypeError", url="", line=1, phase="load")])
    f, _ = findings(cap)
    assert f["Console errors"]["status"] == "WARN"
    assert f["Failed requests"]["status"] == "WARN"
    assert f["HTTP errors on resources"]["status"] == "WARN"


def test_slow_and_unstable_page_is_flagged():
    cap = make_capture([doc_request()], perf={"ttfb": 2500, "fcp": 4000, "lcp": 9000, "cls": 0.4})
    f, _ = findings(cap)
    assert f["Loading speed"]["status"] == "WARN" and f["Layout stability"]["status"] == "WARN"


def test_security_headers_missing_and_present():
    f, _ = findings(make_capture([doc_request()]))
    assert f["Security headers"]["status"] == "WARN"
    full = {"strict-transport-security": "max-age=1", "content-security-policy": "default-src 'self'; frame-ancestors 'none'",
            "x-content-type-options": "nosniff", "referrer-policy": "no-referrer", "permissions-policy": "geolocation=()"}
    assert findings(make_capture([doc_request()], doc_headers=full))[0]["Security headers"]["status"] == "PASS"


def test_loader_of_classifies_initiators():
    assert pageanalysis.loader_of(dict(initiator_url=GTM), "example.com") == "Google Tag Manager"
    assert pageanalysis.loader_of(dict(initiator_type="parser"), "example.com").startswith("Page HTML")
    assert pageanalysis.loader_of(dict(initiator_url="https://cdn.other.net/a.js", initiator_type="script"), "example.com") == "Script from cdn.other.net"
    assert pageanalysis.loader_of(dict(initiator_url="https://shop.example.com", initiator_type=""), "example.com").startswith("Unknown")


def test_every_finding_has_the_required_fields_and_a_guide():
    from gga import knowledge
    f, _ = findings(gtm_loaded_page())
    for x in f.values():
        assert {"scope", "account", "entity", "check", "status", "detail"} <= set(x)
        assert x["status"] in {"PASS", "WARN", "FAIL", "INFO", "ERROR"}
        assert knowledge.guide(x["check"]), x["check"]
