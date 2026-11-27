"""Fix guides: why each check matters, how to fix it, and where the official source is.

Written in our own words from public documentation. Every link was found on the publisher's own site. A check with no
link has none because we did not find an authoritative page for it. Treat limits and defaults as of the writing date
(Nov 2026) and confirm against the linked page before acting, because Google changes them.
"""
GA = "https://support.google.com/analytics/answer/"
TM = "https://support.google.com/tagmanager/answer/"

_UA_SRC = ("Google: Universal Analytics migration Q&A", GA + "14196937")
_CONSENT_SRC = ("Tag Manager Help: Introduction to user consent management", TM + "12329599")
_KEY_SRC = ("Analytics Help: Mark events as key events", GA + "13128484")
_LIMITS_SRC = ("Analytics Help: Configuration limits", GA + "12229528")
_SETUP_SRC = ("Analytics Help: Set up Analytics for a website and/or app", GA + "14183469")

GUIDES = {
    # ------------------------------------------------------------------ GA4
    "Data retention": dict(
        why="Event-level data is kept for only 2 months unless you change it. That limits how far back Explorations "
            "and funnel reports can look. Standard aggregated reports are not affected.",
        fix="Admin > Data settings > Data retention. Set Event data retention to 14 months, the longest a standard "
            "property allows. The change takes effect after a short delay and can be reverted.",
        source=("Analytics Help: Data retention", GA + "7667196")),
    "Data streams": dict(
        why="A property with no data stream collects nothing, so it is empty or abandoned.",
        fix="Add a web or app data stream and install its tag, or archive the property if it is no longer used.",
        source=_SETUP_SRC),
    "Enhanced measurement": dict(
        why="When it is off, GA4 does not collect scrolls, outbound clicks, site search, video engagement, file "
            "downloads or form interactions automatically.",
        fix="Admin > Data streams > choose the stream > Enhanced measurement, and switch on the events you need.",
        source=("Analytics Help: Enhanced measurement events", GA + "9216061")),
    "Key events": dict(
        why="Key events are GA4's conversions. With none, nothing is reported as a conversion. Some events such as "
            "purchase are marked by default but do not fit sites that generate leads. Standard properties allow up "
            "to 30 key events.",
        fix="Mark your real business events (form submit, call click, thank-you page view) as key events. Do not "
            "mark page_view itself. Create a derived event for a specific page instead.",
        source=_KEY_SRC),
    "Key events firing": dict(
        why="A key event with no hits means that conversion is not being recorded, or the event is defined but "
            "irrelevant to the site (for example the default purchase event on a lead-generation site).",
        fix="Test the tag and trigger in Tag Manager Preview mode and Tag Assistant. Remove key events that do not "
            "apply and fix the ones that should fire.",
        source=_KEY_SRC),
    "Custom dimensions": dict(
        why="Standard properties allow 50 event-scoped and 25 user-scoped custom dimensions. Near the limit you "
            "cannot add new ones, and after deleting some you may have to wait before adding more.",
        fix="Archive dimensions that no report uses and reuse existing parameters before creating new ones.",
        source=_LIMITS_SRC),
    "Custom metrics": dict(
        why="Standard properties allow 50 custom metrics. They are informational here.",
        fix="Archive metrics nobody uses.",
        source=_LIMITS_SRC),
    "Google Ads links": dict(
        why="A link lets GA4 key events and audiences be used in Google Ads. No link means ad campaigns cannot use "
            "GA4 conversions.",
        fix="Admin > Product links > Google Ads links. Link the Ads accounts that advertise for this site."),
    "BigQuery links": dict(
        why="BigQuery export gives you raw event-level data. Standard properties have a daily export limit of about "
            "1 million events for the batch export, and exports pause if a property keeps exceeding it.",
        fix="Admin > Product links > BigQuery links. Link it where you need raw data, and watch the daily event "
            "count against the limit.",
        source=("Analytics Help: BigQuery Export", GA + "9358801")),
    "Google Signals": dict(
        why="Google signals adds cross-device reporting and demographics for users who consented, and it can trigger "
            "data thresholds that hide small groups. Its extra data is not included in the BigQuery export.",
        fix="Turn it on only if you need those reports and your consent setup allows it.",
        source=("Analytics Help: Activate Google signals", GA + "9445345")),
    "Attribution settings": dict(
        why="The attribution model and look-back windows decide which touchpoints get credit for a conversion. "
            "Different settings change reported numbers, including against Google Ads.",
        fix="Admin > Data display > Attribution settings. Choose the model and windows that match how your team "
            "reports, and keep them the same across properties you compare."),
    "Currency vs timezone": dict(
        why="A US dollar currency with an Asian time zone often means the property was created with defaults, so "
            "revenue shows in the wrong currency and daily boundaries are off.",
        fix="Admin > Property details. Set the right time zone and currency."),
    "Property details": dict(
        why="Time zone, currency and industry category shape reporting. Recorded for reference.",
        fix="Admin > Property details."),
    "Internal traffic filter": dict(
        why="Staff and agency visits distort traffic and conversions. The Google API does not expose filters, so "
            "this tool cannot check them. A data filter, once active, permanently changes the data it is applied to.",
        fix="Define internal traffic by IP address, create the data filter in Testing state, confirm it matches, "
            "then activate it.",
        source=("Analytics Help: Filter out internal traffic", GA + "10104470")),
    "Events last 30d": dict(
        why="No events in the window means tracking is broken, the tag was removed, or the property is abandoned.",
        fix="Check Realtime, then check the site with Tag Assistant. If the site is retired, archive the property.",
        source=_SETUP_SRC),
    "page_view present": dict(
        why="page_view is collected automatically on web streams once the Google tag is installed. Its absence "
            "usually means the tag is missing or blocked, or that the stream is for something else.",
        fix="Confirm the tag is on every page and not blocked by consent settings. Test with Tag Assistant.",
        source=("Analytics Help: Automatically collected events", GA + "9234069")),
    "Unassigned traffic": dict(
        why="Unassigned sessions could not be matched to a default channel group. A high share often points to "
            "inconsistent campaign tagging, or to tags that fire in the wrong order.",
        fix="Standardise UTM source and medium values, review referral exclusions, and check that the Google tag "
            "fires early on the page. Samples under a few hundred sessions are too small to judge.",
        source=("Analytics Help: Traffic acquisition report", GA + "12923437")),
    # ------------------------------------------------------------------ GTM
    "Published version": dict(
        why="A container that was never published does nothing on the website.",
        fix="Review the workspace in Preview mode, then submit and publish a version."),
    "Tags present": dict(
        why="A live version with no tags is either unused or never finished.",
        fix="Finish it, or delete the container if it is not used."),
    "Paused tags": dict(
        why="Paused tags never fire. They add clutter, slow reviews and hide what is really running.",
        fix="Delete tags that are obsolete. Container versions keep the history, so deleting is safe to undo."),
    "Tags with no firing trigger": dict(
        why="A tag with no trigger never fires unless another tag sequences it. A Conversion Linker without a "
            "trigger weakens Google Ads conversion measurement.",
        fix="Attach a trigger. Google suggests the All Pages trigger for a Conversion Linker in most cases.",
        source=("Tag Manager Help: Conversion linker", TM + "7549390")),
    "Unused triggers": dict(
        why="Triggers attached to no tag are clutter and make the container harder to review.",
        fix="Delete them after confirming no tag or trigger group uses them."),
    "Unused variables": dict(
        why="Variables referenced nowhere are clutter, and leftovers often hold old account IDs.",
        fix="Delete them after confirming nothing references them."),
    "Duplicate tags": dict(
        why="Two tags with the same settings and triggers can fire twice and double count conversions.",
        fix="Keep one, and delete or merge the other."),
    "Universal Analytics remnants": dict(
        why="Universal Analytics no longer processes data, so tags for it collect nothing.",
        fix="Remove the Universal Analytics tags and variables, and make sure a GA4 tag does the measuring.",
        source=_UA_SRC),
    "Hardcoded GA4 IDs in tags": dict(
        why="A measurement ID typed into many tags is easy to get wrong and slow to change.",
        fix="Store the ID once in a Constant variable, or reuse configuration settings, and reference it in the tags.",
        source=("Tag Manager Help: Reuse configuration settings", TM + "13438166")),
    "Custom HTML tags": dict(
        why="Custom HTML runs arbitrary code on your site, which is a security and performance risk. Google "
            "advises putting separate tools in separate Custom HTML tags.",
        fix="Replace them with built-in tag templates where one exists, review the rest, and split bundled code.",
        source=("Tag Manager Help: Custom tags", TM + "6107167")),
    "Default/test tag names": dict(
        why="Names like Test or Copy of in a live version suggest unfinished or forgotten work.",
        fix="Rename or delete them, and adopt a naming convention such as Platform - Event - Detail."),
    "Tag consent settings": dict(
        why="Consent settings decide whether a tag may fire for a visitor who has not agreed. Tags without them "
            "rely entirely on the site's own banner. Informational here.",
        fix="For sites subject to privacy law, review consent settings on every tag with the legal owner.",
        source=_CONSENT_SRC),
    "GA4 IDs referenced": dict(
        why="The GA4 measurement IDs found inside the container. Recorded for reference and for the cross-check.",
        fix="None needed."),
    "GA4 ID not in accessible properties": dict(
        why="The container sends data to a GA4 property you cannot open. It may belong to another team or client, "
            "be retired, or contain a typo.",
        fix="Ask the property owner for Viewer access, or confirm the ID is meant to be there."),
    # ------------------------------------------------------------------ live site
    "Page loads": dict(
        why="The page could not be read, so nothing else could be checked.",
        fix="Check the address, and whether the site blocks automated requests."),
    "GTM installed": dict(
        why="No Tag Manager container was found in the page HTML. It may be added by a plugin or script, or "
            "not installed.",
        fix="Check the page source and Tag Assistant. Install the container snippet if it is missing."),
    "Multiple GTM containers": dict(
        why="Several containers on one page raise the risk of duplicate tags and slower pages.",
        fix="Confirm each one is intended, and consolidate where you can."),
    "GTM noscript snippet": dict(
        why="The noscript iframe from the Tag Manager install guide was not found. Informational.",
        fix="Add it right after the opening body tag if you want to follow the install guide."),
    "GTM container in your accounts": dict(
        why="The container on the page is not in any Tag Manager account you can open, so you cannot audit or "
            "change it.",
        fix="Ask who owns the container and request access, or confirm it belongs to a third party."),
    "GTM container published": dict(
        why="Google returned an error for the container's public script, so it may not exist or may be unpublished.",
        fix="Check the container ID in the snippet and publish a version."),
    "GA4 tag present": dict(
        why="No GA4 measurement ID was found on the page or inside its containers.",
        fix="Install the Google tag or a GA4 tag in Tag Manager and test with Tag Assistant."),
    "Many GA4 IDs": dict(
        why="Several different GA4 IDs on one page may be intentional (for example roll-up properties) but often "
            "signal leftovers.",
        fix="Confirm each property is meant to receive this site's data."),
    "GA4 loaded twice": dict(
        why="The same GA4 ID in the page HTML and inside a Tag Manager container can send each page view twice.",
        fix="Keep one installation method and remove the other."),
    "GA4 ID in your properties": dict(
        why="The GA4 ID on the page belongs to no property you can open.",
        fix="Ask the owner for access, or confirm the site is meant to report elsewhere."),
    "Universal Analytics": dict(
        why="Universal Analytics no longer processes data, so a UA ID on a page collects nothing.",
        fix="Remove the UA code and use GA4.",
        source=_UA_SRC),
    "Other tracking IDs": dict(
        why="Google Ads and Meta pixel IDs found, listed for reference.",
        fix="None needed."),
    "Audit": dict(
        why="The check could not run, usually a permission problem or an API limit.",
        fix="Confirm you have access to the item and run it again."),
}


def guide(check):
    """Returns dict(why, fix, source=(title, url) or None) for a check name, or None."""
    g = GUIDES.get(check)
    if not g:
        return None
    return dict(check=check, why=g["why"], fix=g["fix"], source=g.get("source"))


def for_findings(findings, statuses=("FAIL", "WARN", "ERROR")):
    """Guides for the checks that actually have problems in these findings, with their counts, worst first."""
    counts = {}
    for r in findings:
        if r["status"] in statuses:
            c = counts.setdefault(r["check"], dict(FAIL=0, WARN=0, ERROR=0))
            c[r["status"]] += 1
    out = []
    for check, c in counts.items():
        g = guide(check)
        if g:
            out.append(dict(g, **c))
    out.sort(key=lambda g: (-(g["FAIL"] * 1000 + g["ERROR"] * 100 + g["WARN"]), g["check"]))
    return out
