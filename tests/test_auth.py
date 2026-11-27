import time
from urllib.parse import parse_qs, urlparse

import pytest

from gga import auth

CID = "123456789012-abcdefghijklmnopqrstuvwxyz1234.apps.googleusercontent.com"
SECRET = "fake-test-secret-value-not-real-1"


@pytest.fixture
def web_env(monkeypatch):
    monkeypatch.setenv("GGA_REDIRECT_URI", "https://audit.example.com")
    monkeypatch.setenv("GGA_CLIENT_ID", CID)
    monkeypatch.setenv("GGA_CLIENT_SECRET", SECRET)
    monkeypatch.setenv("GGA_ALLOWED_DOMAIN", "example.com")


def test_web_mode_switches_on_with_the_redirect_setting(monkeypatch, web_env):
    assert auth.is_web() and auth.web_configured()
    monkeypatch.delenv("GGA_REDIRECT_URI")
    assert not auth.is_web()


def test_state_roundtrip_carries_an_own_client_and_never_exposes_it(web_env):
    state = auth.make_state({"id": CID, "secret": SECRET})
    assert SECRET not in state and CID not in state  # encrypted, not just encoded
    assert auth.read_state(state)["c"] == {"id": CID, "secret": SECRET}


def test_state_without_a_client_has_no_client(web_env):
    assert "c" not in auth.read_state(auth.make_state())


def test_tampered_or_garbage_or_expired_state_is_rejected(web_env):
    state = auth.make_state()
    assert auth.read_state(state[:-3] + "xyz") is None
    assert auth.read_state("not-a-state") is None
    assert auth.read_state("") is None
    assert auth.read_state(state, max_age=-1) is None


def test_state_from_another_server_key_is_rejected(monkeypatch, web_env):
    state = auth.make_state()
    monkeypatch.setenv("GGA_STATE_KEY", "a-different-secret")
    assert auth.read_state(state) is None


def test_shared_sign_in_link_has_the_right_shape(web_env):
    q = parse_qs(urlparse(auth.web_login_url()).query)
    assert q["redirect_uri"] == ["https://audit.example.com"] and q["client_id"] == [CID]
    assert q["access_type"] == ["offline"] and "code_challenge" not in q
    assert {s.rsplit("/", 1)[-1] for s in q["scope"][0].split()} >= {"analytics.readonly", "tagmanager.readonly"}
    assert auth.read_state(q["state"][0]) is not None


def test_own_client_link_uses_their_client_and_carries_it_in_state(web_env):
    own = {"id": "987654321098-zyxwvutsrqponmlkjihgfedcba9876.apps.googleusercontent.com", "secret": "fake-own-secret-value-not-real-2"}
    q = parse_qs(urlparse(auth.web_login_url(own)).query)
    assert q["client_id"] == [own["id"]]
    assert auth.read_state(q["state"][0])["c"] == own


@pytest.mark.parametrize("cid,secret", [("not-a-client", SECRET), (CID, "short"), ("", ""), ("x.apps.googleusercontent.com", SECRET)])
def test_bad_own_client_details_give_a_clear_error(web_env, cid, secret):
    with pytest.raises(auth.AuthError):
        auth.web_login_url({"id": cid, "secret": secret})


def test_callback_with_a_state_we_did_not_issue_is_refused(web_env):
    with pytest.raises(auth.AuthError, match="expired or was not started here"):
        auth.web_finish("some-code", "bogus")


def test_no_shared_client_and_no_own_client_is_a_clear_error(monkeypatch):
    monkeypatch.setenv("GGA_REDIRECT_URI", "https://audit.example.com")
    monkeypatch.delenv("GGA_CLIENT_ID", raising=False)
    monkeypatch.delenv("GGA_CLIENT_SECRET", raising=False)
    with pytest.raises(auth.AuthError):
        auth.web_login_url()


@pytest.mark.parametrize("kwargs", [{}, {"access_token": "short"}, {"refresh_token": "1//abc", "client_id": "bad", "client_secret": "x"}])
def test_bad_token_input_is_refused_before_any_network_call(kwargs):
    with pytest.raises(auth.AuthError):
        auth.creds_from_token(**kwargs)


def test_domain_restriction(monkeypatch, web_env):
    auth._domain_ok("person@example.com")
    with pytest.raises(auth.AuthError, match="limited to @example.com"):
        auth._domain_ok("person@gmail.com")
    monkeypatch.delenv("GGA_ALLOWED_DOMAIN")
    auth._domain_ok("anyone@anywhere.org")  # no restriction set


def test_scope_helper():
    assert auth.has_data_scopes(["https://www.googleapis.com/auth/analytics.readonly"])
    assert not auth.has_data_scopes(["openid", "email"])


def test_state_is_fresh_each_time(web_env):
    assert auth.make_state() != auth.make_state()
    t = time.time()
    assert auth.read_state(auth.make_state(), max_age=900) is not None and time.time() - t < 2

