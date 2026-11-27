"""Storage tests. They run on SQLite always, and on PostgreSQL too when GGA_TEST_DATABASE_URL is set (CI does this)."""
import os

import pytest

from gga import history

PG = os.environ.get("GGA_TEST_DATABASE_URL", "")


def findings(n=3, status="WARN"):
    return [dict(scope="GTM", account="Acme", entity=f"c{i}", entity_id=f"GTM-{i}", check="Paused tags", status=status, detail=f"{i} paused")
            for i in range(n)]


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.skipif(not PG, reason="no GGA_TEST_DATABASE_URL"))])
def store(request, tmp_path):
    if request.param == "sqlite":
        s = history.Store("sqlite:///" + str(tmp_path / "h.db").replace("\\", "/"), keep=5)
    else:
        s = history.Store(PG, keep=5)
        for t in ("findings", "runs"):
            with s.engine.begin() as c:
                c.exec_driver_sql(f"DELETE FROM {t}")
    yield s
    s.engine.dispose()


def test_save_list_and_read_back_a_run(store):
    rid = store.save_run("me", "audit", "GA4 & GTM audit", "Acme", findings(3) + findings(2, "PASS"), meta={"days": 30})
    runs = store.list_runs("me")
    assert len(runs) == 1 and runs[0]["id"] == rid
    assert (runs[0]["n_warn"], runs[0]["n_pass"], runs[0]["kind"], runs[0]["meta"]) == (3, 2, "audit", {"days": 30})
    back = store.get_findings("me", rid)
    assert len(back) == 5 and back[0]["check"] == "Paused tags" and back[0]["status"] == "WARN"


def test_people_only_see_their_own_runs(store):
    rid = store.save_run("alice", "audit", "t", "s", findings())
    assert store.list_runs("bob") == [] and store.get_run("bob", rid) is None and store.get_findings("bob", rid) == []
    assert store.delete_run("bob", rid) is False and len(store.list_runs("alice")) == 1


def test_newest_first_and_filter_by_kind(store):
    a = store.save_run("me", "audit", "t", "s", findings(1))
    b = store.save_run("me", "page", "t", "s", findings(1))
    assert [r["id"] for r in store.list_runs("me")] == [b, a]
    assert [r["id"] for r in store.list_runs("me", kind="audit")] == [a]


def test_delete_one_and_delete_all(store):
    ids = [store.save_run("me", "audit", "t", "s", findings(2)) for _ in range(3)]
    assert store.delete_run("me", ids[0]) is True
    assert store.get_findings("me", ids[0]) == [] and len(store.list_runs("me")) == 2
    assert store.delete_all("me") == 2 and store.list_runs("me") == []


def test_oldest_runs_are_pruned_beyond_the_limit(store):
    ids = [store.save_run("me", "audit", "t", "s", findings(1)) for _ in range(8)]
    kept = [r["id"] for r in store.list_runs("me")]
    assert kept == ids[::-1][:5]
    assert store.get_findings("me", ids[0]) == []


def test_pruning_is_per_person(store):
    for _ in range(7):
        store.save_run("alice", "audit", "t", "s", findings(1))
    store.save_run("bob", "audit", "t", "s", findings(1))
    assert len(store.list_runs("alice")) == 5 and len(store.list_runs("bob")) == 1


def test_a_large_run_is_stored_in_chunks(store):
    rid = store.save_run("me", "audit", "t", "s", findings(2500))
    assert len(store.get_findings("me", rid)) == 2500


def test_long_text_is_trimmed_not_rejected(store):
    f = findings(1)
    f[0]["detail"] = "x" * 5000
    f[0]["entity"] = "e" * 900
    rid = store.save_run("me", "audit", "t" * 500, "s", f)
    got = store.get_findings("me", rid)[0]
    assert len(got["detail"]) == 1000 and len(got["entity"]) == 400


def test_session_store_has_the_same_behaviour():
    s = history.SessionStore({}, keep=3)
    ids = [s.save_run("anyone", "audit", "t", "s", findings(2)) for _ in range(4)]
    assert [r["id"] for r in s.list_runs("anyone")] == ids[::-1][:3]
    assert len(s.get_findings("anyone", ids[-1])) == 2 and s.get_run("anyone", ids[0]) is None
    assert s.delete_run("anyone", ids[-1]) is True and s.delete_all("anyone") == 2


def test_owner_labels_are_stable_anonymous_and_case_insensitive():
    a, b = history.owner_id("Person@Example.com"), history.owner_id("person@example.com")
    assert a == b and len(a) == 32 and "person" not in a
    assert history.owner_id("") == "anonymous"


def test_postgres_urls_are_normalised_for_the_driver():
    assert history.normalize_url("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert history.normalize_url("postgresql://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert history.normalize_url("sqlite:///x.db") == "sqlite:///x.db"


def test_open_store_chooses_the_right_place(tmp_path, monkeypatch):
    monkeypatch.setenv("GGA_HOME", str(tmp_path))
    s, note = history.open_store({}, web=False)
    assert s.mode == "file" and note == ""
    s2, _ = history.open_store({}, web=True)
    assert s2.mode == "session"
    s3, _ = history.open_store({}, web=True, url="sqlite:///" + str(tmp_path / "x.db").replace("\\", "/"))
    assert s3.mode == "file"


def test_a_broken_database_url_falls_back_to_the_session_with_a_plain_note():
    s, note = history.open_store({}, web=True, url="postgresql://nobody:nothing@127.0.0.1:1/none")
    assert s.mode == "session" and "could not be opened" in note
