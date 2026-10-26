import json
from pathlib import Path

import pytest

from bulk_renamer.engine import (
    JOURNAL_NAME,
    PlanError,
    RenamePlan,
    Rule,
    RuleError,
    load_rules_file,
    natural_key,
)


def make_files(root: Path, *names: str) -> None:
    for n in names:
        (root / n).write_text("x", encoding="utf-8")


def names_in(root: Path) -> set:
    return {p.name for p in root.iterdir() if p.is_file() and not p.name.startswith(".")}


# --------------------------------------------------------------------- rules

def test_replace_literal():
    r = Rule("replace", {"find": "IMG", "replace_with": "foto"})
    assert r.apply("IMG_0001", ".jpg", 0) == ("foto_0001", ".jpg")


def test_replace_regex_mode():
    r = Rule("replace", {"find": r"(\d{4})", "replace_with": r"[\1]", "regex": True})
    assert r.apply("IMG_0001", "", 0) == ("IMG_[0001]", "")


def test_replace_regex_invalid_pattern_raises():
    with pytest.raises(RuleError):
        Rule("replace", {"find": "(", "replace_with": "x", "regex": True}).apply("a", "", 0)


def test_replace_empty_find_raises():
    with pytest.raises(RuleError):
        Rule("replace", {"find": "", "replace_with": "x"}).apply("a", "", 0)


def test_prefix_suffix_insert_remove():
    assert Rule("prefix", {"text": "pre_"}).apply("name", ".txt", 0) == ("pre_name", ".txt")
    assert Rule("suffix", {"text": "_v2"}).apply("name", ".txt", 0) == ("name_v2", ".txt")
    assert Rule("insert", {"text": "-", "position": 2}).apply("abcd", "", 0) == ("ab-cd", "")
    assert Rule("insert", {"text": "-", "position": 99}).apply("ab", "", 0) == ("ab-", "")
    assert Rule("insert", {"text": "-", "position": -1}).apply("abcd", "", 0) == ("abc-d", "")
    assert Rule("remove", {"start": 1, "count": 2}).apply("abcd", "", 0) == ("ad", "")
    assert Rule("remove", {"start": -2, "count": 2}).apply("abcd", "", 0) == ("ab", "")


def test_case_modes():
    assert Rule("case", {"mode": "lower"}).apply("ABC", "", 0) == ("abc", "")
    assert Rule("case", {"mode": "upper"}).apply("abc", "", 0) == ("ABC", "")
    assert Rule("case", {"mode": "title"}).apply("hello world", "", 0) == ("Hello World", "")
    assert Rule("case", {"mode": "sentence"}).apply("hELLO", "", 0) == ("Hello", "")
    with pytest.raises(RuleError):
        Rule("case", {"mode": "shout"}).apply("a", "", 0)


def test_extension_rule():
    assert Rule("extension", {"ext": "md"}).apply("readme", ".txt", 0) == ("readme", ".md")
    assert Rule("extension", {"ext": ""}).apply("readme", ".txt", 0) == ("readme", "")
    assert Rule("extension", {"ext": ".pdf"}).apply("readme", ".txt", 0) == ("readme", ".pdf")


def test_sanitize():
    r = Rule("sanitize")
    assert r.apply('a<b>c:"d/e\\f|g?h*i', ".tx?t", 0) == ("a_b_c__d_e_f_g_h_i", ".tx_t")
    assert r.apply("  dots... ", "", 0) == ("dots", "")


def test_number_default_and_custom():
    assert Rule("number").apply("holiday", ".jpg", 0) == ("holiday_001", ".jpg")
    assert Rule("number").apply("holiday", ".jpg", 4) == ("holiday_005", ".jpg")
    r = Rule("number", {"template": "{i:02d}-{name}", "start": 10, "step": 5})
    assert r.apply("a", "", 0) == ("10-a", "")
    assert r.apply("a", "", 2) == ("20-a", "")


def test_number_bad_templates_raise():
    with pytest.raises(RuleError):
        Rule("number", {"template": "{bogus}"}).apply("a", "", 0)
    with pytest.raises(RuleError):
        Rule("number", {"template": "static"}).apply("a", "", 0)


