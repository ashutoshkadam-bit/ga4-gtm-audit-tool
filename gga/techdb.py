"""Technology signatures: what a page is built with and which tags, vendors and CDNs it uses.

Our own signatures, written for this tool (no third-party fingerprint database is copied). Each entry lists any of:
  url     regex matched against every network request URL
  html    regex matched against the page HTML
  js      names of JavaScript globals that prove the technology is running
  cookie  regex matched against cookie names
  header  {response header name: regex} matched against the document and resource response headers
It is easy to extend: add a line to SIGNATURES. Detection is evidence-based, and the evidence is shown in the report.
"""
import re

CATEGORIES = ["Tag manager", "Analytics", "Advertising", "Customer data / marketing", "Session replay / UX",
              "A/B testing", "Consent management", "CDN", "Server / hosting", "CMS / platform", "JavaScript framework",
              "Embeds and widgets", "Monitoring", "Security / bot protection", "Payments", "Chat / support"]


def S(name, cat, url=None, html=None, js=None, cookie=None, header=None):
    return dict(name=name, category=cat, url=url, html=html, js=js or [], cookie=cookie, header=header or {})


SIGNATURES = [
    # ---------------------------------------------------------------- tag managers
    S("Google Tag Manager", "Tag manager", url=r"googletagmanager\.com/gtm\.js", js=["google_tag_manager"],
      html=r"googletagmanager\.com/(gtm\.js|ns\.html)"),
    S("Google tag (gtag.js)", "Tag manager", url=r"googletagmanager\.com/gtag/js", js=["gtag"]),
    S("GTM (first-party or server-side loader)", "Tag manager", url=r"^https?://(?!www\.googletagmanager\.com)[^/]+/[^?]*gtm\.js\?id=GTM-"),
    S("Adobe Launch (Tags)", "Tag manager", url=r"assets\.adobedtm\.com", js=["_satellite"]),
    S("Tealium iQ", "Tag manager", url=r"tags\.tiqcdn\.com|tealiumiq\.com", js=["utag"]),
    S("Ensighten", "Tag manager", url=r"nexus\.ensighten\.com"),
    S("Segment", "Tag manager", url=r"cdn\.segment\.com|api\.segment\.io|cdn\.segment\.io"),
    S("Signal (BrightTag)", "Tag manager", url=r"s\.thebrighttag\.com"),
    # ---------------------------------------------------------------- analytics
    S("Google Analytics 4", "Analytics", url=r"(google-analytics|analytics\.google)\.com/g/collect|/g/collect\?v=2"),
    S("Universal Analytics (obsolete)", "Analytics", url=r"google-analytics\.com/(analytics\.js|(r/|j/)?collect\?|ga\.js)", js=["ga"]),
    S("Adobe Analytics", "Analytics", url=r"\.omtrdc\.net|\.2o7\.net|/b/ss/[^/]+/|AppMeasurement", js=["s_gi", "AppMeasurement"]),
    S("Adobe Experience Platform Web SDK", "Analytics", url=r"edge\.adobedc\.net|alloy(\.min)?\.js|/ee/([a-z0-9]+/)?v\d+/(interact|collect)", js=["alloy", "__alloyNS"]),
    S("Adobe Target", "Analytics", url=r"tt\.omtrdc\.net|/at\.js|target\.adobe\.com", js=["adobe.target"]),
    S("Adobe Experience Cloud ID / Audience Manager", "Analytics", url=r"demdex\.net|VisitorAPI", js=["Visitor"],
      cookie=r"^AMCV_|^AMCVS_"),
    S("Matomo", "Analytics", url=r"matomo\.(php|js)|piwik\.(php|js)", js=["_paq", "Matomo"]),
    S("Mixpanel", "Analytics", url=r"api(-js)?\.mixpanel\.com|cdn\.mxpnl\.com", js=["mixpanel"]),
    S("Amplitude", "Analytics", url=r"api2?\.amplitude\.com|cdn\.amplitude\.com", js=["amplitude"]),
    S("Heap", "Analytics", url=r"heapanalytics\.com", js=["heap"]),
    S("PostHog", "Analytics", url=r"(app|us|eu|i)\.posthog\.com|posthog-js", js=["posthog"]),
    S("Plausible", "Analytics", url=r"plausible\.io/(js|api/event)"),
    S("Snowplow", "Analytics", url=r"snowplow|/com\.snowplowanalytics\.snowplow/tp2", js=["snowplow"]),
    S("Piwik PRO", "Analytics", url=r"piwik\.pro|ppms\.(eu|us)"),
    S("comScore", "Analytics", url=r"scorecardresearch\.com|sb\.scorecardresearch"),
    S("Chartbeat", "Analytics", url=r"chartbeat\.(com|net)", js=["_sf_async_config"]),
    S("Parse.ly", "Analytics", url=r"parsely\.com|cdn\.parsely"),
    S("Quantcast Measure", "Analytics", url=r"quantserve\.com|quantcount\.com"),
    S("Yandex Metrica", "Analytics", url=r"mc\.yandex\.(ru|com)", js=["ym"]),
    S("Google Optimize (retired)", "A/B testing", url=r"optimize\.google\.com|googleoptimize\.com"),
    # ---------------------------------------------------------------- advertising
    S("Google Ads conversion / remarketing", "Advertising",
      url=r"googleadservices\.com|google\.com/pagead/(1p-)?(conversion|user-list)|googleads\.g\.doubleclick\.net/pagead|/ccm/collect"),
    S("Floodlight / Campaign Manager", "Advertising", url=r"fls\.doubleclick\.net|ad\.doubleclick\.net/activity"),
    S("Google Ad Manager / AdSense", "Advertising", url=r"securepubads\.g\.doubleclick\.net|pagead2\.googlesyndication\.com|adservice\.google\."),
    S("Meta (Facebook) Pixel", "Advertising", url=r"connect\.facebook\.net/[^/]+/fbevents\.js|facebook\.com/tr[/?]", js=["fbq"],
      cookie=r"^_fbp$|^_fbc$"),
    S("TikTok Pixel", "Advertising", url=r"analytics\.tiktok\.com|business-api\.tiktok\.com", js=["ttq"]),
    S("LinkedIn Insight Tag", "Advertising", url=r"snap\.licdn\.com|px\.ads\.linkedin\.com", js=["_linkedin_data_partner_ids"]),
    S("X (Twitter) pixel", "Advertising", url=r"static\.ads-twitter\.com|analytics\.twitter\.com|t\.co/i/adsct", js=["twq"]),
    S("Pinterest Tag", "Advertising", url=r"ct\.pinterest\.com|s\.pinimg\.com/ct/", js=["pintrk"]),
    S("Snap Pixel", "Advertising", url=r"sc-static\.net/scevent|tr\.snapchat\.com", js=["snaptr"]),
    S("Reddit Pixel", "Advertising", url=r"redditstatic\.com/ads|alb\.reddit\.com"),
    S("Microsoft Advertising UET (Bing)", "Advertising", url=r"bat\.bing\.com", js=["uetq"]),
    S("Criteo", "Advertising", url=r"criteo\.(com|net)", js=["criteo_q"]),
    S("Taboola", "Advertising", url=r"taboola\.com|cdn\.taboola", js=["_taboola"]),
    S("Outbrain", "Advertising", url=r"outbrain\.com|outbrainimg\.com", js=["obApi"]),
    S("The Trade Desk", "Advertising", url=r"adsrvr\.org"),
    S("Amazon Ads", "Advertising", url=r"amazon-adsystem\.com"),
    S("Yahoo / Verizon Ads", "Advertising", url=r"ads\.yahoo\.com|analytics\.yahoo\.com|udc\.yahoo\.com"),
    S("AppsFlyer Smart Banner / Web", "Advertising", url=r"appsflyer\.com|onelink\.me"),
    # ---------------------------------------------------------------- customer data / marketing
    S("HubSpot", "Customer data / marketing", url=r"js\.hs-scripts\.com|js\.hs-analytics\.net|js\.hsforms\.net|hubspot\.com/", js=["_hsq"],
      cookie=r"^hubspotutk$|^__hs"),
    S("Salesforce Pardot", "Customer data / marketing", url=r"pardot\.com|pi\.pardot"),
    S("Marketo", "Customer data / marketing", url=r"munchkin\.marketo\.net|mktoresp", js=["Munchkin"]),
    S("Klaviyo", "Customer data / marketing", url=r"klaviyo\.com|static\.klaviyo", js=["klaviyo"]),
    S("Braze", "Customer data / marketing", url=r"braze\.com|appboy\.com", js=["braze", "appboy"]),
    S("CleverTap", "Customer data / marketing", url=r"clevertap(-prod)?\.com|wzrkt\.com", js=["clevertap"]),
    S("MoEngage", "Customer data / marketing", url=r"moengage\.com", js=["Moengage"]),
    S("WebEngage", "Customer data / marketing", url=r"webengage\.(com|co)|webengage", js=["webengage"]),
    S("Netcore / Smartech", "Customer data / marketing", url=r"netcoresmartech\.com|smartech", js=["smartech"]),
    S("mParticle", "Customer data / marketing", url=r"mparticle\.com", js=["mParticle"]),
    S("RudderStack", "Customer data / marketing", url=r"rudderstack\.com|rudderlabs\.com", js=["rudderanalytics"]),
    S("Mailchimp", "Customer data / marketing", url=r"chimpstatic\.com|list-manage\.com"),
    # ---------------------------------------------------------------- session replay / UX
    S("Hotjar", "Session replay / UX", url=r"static\.hotjar\.com|script\.hotjar\.com|vars\.hotjar\.com", js=["hj"], cookie=r"^_hj"),
    S("Microsoft Clarity", "Session replay / UX", url=r"clarity\.ms", js=["clarity"], cookie=r"^_clck$|^_clsk$"),
    S("FullStory", "Session replay / UX", url=r"fullstory\.com|edge\.fullstory", js=["FS"]),
    S("Mouseflow", "Session replay / UX", url=r"mouseflow\.com", js=["mouseflow"]),
    S("Crazy Egg", "Session replay / UX", url=r"crazyegg\.com|script\.crazyegg"),
    S("Lucky Orange", "Session replay / UX", url=r"luckyorange\.(com|net)"),
    S("LogRocket", "Session replay / UX", url=r"logrocket\.(com|io)|lr-ingest", js=["LogRocket"]),
    # ---------------------------------------------------------------- A/B testing
    S("Optimizely", "A/B testing", url=r"cdn\.optimizely\.com|optimizely\.com/", js=["optimizely"]),
    S("VWO", "A/B testing", url=r"dev\.visualwebsiteoptimizer\.com|vwo\.com", js=["VWO", "_vwo_code"]),
    S("AB Tasty", "A/B testing", url=r"abtasty\.com", js=["ABTasty"]),
    S("Dynamic Yield", "A/B testing", url=r"dynamicyield\.com|dy-api", js=["DY"]),
    S("LaunchDarkly", "A/B testing", url=r"launchdarkly\.com"),
    # ---------------------------------------------------------------- consent management
    S("OneTrust", "Consent management", url=r"cdn\.cookielaw\.org|onetrust\.com|cookielaw\.org", js=["OneTrust", "OptanonWrapper"],
      cookie=r"^OptanonConsent$|^OptanonAlertBoxClosed$"),
    S("Cookiebot", "Consent management", url=r"consent\.cookiebot\.com|consentcdn\.cookiebot", js=["Cookiebot"], cookie=r"^CookieConsent$"),
    S("CookieYes", "Consent management", url=r"cdn-cookieyes\.com|cookieyes\.com", cookie=r"^cookieyes-consent$"),
    S("Usercentrics", "Consent management", url=r"usercentrics\.eu|app\.usercentrics", js=["UC_UI"]),
    S("Didomi", "Consent management", url=r"didomi\.io|sdk\.privacy-center\.org", js=["Didomi"], cookie=r"^didomi_token$"),
    S("TrustArc", "Consent management", url=r"trustarc\.com|truste\.com|consent\.trustarc"),
    S("Iubenda", "Consent management", url=r"iubenda\.com", js=["_iub"]),
    S("Osano", "Consent management", url=r"osano\.com", js=["Osano"]),
    S("Termly", "Consent management", url=r"termly\.io"),
    S("Complianz", "Consent management", html=r"complianz|cmplz", cookie=r"^cmplz_"),
    S("Google Funding Choices / CMP", "Consent management", url=r"fundingchoicesmessages\.google\.com"),
    S("Google Consent Mode signals", "Consent management", url=r"[?&]gcs=G1\d{2}|[?&]gcd="),
    # ---------------------------------------------------------------- CDN
    S("Cloudflare", "CDN", url=r"cdnjs\.cloudflare\.com|challenges\.cloudflare\.com|cloudflareinsights\.com", header={"server": r"^cloudflare", "cf-ray": r".+"}),
    S("Akamai", "CDN", url=r"akamaihd\.net|akamaized\.net|edgekey\.net|akamaiedge\.net",
      header={"server": r"akamai", "x-akamai-transformed": r".+", "akamai-grn": r".+", "x-cache": r"tcp_(hit|miss)"}),
    S("Fastly", "CDN", url=r"fastly\.net|fastlylb\.net", header={"x-served-by": r"cache-", "fastly-io-info": r".+", "x-fastly-request-id": r".+"}),
    S("Amazon CloudFront", "CDN", url=r"cloudfront\.net", header={"x-amz-cf-id": r".+", "via": r"cloudfront", "x-amz-cf-pop": r".+"}),
    S("Azure CDN / Front Door", "CDN", url=r"azureedge\.net|azurefd\.net|msecnd\.net", header={"x-azure-ref": r".+", "x-msedge-ref": r".+"}),
    S("Google Cloud CDN / storage", "CDN", url=r"storage\.googleapis\.com|googleusercontent\.com|gstatic\.com", header={"via": r"1\.1 google"}),
    S("Imperva / Incapsula", "CDN", header={"x-iinfo": r".+", "x-cdn": r"imperva|incapsula"}, cookie=r"^incap_ses|^visid_incap"),
    S("Sucuri", "CDN", header={"x-sucuri-id": r".+", "server": r"sucuri"}),
    S("Netlify", "CDN", header={"server": r"netlify", "x-nf-request-id": r".+"}),
    S("Vercel", "CDN", header={"server": r"^vercel", "x-vercel-id": r".+"}),
    S("Bunny CDN", "CDN", url=r"b-cdn\.net", header={"server": r"bunnycdn"}),
    S("jsDelivr", "CDN", url=r"cdn\.jsdelivr\.net"),
    S("unpkg", "CDN", url=r"unpkg\.com"),
    S("StackPath / Edgio / Limelight", "CDN", url=r"stackpathcdn\.com|edgio\.net|llnwd\.net|edgecastcdn\.net"),
    S("Alibaba Cloud CDN", "CDN", url=r"alicdn\.com|alikunlun"),
    S("KeyCDN / CDN77 / Gcore", "CDN", url=r"kxcdn\.com|cdn77\.org|gcdn\.co|gcore"),
    # ---------------------------------------------------------------- server / hosting
    S("nginx", "Server / hosting", header={"server": r"nginx"}),
    S("Apache", "Server / hosting", header={"server": r"apache"}),
    S("Microsoft IIS / ASP.NET", "Server / hosting", header={"server": r"microsoft-iis", "x-powered-by": r"asp\.net", "x-aspnet-version": r".+"}),
    S("LiteSpeed", "Server / hosting", header={"server": r"litespeed"}),
    S("PHP", "Server / hosting", header={"x-powered-by": r"php"}),
    S("Node.js / Express", "Server / hosting", header={"x-powered-by": r"express"}),
    S("Varnish cache", "Server / hosting", header={"via": r"varnish", "x-varnish": r".+"}),
    S("AWS (S3 / ELB)", "Server / hosting", header={"server": r"amazons3|awselb", "x-amz-request-id": r".+"}),
    # ---------------------------------------------------------------- CMS / platform
    S("WordPress", "CMS / platform", html=r"/wp-content/|/wp-includes/|name=[\"']generator[\"'] content=[\"']WordPress"),
    S("WooCommerce", "CMS / platform", html=r"woocommerce|/wp-content/plugins/woocommerce"),
    S("Shopify", "CMS / platform", url=r"cdn\.shopify\.com|myshopify\.com", js=["Shopify"]),
    S("Wix", "CMS / platform", url=r"static\.parastorage\.com|wixstatic\.com|static\.wixstatic"),
    S("Squarespace", "CMS / platform", url=r"static1?\.squarespace\.com|squarespace-cdn"),
    S("Webflow", "CMS / platform", html=r"webflow\.com|data-wf-(page|site)", js=["Webflow"]),
    S("Drupal", "CMS / platform", html=r"/sites/default/files|Drupal\.settings", js=["Drupal"]),
    S("Joomla", "CMS / platform", html=r"/media/jui/|name=[\"']generator[\"'] content=[\"']Joomla"),
    S("Magento / Adobe Commerce", "CMS / platform", html=r"/static/version\d+|Magento_|mage/cookies", js=["require.s.contexts._.config.paths.mage"]),
    S("Adobe Experience Manager", "CMS / platform", html=r"/etc\.clientlibs/|/content/dam/|/libs/granite/"),
    S("Sitecore", "CMS / platform", html=r"/sitecore/|-/media/"),
    S("BigCommerce", "CMS / platform", url=r"bigcommerce\.com|cdn11\.bigcommerce"),
    S("Framer", "CMS / platform", url=r"framerusercontent\.com|framer\.com"),
    S("Ghost", "CMS / platform", html=r"name=[\"']generator[\"'] content=[\"']Ghost"),
    S("HubSpot CMS", "CMS / platform", html=r"hs-sites|hubspotusercontent"),
    # ---------------------------------------------------------------- JavaScript frameworks
    S("React", "JavaScript framework", html=r"data-reactroot|react-dom|__REACT", js=["React"]),
    S("Next.js", "JavaScript framework", html=r"/_next/static/|__NEXT_DATA__", js=["__NEXT_DATA__"]),
    S("Nuxt", "JavaScript framework", html=r"/_nuxt/", js=["__NUXT__"]),
    S("Vue.js", "JavaScript framework", html=r"data-v-[0-9a-f]{6,}|vue(\.min)?\.js", js=["Vue", "__VUE__"]),
    S("Angular", "JavaScript framework", html=r"ng-version=|ng-app", js=["ng"]),
    S("Svelte / SvelteKit", "JavaScript framework", html=r"/_app/immutable/|svelte-[a-z0-9]{4,}"),
    S("Gatsby", "JavaScript framework", html=r"/page-data/|gatsby"),
    S("jQuery", "JavaScript framework", url=r"jquery([.-]\d[\w.-]*)?(\.min)?\.js", js=["jQuery"]),
    S("Bootstrap", "JavaScript framework", url=r"bootstrap(\.bundle)?(\.min)?\.(js|css)"),
    # ---------------------------------------------------------------- embeds and widgets
    S("Google Fonts", "Embeds and widgets", url=r"fonts\.googleapis\.com|fonts\.gstatic\.com"),
    S("Font Awesome", "Embeds and widgets", url=r"fontawesome|use\.fontawesome\.com"),
    S("YouTube embed", "Embeds and widgets", url=r"youtube(-nocookie)?\.com/(embed|iframe_api)|ytimg\.com"),
    S("Vimeo embed", "Embeds and widgets", url=r"player\.vimeo\.com|vimeocdn\.com"),
    S("Google Maps", "Embeds and widgets", url=r"maps\.googleapis\.com|maps\.google\.com/maps/api"),
    S("Google reCAPTCHA", "Security / bot protection", url=r"google\.com/recaptcha|gstatic\.com/recaptcha", js=["grecaptcha"]),
    S("hCaptcha", "Security / bot protection", url=r"hcaptcha\.com", js=["hcaptcha"]),
    S("Cloudflare Turnstile", "Security / bot protection", url=r"challenges\.cloudflare\.com/turnstile"),
    S("PerimeterX / HUMAN", "Security / bot protection", url=r"perimeterx\.net|px-cloud\.net|px-cdn\.net"),
    S("DataDome", "Security / bot protection", url=r"datadome\.co"),
    # ---------------------------------------------------------------- monitoring
    S("Sentry", "Monitoring", url=r"browser\.sentry-cdn\.com|sentry\.io|ingest\.sentry", js=["Sentry"]),
    S("New Relic", "Monitoring", url=r"js-agent\.newrelic\.com|bam\.nr-data\.net|nr-data\.net", js=["newrelic", "NREUM"]),
    S("Datadog RUM", "Monitoring", url=r"datadoghq\.(com|eu)|browser-intake", js=["DD_RUM"]),
    S("Bugsnag", "Monitoring", url=r"bugsnag\.com|d2wy8f7a9ursnm\.cloudfront\.net", js=["Bugsnag"]),
    # ---------------------------------------------------------------- payments
    S("Stripe", "Payments", url=r"js\.stripe\.com|stripe\.network", js=["Stripe"]),
    S("PayPal", "Payments", url=r"paypal\.com/sdk|paypalobjects\.com", js=["paypal"]),
    S("Razorpay", "Payments", url=r"checkout\.razorpay\.com|razorpay\.com", js=["Razorpay"]),
    S("PayU / CCAvenue / Paytm", "Payments", url=r"payu(money)?\.(in|com)|ccavenue\.com|securegw\.paytm\.in"),
    # ---------------------------------------------------------------- chat / support
    S("Intercom", "Chat / support", url=r"widget\.intercom\.io|intercomcdn\.com", js=["Intercom"]),
    S("Drift", "Chat / support", url=r"js\.driftt\.com|drift\.com", js=["drift"]),
    S("Zendesk", "Chat / support", url=r"static\.zdassets\.com|zopim\.com", js=["zE"]),
    S("Freshworks / Freshchat", "Chat / support", url=r"freshchat\.com|freshworks\.com|wchat\.freshchat", js=["fcWidget"]),
    S("LiveChat", "Chat / support", url=r"livechatinc\.com|cdn\.livechat", js=["LiveChatWidget"]),
    S("Tawk.to", "Chat / support", url=r"embed\.tawk\.to", js=["Tawk_API"]),
    S("Zoho SalesIQ", "Chat / support", url=r"salesiq\.zoho\.(com|in)|zohopublic", js=["$zoho"]),
]

