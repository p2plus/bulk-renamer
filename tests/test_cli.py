"""CLI tests: run the console script in-process via cli.main()."""
import json

import pytest

from bulk_renamer.cli import main


def make_files(root, *names):
    for n in names:
        (root / n).write_text("x", encoding="utf-8")


def names_in(root):
    return {p.name for p in root.iterdir() if p.is_file() and not p.name.startswith(".")}


def test_rules_subcommand(capsys):
    assert main(["rules"]) == 0
    out = capsys.readouterr().out
    assert "replace" in out and "number" in out


def test_dry_run_is_default(tmp_path, capsys):
    make_files(tmp_path, "IMG_1.jpg")
    rc = main([str(tmp_path), "--prefix", "x_"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "IMG_1.jpg" in out and "x_IMG_1.jpg" in out
    assert "dry run" in out
    assert names_in(tmp_path) == {"IMG_1.jpg"}  # untouched


def test_apply_and_undo(tmp_path, capsys):
    make_files(tmp_path, "IMG_1.jpg", "IMG_2.jpg")
    rc = main([str(tmp_path), "--prefix", "x_", "--apply"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "applied: 2" in out
    assert names_in(tmp_path) == {"x_IMG_1.jpg", "x_IMG_2.jpg"}

    rc = main([str(tmp_path), "--undo"])
    assert rc == 0
    assert "undone: 2" in capsys.readouterr().out
    assert names_in(tmp_path) == {"IMG_1.jpg", "IMG_2.jpg"}


def test_json_output(tmp_path, capsys):
    make_files(tmp_path, "a.txt")
    rc = main([str(tmp_path), "--prefix", "z_", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["root"] == str(tmp_path.resolve())
    row = next(r for r in data["rows"] if r["source"] == "a.txt")
    assert row["target"] == "z_a.txt" and row["status"] == "rename"


def test_problems_block_apply(tmp_path, capsys):
    make_files(tmp_path, "a.txt", "b.txt")
    rc = main([str(tmp_path), "--replace", "a", "b", "--apply"])
    assert rc == 1
    assert "refusing" in capsys.readouterr().err
    assert names_in(tmp_path) == {"a.txt", "b.txt"}


def test_bad_regex_exits_nonzero(tmp_path, capsys):
    rc = main([str(tmp_path), "--regex", "(", "x"])
    assert rc == 1
    assert "error" in capsys.readouterr().err


def test_undo_without_journal_fails(tmp_path, capsys):
    rc = main([str(tmp_path), "--undo"])
    assert rc == 1
    assert "error" in capsys.readouterr().err


def test_filter_flag(tmp_path, capsys):
    make_files(tmp_path, "a.log", "a.txt")
    rc = main([str(tmp_path), "--filter", "*.log", "--prefix", "x_", "--json"])
    assert rc == 0
    rows = json.loads(capsys.readouterr().out)["rows"]
    assert {r["source"] for r in rows} == {"a.log"}


def test_rules_file(tmp_path):
    make_files(tmp_path, "f1.txt")
    rf = tmp_path.parent / "rules.json"
    rf.write_text(json.dumps([
        {"kind": "replace", "find": "f", "replace_with": "g"},
        {"kind": "number", "template": "{i:02d}_{name}", "start": 1, "step": 1},
    ]))
    rc = main([str(tmp_path), "--rules", str(rf), "--apply"])
    assert rc == 0
    assert names_in(tmp_path) == {"01_g1.txt"}
