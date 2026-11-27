from gga import log


def test_secret_looking_fields_are_never_logged():
    out = log.clean(dict(client_secret="GOCSPX-abc", access_token="ya29.x", code="4/0abc", state="s", cookie="a=b", host="example.com", n=3))
    assert out["client_secret"] == out["access_token"] == out["code"] == out["state"] == out["cookie"] == "[hidden]"
    assert out["host"] == "example.com" and out["n"] == 3


def test_long_values_are_shortened():
    assert len(log.clean(dict(detail="x" * 5000))["detail"]) == 200


def test_people_are_identified_only_by_a_one_way_hash():
    a, b = log.who("Person@Example.com"), log.who("person@example.com")
    assert a == b and len(a) == 10 and "example" not in a
    assert log.who("") == ""


def test_events_are_one_json_line_with_time_and_level(capsys):
    rec = log.event("audit_run", ga4=2, gtm=5, user=log.who("p@example.com"))
    out = capsys.readouterr().out.strip().splitlines()[-1]
    assert out.startswith("{") and '"event": "audit_run"' in out and rec["ga4"] == 2 and rec["level"] == "INFO"


def test_exceptions_log_type_and_message_without_crashing_when_sentry_is_absent(capsys):
    rec = log.exception("thing_failed", ValueError("bad input"), host="example.com")
    assert rec["error_type"] == "ValueError" and rec["level"] == "ERROR"
    assert "thing_failed" in capsys.readouterr().out
