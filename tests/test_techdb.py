from gga import techdb


def names(found):
    return {t["name"] for t in found}


def test_tag_manager_and_google_analytics_from_requests():
    urls = ["https://www.googletagmanager.com/gtm.js?id=GTM-ABC123", "https://www.google-analytics.com/g/collect?v=2&tid=G-AAAA111111&en=page_view"]
    found = names(techdb.detect(urls))
    assert {"Google Tag Manager", "Google Analytics 4"} <= found


def test_adobe_stack_detected_including_first_party_tracking_server():
    urls = ["https://assets.adobedtm.com/launch-abc.min.js", "https://smetrics.example.com/b/ss/prodsuite/1/JS-2.26.0/s123",
            "https://dpm.demdex.net/id?d_visid_ver=5.5.0"]
    found = names(techdb.detect(urls, js_present=["_satellite", "s_gi"]))
    assert {"Adobe Launch (Tags)", "Adobe Analytics", "Adobe Experience Cloud ID / Audience Manager"} <= found


def test_adobe_web_sdk_on_a_first_party_endpoint():
    assert "Adobe Experience Platform Web SDK" in names(techdb.detect(["https://www.example.com/ee/v1/interact?configId=abc"]))


def test_ads_pixels_and_consent_tools():
    urls = ["https://connect.facebook.net/en_US/fbevents.js", "https://cdn.cookielaw.org/scripttemplates/otSDKStub.js",
            "https://analytics.tiktok.com/i18n/pixel/events.js"]
    found = names(techdb.detect(urls, cookie_names=["OptanonConsent"]))
    assert {"Meta (Facebook) Pixel", "OneTrust", "TikTok Pixel"} <= found


def test_cdn_from_headers_not_from_nothing():
    found = techdb.detect([], header_sets=[{"cf-ray": "abc-DEL", "server": "cloudflare"}])
    assert "Cloudflare" in names(found)
    assert names(techdb.detect([], header_sets=[{"server": "nginx"}])) == {"nginx"}


def test_cms_from_html_and_framework_from_globals():
    found = names(techdb.detect([], html='<link href="/wp-content/themes/x/style.css">', js_present=["jQuery"]))
    assert {"WordPress", "jQuery"} <= found


def test_nothing_detected_on_a_plain_page():
    assert techdb.detect(["https://example.com/", "https://example.com/style.css"], html="<h1>Hi</h1>") == []


def test_every_signature_has_a_known_category_and_a_way_to_detect_it():
    for s in techdb.SIGNATURES:
        assert s["category"] in techdb.CATEGORIES, s["name"]
        assert s["url"] or s["html"] or s["js"] or s["cookie"] or s["header"], s["name"]


def test_signature_names_are_unique():
    seen = [s["name"] for s in techdb.SIGNATURES]
    assert len(seen) == len(set(seen))


def test_registrable_domain_handles_two_part_suffixes():
    assert techdb.registrable("www.example.com") == "example.com"
    assert techdb.registrable("shop.example.co.in") == "example.co.in"
    assert techdb.registrable("a.b.example.com.au") == "example.com.au"
    assert techdb.registrable("localhost") == "localhost"
