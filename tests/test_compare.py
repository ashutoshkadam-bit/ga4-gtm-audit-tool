import pytest

from gga import compare


def f(check, status, entity="c1", entity_id="GTM-1", account="Acme", scope="GTM", detail=""):
    return dict(scope=scope, account=account, entity=entity, entity_id=entity_id, check=check, status=status, detail=detail)


def counts(old, new):
    return compare.compare(old, new)["counts"]


def test_a_fixed_problem_is_resolved():
    c = compare.compare([f("Paused tags", "WARN", detail="3")], [f("Paused tags", "PASS", detail="0")])
    assert c["counts"]["resolved"] == 1 and c["resolved"][0]["was"] == "WARN" and c["resolved"][0]["now"] == "PASS"


def test_a_new_problem_is_reported():
    c = compare.compare([f("Paused tags", "PASS")], [f("Paused tags", "WARN", detail="2")])
    assert c["counts"]["new_problems"] == 1 and c["new_problems"][0]["now_detail"] == "2"


def test_warn_to_fail_is_worse_and_fail_to_warn_is_improved():
    assert counts([f("x", "WARN")], [f("x", "FAIL")])["worsened"] == 1
    assert counts([f("x", "FAIL")], [f("x", "WARN")])["improved"] == 1


def test_unchanged_problem_persists_and_flags_changed_detail():
    c = compare.compare([f("Paused tags", "WARN", detail="3")], [f("Paused tags", "WARN", detail="17")])
    assert c["counts"]["persisting"] == 1 and c["counts"]["changed"] == 1
    assert compare.compare([f("Paused tags", "WARN", detail="3")], [f("Paused tags", "WARN", detail="3")])["counts"]["changed"] == 0


def test_info_and_pass_are_not_problems():
    c = compare.compare([f("a", "INFO"), f("b", "PASS")], [f("a", "PASS"), f("b", "INFO")])
    assert all(v == 0 for v in c["counts"].values())


def test_items_in_only_one_run_are_listed_not_counted_as_changes():
    old = [f("Paused tags", "WARN", entity="gone", entity_id="GTM-OLD"), f("Paused tags", "WARN")]
    new = [f("Paused tags", "FAIL", entity="fresh", entity_id="GTM-NEW"), f("Paused tags", "WARN")]
    c = compare.compare(old, new)
    assert c["counts"]["new_problems"] == 0 and c["counts"]["resolved"] == 0
    assert [a[2] for a in c["added_items"]] == ["fresh"] and [a[2] for a in c["removed_items"]] == ["gone"]
    assert c["compared_items"] == 1


def test_a_check_that_did_not_run_is_not_counted_as_fixed():
    c = compare.compare([f("Paused tags", "WARN"), f("Unused triggers", "WARN")], [f("Paused tags", "WARN")])
    assert c["counts"]["resolved"] == 0 and c["not_rechecked"] == 1


def test_duplicate_rows_collapse_to_the_worst_status():
    old = [f("Enhanced measurement", "PASS", detail="stream a"), f("Enhanced measurement", "WARN", detail="stream b")]
    new = [f("Enhanced measurement", "PASS", detail="stream a"), f("Enhanced measurement", "PASS", detail="stream b")]
    assert counts(old, new)["resolved"] == 1


def test_page_audits_are_compared_per_address_not_per_host():
    a = f("Page loads", "PASS", scope="PAGE", entity="https://x.com/a", entity_id="x.com", account="x.com")
    b = f("Page loads", "FAIL", scope="PAGE", entity="https://x.com/b", entity_id="x.com", account="x.com")
    c = compare.compare([a], [b])
    assert c["compared_items"] == 0 and len(c["added_items"]) == 1 and len(c["removed_items"]) == 1


def test_health_scores_move_with_the_findings():
    c = compare.compare([f("a", "FAIL"), f("b", "WARN")], [f("a", "PASS"), f("b", "PASS")])
    row = c["health"][0]
    assert (row["was"], row["now"], row["change"]) == (75, 100, 25)
    assert c["score_old"] == 75 and c["score_new"] == 100


def test_headline_in_plain_words():
    assert compare.headline(compare.compare([f("a", "PASS")], [f("a", "WARN")])) == "1 new problem"
    assert "fixed" in compare.headline(compare.compare([f("a", "WARN")], [f("a", "PASS")]))
    assert compare.headline(compare.compare([f("a", "WARN")], [f("a", "WARN")])) == "no change in problems"


def test_empty_runs_do_not_crash():
    c = compare.compare([], [])
    assert c["compared_items"] == 0 and c["score_old"] is None


def test_baseline_from_a_findings_csv():
    data = ("scope,account,entity,entity_id,check,status,detail\n"
            "GTM,Acme,c1,GTM-1,Paused tags,WARN,3\nGTM,Acme,c1,GTM-1,Bad status row,NOPE,x\n").encode("utf-8-sig")
    rows = compare.baseline_from_csv(data)
    assert len(rows) == 1 and rows[0]["check"] == "Paused tags"


@pytest.mark.parametrize("data", [b"", b"a,b\n1,2\n", b"scope,account,entity,check,status\n"])
def test_baseline_from_a_wrong_file_gives_a_plain_error(data):
    with pytest.raises(ValueError, match="not a findings file|no usable findings"):
        compare.baseline_from_csv(data)


def test_comparison_csv_has_every_changed_row():
    c = compare.compare([f("a", "WARN"), f("b", "PASS")], [f("a", "PASS"), f("b", "FAIL")])
    text = compare.to_csv(c).decode("utf-8-sig")
    assert "resolved" in text and "new problems" in text
