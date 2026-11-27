from gga import core


class FakeAuditor:
    """Stands in for the Google-connected auditor so the runner can be tested offline."""

    def audit_ga4_property(self, p):
        if p["property"] == "boom":
            raise RuntimeError("api exploded")
        f = [dict(scope="GA4", account=p["account"], entity=p["property"], entity_id="1", check="Data streams", status="PASS", detail="")]
        return f, dict(scope="GA4", account=p["account"], entity=p["property"], entity_id="1", ids="G-KNOWN00001")

    def audit_gtm_container(self, c):
        f = [dict(scope="GTM", account=c["account"], entity=c["container"], entity_id=c["public_id"], check="Published version", status="PASS", detail="")]
        return f, dict(scope="GTM", account=c["account"], entity=c["container"], entity_id=c["public_id"], ids="G-KNOWN00001 G-UNKNOWN999")


def test_runner_collects_findings_progress_and_cross_check():
    ga4 = [dict(account="A", property="web")]
    gtm = [dict(account="A", container="site", public_id="GTM-1")]
    seen = []
    findings, inventory = core.run_audit(FakeAuditor(), ga4, gtm, progress=lambda d, n, label: seen.append((d, n)))
    assert seen == [(1, 2), (2, 2)] and len(inventory) == 2
    cross = [f for f in findings if f["check"] == "GA4 ID not in accessible properties"]
    assert len(cross) == 1 and "G-UNKNOWN999" in cross[0]["detail"]


def test_one_failing_item_becomes_an_error_row_and_the_run_continues():
    ga4 = [dict(account="A", property="boom"), dict(account="A", property="ok")]
    findings, _ = core.run_audit(FakeAuditor(), ga4, [])
    assert any(f["status"] == "ERROR" and f["entity"] == "boom" for f in findings)
    assert any(f["entity"] == "ok" and f["status"] == "PASS" for f in findings)


def test_stop_request_halts_the_run():
    ga4 = [dict(account="A", property=f"p{i}") for i in range(5)]
    n = {"c": 0}

    def stop():
        n["c"] += 1
        return n["c"] > 2

    findings, _ = core.run_audit(FakeAuditor(), ga4, [], should_stop=stop)
    assert len([f for f in findings if f["check"] == "Data streams"]) == 2


def test_cross_check_needs_known_ids():
    inv = [dict(scope="GTM", account="A", entity="x", entity_id="GTM-1", ids="G-AAAAAAAAAA")]
    assert core.cross_check(inv, set()) == []
    assert core.cross_check(inv, {"G-AAAAAAAAAA"}) == []
    assert len(core.cross_check(inv, {"G-OTHER00000"})) == 1


def test_options_have_safe_defaults():
    assert core.DEFAULTS["unassigned_threshold"] == 10 and core.DEFAULTS["days"] == 30


def test_short_err_never_raises_on_odd_errors():
    assert core.short_err(ValueError("plain")) == "plain"
    assert isinstance(core.short_err(Exception()), str)
