"""Public analytics and audit frameworks, summarised in our own words with links to the original sources.

Each entry says whether it rests on a public source or is general practice with no single authority. Nothing here is
legal advice. We link to the books and standards instead of reproducing them, because most are copyrighted.
"""
GA = "https://support.google.com/analytics/answer/"
TM = "https://support.google.com/tagmanager/answer/"
GOV_DQ = "https://www.gov.uk/government/publications/the-government-data-quality-framework/the-government-data-quality-framework"

FRAMEWORKS = [
    dict(
        name="The audit lifecycle",
        kind="General practice",
        what="Every audit follows the same loop: agree the scope, collect evidence, assess it against written criteria, "
             "report findings with a severity, fix, then re-audit to prove the fix. The value is in the written "
             "criteria and the re-check, not in the first report.",
        in_tool="Scope = the accounts you pick. Evidence = read-only Google API data. Criteria = the checks and their "
                "fix guides. Report = the Excel and HTML downloads. Re-audit = run the same selection again later and "
                "compare.",
        use_when="Before any client audit, so everyone agrees what 'done' means.",
        sources=[]),
    dict(
        name="Measurement planning",
        kind="General practice",
        what="Start from the business objective, then pick the few KPIs that show progress, then the events and "
             "parameters that produce those KPIs, then name an owner for each. Tracking added without a plan is the "
             "usual cause of unused events and dead key events.",
        in_tool="The 'Key events firing' and 'Key events' checks test the end of this chain: does each planned "
                "conversion actually record data? The unused-variable and unused-trigger checks find what the plan "
                "no longer needs.",
        use_when="Setting up a new property, or when an audit shows many dormant events or key events.",
        sources=[("Analytics Help: Mark events as key events", GA + "13128484"),
                 ("Analytics Help: About events", GA + "9322688")]),
    dict(
        name="Data quality dimensions",
        kind="Public source",
        what="Six dimensions are widely used to describe data quality: accuracy (reflects reality), completeness "
             "(nothing missing), consistency (agrees across systems), timeliness (available when needed), validity "
             "(follows the expected format and rules) and uniqueness (counted once). The UK government's framework "
             "builds on the DAMA UK work and explains each one.",
        in_tool="Completeness: events and key events firing. Validity: well-formed IDs, no Universal Analytics. "
                "Uniqueness: duplicate tags and the same GA4 ID loaded twice. Timeliness: events in the last 30 days. "
                "Consistency: GTM IDs against GA4 properties. Accuracy needs a source of truth (such as a CRM) and "
                "is not tested by this tool.",
        use_when="Explaining findings to non-technical stakeholders in a shared vocabulary.",
        sources=[("UK Government Data Quality Framework", GOV_DQ),
                 ("GOV.UK: Meet the data quality dimensions",
                  "https://www.gov.uk/government/news/meet-the-data-quality-dimensions")]),
    dict(
        name="Tag governance",
        kind="General practice",
        what="Treat the tag manager like production code: one named owner per container, a naming convention, "
             "review before publish, a version note for every release, and a regular clean-up of paused and unused "
             "items. Containers without this decay into the clutter our checks report.",
        in_tool="Paused tags, unused triggers and variables, duplicate tags, default or test names, hardcoded IDs "
                "and custom HTML counts all measure governance debt.",
        use_when="Agencies that manage many client containers, and any container that more than one person edits.",
        sources=[("Tag Manager Help: Custom tags", TM + "6107167"),
                 ("Tag Manager Help: Reuse configuration settings", TM + "13438166")]),
    dict(
        name="Privacy and consent",
        kind="Public source",
        what="Privacy rules shape what analytics may collect and when. The EU's GDPR sets principles such as "
             "lawfulness, purpose limitation and data minimisation, and requires a legal basis such as consent. India's "
             "Digital Personal Data Protection Act, 2023 sets consent and notice duties for personal data of people in "
             "India. NIST's Privacy Framework is a voluntary, free way to organise privacy risk work. Consent mode "
             "lets Google tags adjust behaviour according to the visitor's choice.",
        in_tool="The 'Tag consent settings' check shows how many tags have no consent settings, and the live site "
                "check reports what loads on a page. Neither tests whether tags wait for consent. That needs a "
                "real browser and a legal review.",
        use_when="Any site collecting data from visitors in the EU or India, or serving regulated clients.",
        sources=[("GDPR, Regulation (EU) 2016/679 (EUR-Lex)", "https://eur-lex.europa.eu/eli/reg/2016/679/oj"),
                 ("NIST Privacy Framework", "https://www.nist.gov/privacy-framework"),
                 ("Tag Manager Help: Introduction to user consent management", TM + "12329599"),
                 ("India DPDP Act 2023: read the official text published by the Ministry of Electronics and "
                  "Information Technology", None)]),
    dict(
        name="Attribution and reporting identity",
        kind="Public source",
        what="Attribution decides which touchpoint gets credit for a conversion. It depends on the model and the "
             "look-back windows, and reporting identity decides how users are counted across devices. Changing "
             "either changes reported numbers without any change in real behaviour.",
        in_tool="The 'Attribution settings' and 'Google Signals' checks record these settings so you can see where "
                "two properties are not comparable.",
        use_when="Numbers differ between GA4, Google Ads and another system, or between two properties.",
        sources=[("Analytics Help: Reporting identity", GA + "10976610")]),
    dict(
        name="Sampling, thresholds and data storage",
        kind="Public source",
        what="GA4 may sample large explorations, hides small groups with data thresholds to protect privacy, and "
             "keeps event-level data for a limited time. A report that looks wrong can be one of these working as "
             "designed.",
        in_tool="The 'Data retention' check covers storage. 'Google Signals' is a common cause of thresholding. "
                "The 'Unassigned traffic' check warns that small samples cannot be judged.",
        use_when="Before challenging a number that differs between two reports.",
        sources=[("Analytics Help: Data quality", GA + "12856703"),
                 ("Analytics Help: How Analytics stores and displays data", GA + "13888627"),
                 ("Analytics Help: Data retention", GA + "7667196")]),
    dict(
        name="Risk-based prioritisation",
        kind="General practice",
        what="Rank findings by impact on decisions and by effort to fix, then do the high-impact, low-effort ones "
             "first. A broken conversion beats a naming convention every time.",
        in_tool="FAIL means broken or missing, WARN a risk, INFO a record. The health score is 100 minus 20 per "
                "fail and 5 per warn or error. It is a sorting aid, not a measure of business impact.",
        use_when="Turning an audit into a plan with owners and dates.",
        sources=[]),
]

DQ_MAP = [
    ("Completeness", "Key events firing, Events last 30d, page_view present"),
    ("Validity", "Universal Analytics remnants, GA4 ID in your properties"),
    ("Uniqueness", "Duplicate tags, GA4 loaded twice"),
    ("Timeliness", "Events last 30d"),
    ("Consistency", "GA4 ID not in accessible properties, GTM container in your accounts"),
    ("Accuracy", "Not tested here. Needs a source of truth such as a CRM or sales records."),
]