def test_unknown_kind_raises():
    with pytest.raises(RuleError):
        Rule("explode")


def test_rule_json_roundtrip():
    r = Rule("replace", {"find": "a", "replace_with": "b", "regex": True})
    assert Rule.from_json(r.to_json()) == r


def test_load_rules_file(tmp_path):
    f = tmp_path / "rules.json"
    f.write_text(json.dumps([{"kind": "prefix", "text": "x_"}]))
    rules = load_rules_file(f)
    assert rules == [Rule("prefix", {"text": "x_"})]


def test_natural_sort():
    keys = sorted(["file10", "file2", "file1"], key=natural_key)
    assert keys == ["file1", "file2", "file10"]


# ---------------------------------------------------------------------- plan

def test_plan_basic_rename_and_noop(tmp_path):
    make_files(tmp_path, "IMG_1.txt", "keep.txt")
    plan = RenamePlan.build(tmp_path, [Rule("replace", {"find": "IMG", "replace_with": "pic"})])
    assert plan.changes[0].target.name == "pic_1.txt"
    statuses = {i.source.name: i.status for i in plan.items}
    assert statuses == {"IMG_1.txt": "rename", "keep.txt": "noop"}


def test_plan_duplicate_targets_flagged(tmp_path):
    make_files(tmp_path, "a.txt", "b.txt")
    plan = RenamePlan.build(tmp_path, [Rule("replace", {"find": "[ab]", "replace_with": "x", "regex": True})])
    assert plan.problem_count == 2
    assert all("conflicts" in p for it in plan.items for p in it.problems)


def test_plan_collision_with_existing_file(tmp_path):
    make_files(tmp_path, "a.txt", "b.txt")
    plan = RenamePlan.build(tmp_path, [Rule("replace", {"find": "a", "replace_with": "b"})])
    assert plan.problem_count == 1
    assert "target already exists" in plan.items[0].problems[0]


def test_plan_swap_rules_are_not_problems(tmp_path):
    # Rules compose per-file, so a swap needs a marker rule; the resulting
    # plan (a->b, b->a) must still be flagged as clean, not as a collision.
    make_files(tmp_path, "a.txt", "b.txt")
    rules = [
        Rule("replace", {"find": "^a$", "replace_with": "TMP", "regex": True}),
        Rule("replace", {"find": "^b$", "replace_with": "a", "regex": True}),
        Rule("replace", {"find": "TMP", "replace_with": "b"}),
    ]
    plan = RenamePlan.build(tmp_path, rules)
    assert plan.problem_count == 0
    assert {i.source.name: i.target.name for i in plan.changes} == {
        "a.txt": "b.txt", "b.txt": "a.txt",
    }


def test_plan_empty_result_name_flagged(tmp_path):
    make_files(tmp_path, "ab.txt")
    plan = RenamePlan.build(tmp_path, [Rule("remove", {"start": 0, "count": 2})])
    assert plan.problem_count == 1
    assert "empty" in plan.items[0].problems[0]


def test_plan_filter_and_recursive(tmp_path):
    make_files(tmp_path, "a.log", "b.txt")
    sub = tmp_path / "sub"
    sub.mkdir()
    make_files(sub, "c.log")
    plan = RenamePlan.build(
        tmp_path,
        [Rule("prefix", {"text": "x_"})],
        file_filter="*.log",
        recursive=True,
    )
    assert {i.source.name for i in plan.items} == {"a.log", "c.log"}


def test_plan_numbering_uses_natural_order(tmp_path):
    make_files(tmp_path, "b10.txt", "b2.txt", "b1.txt")
    plan = RenamePlan.build(tmp_path, [Rule("number", {"template": "{name}_{i}", "start": 1, "step": 1})])
    order = [i.target.name for i in plan.changes]
    assert order == ["b1_1.txt", "b2_2.txt", "b10_3.txt"]


# --------------------------------------------------------------------- apply