_COMPILED = []
for _s in SIGNATURES:
    _COMPILED.append((_s,
                      re.compile(_s["url"], re.I) if _s["url"] else None,
                      re.compile(_s["html"], re.I) if _s["html"] else None,
                      re.compile(_s["cookie"]) if _s["cookie"] else None,
                      {k: re.compile(v, re.I) for k, v in _s["header"].items()}))


def detect(request_urls, html="", js_present=(), cookie_names=(), header_sets=()):
    """Returns a list of dicts: name, category, evidence (list of short strings), hits (number of matching requests).

    header_sets is an iterable of dicts of lower-case response headers (the document and any resources)."""
    js_present = set(js_present)
    found = []
    for sig, url_re, html_re, cookie_re, hdr in _COMPILED:
        ev, hits = [], 0
        if url_re:
            matched = [u for u in request_urls if url_re.search(u)]
            hits = len(matched)
            if matched:
                ev.append(f"{hits} request(s), e.g. {matched[0][:110]}")
        if html_re and html and html_re.search(html):
            ev.append("found in page HTML")
        for name in sig["js"]:
            if name in js_present:
                ev.append(f"JavaScript global {name}")
                break
        if cookie_re:
            hit = [c for c in cookie_names if cookie_re.search(c)]
            if hit:
                ev.append("cookie " + hit[0])
        for h, rx in hdr.items():
            for hs in header_sets:
                v = hs.get(h)
                if v and rx.search(v):
                    ev.append(f"header {h}: {str(v)[:60]}")
                    break
            else:
                continue
            break
        if ev:
            found.append(dict(name=sig["name"], category=sig["category"], evidence=ev, hits=hits))
    order = {c: i for i, c in enumerate(CATEGORIES)}
    found.sort(key=lambda t: (order.get(t["category"], 99), t["name"]))
    return found


# ---- registrable domain (first-party test) ---------------------------------------------------------------
_SECOND_LEVEL = {"co", "com", "org", "net", "gov", "edu", "ac", "nic", "res", "in", "or"}


def registrable(host):
    host = (host or "").lower().strip(".")
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    if len(parts[-1]) == 2 and parts[-2] in _SECOND_LEVEL:  # co.in, com.au, co.uk ...
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])
