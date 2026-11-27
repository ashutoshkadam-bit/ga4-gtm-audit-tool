import datetime
from types import SimpleNamespace

import pytest

from gga import history, schedule

UTC = datetime.timezone.utc
F_OLD = [dict(scope="GA4", account="Acme", entity="Acme web", entity_id="1", check="Data retention", status="PASS", detail="ok")]
F_NEW = [dict(scope="GA4", account="Acme", entity="Acme web", entity_id="1", check="Data retention", status="FAIL", detail="2 months")]


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("GGA_SCHEDULE_KEY", "test-schedule-key-not-real")


@pytest.fixture
def store(tmp_path):
    return history.Store("sqlite:///" + str(tmp_path / "t.db").replace("\\", "/"))


def creds(**kw):
    return SimpleNamespace(**dict(dict(refresh_token="1//refresh-token-value", client_id="cid.apps.googleusercontent.com", client_secret="secret-value-123"), **kw))


def make(store, owner="o1", **kw):
    args = dict(name="Weekly", frequency="weekly", accounts="acme", only="all", days=30, data_checks=True, webhook="", notify_email="")
    args.update(kw)
    return schedule.create(store, owner, "a@b.com", creds(), **args)


def test_seal_roundtrip_and_wrong_key(monkeypatch):
    sealed = schedule.seal({"a": 1})
    assert '{"a"' not in sealed and schedule.unseal(sealed) == {"a": 1}
    monkeypatch.setenv("GGA_SCHEDULE_KEY", "another-key")
    with pytest.raises(schedule.ScheduleError):
        schedule.unseal(sealed)


def test_hosted_copy_without_a_key_is_refused(monkeypatch):
    monkeypatch.delenv("GGA_SCHEDULE_KEY")
    monkeypatch.delenv("GGA_STATE_KEY", raising=False)
    monkeypatch.delenv("GGA_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("GGA_REDIRECT_URI", "https://audit.example.com")
    assert not schedule.key_configured()
    with pytest.raises(schedule.ScheduleError):
        schedule.seal({})


def test_create_stores_no_plain_secrets_and_isolates_people(store):
    make(store, webhook="")
    make(store, owner="o2", name="Other")
    mine = schedule.list_for(store, "o1")
    assert [s["name"] for s in mine] == ["Weekly"] and "secret_enc" not in mine[0]
    raw = schedule.get_row(store, "o1", mine[0]["id"])
    assert "1//refresh-token-value" not in raw["secret_enc"]
    assert schedule.get_row(store, "o2", mine[0]["id"]) is None
    assert not schedule.remove(store, "o2", mine[0]["id"]) and schedule.remove(store, "o1", mine[0]["id"])


@pytest.mark.parametrize("bad", [dict(name=""), dict(frequency="hourly"), dict(only="x"), dict(webhook="http://hooks.example.com/x"),
                                 dict(webhook="https://localhost/x"), dict(notify_email="nope")])
def test_bad_input_is_refused(store, bad):
    with pytest.raises(schedule.ScheduleError):
        make(store, **bad)


def test_sign_in_that_cannot_be_reused_is_refused(store):
    with pytest.raises(schedule.ScheduleError, match="cannot be reused"):
        schedule.create(store, "o", "a@b.com", creds(refresh_token=None), "x")


def test_session_only_history_cannot_schedule():
    with pytest.raises(schedule.ScheduleError, match="database"):
        schedule.create(history.SessionStore({}), "o", "a@b.com", creds(), "x")


def test_limit_per_person(store):
    for i in range(schedule.MAX_PER_PERSON):
        make(store, name=f"s{i}")
    with pytest.raises(schedule.ScheduleError, match="up to"):
        make(store, name="one too many")


def test_due_logic():
    now = datetime.datetime(2026, 1, 15, 3, 0, tzinfo=UTC)
    assert schedule.is_due(dict(last_run_at=None, frequency="weekly"), now)
    assert not schedule.is_due(dict(last_run_at=now - datetime.timedelta(days=3), frequency="weekly"), now)
    assert schedule.is_due(dict(last_run_at=now - datetime.timedelta(days=6, hours=23), frequency="weekly"), now)
    assert schedule.is_due(dict(last_run_at=now - datetime.timedelta(hours=22), frequency="daily"), now)


def fake_audit(findings):
    return lambda creds_, accounts, only, days, data, progress: (findings, [])


def test_run_saves_history_and_alerts_only_when_worse(store, monkeypatch):
    sent = []
    monkeypatch.setattr(schedule, "send_webhook", lambda url, text: sent.append(text) or "")
    monkeypatch.setattr(schedule.site, "check_public", lambda url: None)
    sid = make(store, webhook="https://hooks.example.com/x")
    row = schedule.get_row(store, "o1", sid)
    ok = lambda s: s  # noqa: E731
    st1, _ = schedule.run_one(store, row, audit=fake_audit(F_OLD), creds_fn=ok)
    assert st1 == "ok" and sent == []  # first run: nothing to compare, no alert
    runs = store.list_runs("o1", "audit")
    assert len(runs) == 1 and runs[0]["source"] == "scheduled" and runs[0]["n_pass"] == 1
    st2, msg = schedule.run_one(store, schedule.get_row(store, "o1", sid), audit=fake_audit(F_NEW), creds_fn=ok)
    assert st2 == "ok" and len(sent) == 1 and ("New problems" in sent[0] or "Got worse" in sent[0])
    after = schedule.list_for(store, "o1")[0]
    assert after["last_status"] == "ok" and after["last_run_id"] == store.list_runs("o1", "audit")[0]["id"]
    schedule.run_one(store, schedule.get_row(store, "o1", sid), audit=fake_audit(F_NEW), creds_fn=ok)
    assert len(sent) == 1  # nothing new the third time


def test_failure_is_recorded_and_reported_not_raised(store, monkeypatch):
    sent = []
    monkeypatch.setattr(schedule, "send_webhook", lambda url, text: sent.append(text) or "")
    monkeypatch.setattr(schedule.site, "check_public", lambda url: None)
    sid = make(store, webhook="https://hooks.example.com/x")

    def revoked(_):
        raise schedule.ScheduleError("Google no longer accepts the saved sign-in")
    status, msg = schedule.run_one(store, schedule.get_row(store, "o1", sid), creds_fn=revoked)
    assert status == "error" and "no longer accepts" in msg
    assert schedule.list_for(store, "o1")[0]["last_status"] == "error" and "could not run" in sent[0]


def test_run_due_skips_paused_and_not_due(store):
    a, b = make(store, name="a"), make(store, name="b")
    schedule.set_active(store, "o1", b, False)
    out = schedule.run_due(store, audit=fake_audit(F_OLD), creds_fn=lambda s: s)
    assert [o[0] for o in out] == [a]
    assert schedule.run_due(store, audit=fake_audit(F_OLD), creds_fn=lambda s: s) == []  # just ran, so not due


def test_webhook_payload_works_for_slack_and_discord(monkeypatch):
    posted = {}
    monkeypatch.setattr(schedule.site, "check_public", lambda url: None)
    monkeypatch.setattr(schedule.requests, "post", lambda url, json, **kw: posted.update(json) or SimpleNamespace(status_code=204))
    assert schedule.send_webhook("https://hooks.example.com/x", "hello") == ""
    assert posted == {"text": "hello", "content": "hello"}


def test_webhook_to_a_private_address_is_refused():
    assert "refused" in schedule.send_webhook("https://localhost/x", "hello")