def test_apply_and_undo_roundtrip(tmp_path):
    make_files(tmp_path, "IMG_1.jpg", "IMG_2.jpg")
    plan = RenamePlan.build(tmp_path, [Rule("replace", {"find": "IMG", "replace_with": "url"})])
    ops = plan.apply()
    assert len(ops) == 2
    assert names_in(tmp_path) == {"url_1.jpg", "url_2.jpg"}
    assert (tmp_path / JOURNAL_NAME).is_file()

    RenamePlan.undo(tmp_path / JOURNAL_NAME)
    assert names_in(tmp_path) == {"IMG_1.jpg", "IMG_2.jpg"}
    assert not (tmp_path / JOURNAL_NAME).exists()


def test_apply_swap_via_two_phase(tmp_path):
    make_files(tmp_path, "a.txt", "b.txt")
    rules = [
        Rule("replace", {"find": "a", "replace_with": "tmp"}),
        Rule("replace", {"find": "^b", "replace_with": "a", "regex": True}),
        Rule("replace", {"find": "tmp", "replace_with": "b"}),
    ]
    plan = RenamePlan.build(tmp_path, rules)
    assert plan.problem_count == 0
    plan.apply()
    assert names_in(tmp_path) == {"a.txt", "b.txt"}
    assert (tmp_path / "a.txt").read_text() == "x"  # both exist, contents untouched
    RenamePlan.undo(tmp_path / JOURNAL_NAME)
    assert names_in(tmp_path) == {"a.txt", "b.txt"}


def test_apply_chain_via_two_phase(tmp_path):
    # Build a real chain (a->b, b->c) directly at the engine level; rule
    # pipelines compose per file, so cross-file chains are constructed items.
    make_files(tmp_path, "a.txt", "b.txt")
    from bulk_renamer.engine import PlanItem
    items = [
        PlanItem(source=tmp_path / "a.txt", target=tmp_path / "b.txt"),
        PlanItem(source=tmp_path / "b.txt", target=tmp_path / "c.txt"),
    ]
    plan = RenamePlan(root=tmp_path, rules=[], items=items)
    assert plan.problem_count == 0
    plan.apply()
    assert names_in(tmp_path) == {"b.txt", "c.txt"}
    RenamePlan.undo(tmp_path / JOURNAL_NAME)
    assert names_in(tmp_path) == {"a.txt", "b.txt"}


def test_undo_of_multi_op_journal_is_a_chain_and_works(tmp_path):
    # swap via rules, then undo: undo ops (b->a, a->b) form a cycle again.
    make_files(tmp_path, "a.txt", "b.txt")
    rules = [
        Rule("replace", {"find": "^a$", "replace_with": "TMP", "regex": True}),
        Rule("replace", {"find": "^b$", "replace_with": "a", "regex": True}),
        Rule("replace", {"find": "TMP", "replace_with": "b"}),
    ]
    RenamePlan.build(tmp_path, rules).apply()
    assert names_in(tmp_path) == {"a.txt", "b.txt"}
    RenamePlan.undo(tmp_path / JOURNAL_NAME)
    assert names_in(tmp_path) == {"a.txt", "b.txt"}


def test_apply_refuses_on_problems(tmp_path):
    make_files(tmp_path, "a.txt", "b.txt")
    plan = RenamePlan.build(tmp_path, [Rule("replace", {"find": "a", "replace_with": "b"})])
    with pytest.raises(PlanError):
        plan.apply()
    assert names_in(tmp_path) == {"a.txt", "b.txt"}  # nothing touched


def test_undo_missing_journal(tmp_path):
    with pytest.raises(FileNotFoundError):
        RenamePlan.undo(tmp_path / "nope.json")


def test_apply_custom_journal_path(tmp_path):
    make_files(tmp_path, "x.txt")
    journal = tmp_path / "elsewhere.json"
    plan = RenamePlan.build(tmp_path, [Rule("prefix", {"text": "y_"})])
    plan.apply(journal)
    assert journal.is_file()
    RenamePlan.undo(journal)
    assert names_in(tmp_path) == {"x.txt"}
