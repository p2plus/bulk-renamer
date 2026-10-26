"""Command-line interface. Dry-run is the default; you must ask for damage."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .engine import (
    JOURNAL_NAME,
    RULE_KINDS,
    PlanError,
    RenamePlan,
    Rule,
    RuleError,
    load_rules_file,
)

# Convenience flags append rules in this fixed order; numbering runs last so
# counters see the final names. Use --rules for exact ordering.
_FLAG_ORDER = (
    "replace", "regex", "prefix", "suffix", "insert",
    "remove", "case", "extension", "sanitize", "number",
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bulk-renamer",
        description="Bulk-rename files with a preview first. Dry-run is the default.",
        epilog="Rules compose in the fixed order listed under 'bulk-renamer rules'. "
               "For exact ordering, put them in a JSON file and pass --rules.",
    )
    p.add_argument("directory", type=Path, help="directory containing the files")
    p.add_argument("--filter", default="*", metavar="GLOB",
                   help="only rename files matching this glob (default: *)")
    p.add_argument("-r", "--recursive", action="store_true",
                   help="include subdirectories")
    p.add_argument("--rules", type=Path, metavar="FILE",
                   help="JSON file with rules (list of {\"kind\": ..., ...}); "
                        "overrides individual rule flags")
    p.add_argument("--apply", action="store_true",
                   help="actually rename (default is a dry-run preview)")
    p.add_argument("--undo", action="store_true",
                   help="undo the last apply, using the journal in DIRECTORY")
    p.add_argument("--journal", type=Path, metavar="FILE",
                   help=f"journal path (default: DIRECTORY/{JOURNAL_NAME})")
    p.add_argument("--json", action="store_true", help="machine-readable output")

    g = p.add_argument_group("rules (compose in the order shown by 'bulk-renamer rules')")
    g.add_argument("--replace", nargs=2, metavar=("FIND", "REPLACE"), action="append",
                   help="literal find & replace")
    g.add_argument("--regex", nargs=2, metavar=("PATTERN", "REPLACE"), action="append",
                   help="regular-expression replace")
    g.add_argument("--prefix", metavar="TEXT", action="append",
                   help="text to prepend")
    g.add_argument("--suffix", metavar="TEXT", action="append",
                   help="text to append before the extension")
    g.add_argument("--insert", nargs=2, metavar=("TEXT", "POS"), action="append",
                   help="insert TEXT at position POS (negative = from the end)")
    g.add_argument("--remove", nargs=2, metavar=("START", "COUNT"), action="append",
                   help="remove COUNT characters at START (negative START = from the end)")
    g.add_argument("--case", choices=("lower", "upper", "title", "sentence"),
                   help="change case of the whole name")
    g.add_argument("--ext", metavar="EXT", help="set a new extension ('' strips it)")
    g.add_argument("--sanitize", action="store_true",
                   help="replace filesystem-illegal characters with '_'")
    g.add_argument("--number", nargs=3, metavar=("TEMPLATE", "START", "STEP"), action="append",
                   help="number with a template, e.g. '{name}_{i:03d}' 1 1")

    return p


def _rules_from_args(args: argparse.Namespace) -> list:
    if args.rules:
        return load_rules_file(args.rules)

    rules: list = []
    for pair in args.replace or []:
        rules.append(Rule("replace", {"find": pair[0], "replace_with": pair[1]}))
    for pair in args.regex or []:
        rules.append(Rule("regex", {"pattern": pair[0], "replace_with": pair[1]}))
    for t in args.prefix or []:
        rules.append(Rule("prefix", {"text": t}))
    for t in args.suffix or []:
        rules.append(Rule("suffix", {"text": t}))
    for pair in args.insert or []:
        rules.append(Rule("insert", {"text": pair[0], "position": int(pair[1])}))
    for pair in args.remove or []:
        rules.append(Rule("remove", {"start": int(pair[0]), "count": int(pair[1])}))
    if args.case:
        rules.append(Rule("case", {"mode": args.case}))
    if args.ext is not None:
        rules.append(Rule("extension", {"ext": args.ext}))
    if args.sanitize:
        rules.append(Rule("sanitize"))
    for t in args.number or []:
        rules.append(Rule("number", {"template": t[0], "start": int(t[1]), "step": int(t[2])}))
    return rules


def _print_plan(plan: RenamePlan) -> None:
    width = max((len(i.source.name) for i in plan.items), default=0)
    for i in plan.items:
        if i.status == "noop":
            continue
        flag = f"  !! {'; '.join(i.problems)}" if i.problems else ""
        print(f"{i.source.name:<{width}}  ->  {i.target.name}{flag}")
    n_changes = len(plan.changes)
    print(
        f"\n{len(plan.items)} file(s), {n_changes} rename(s), "
        f"{plan.problem_count} problem(s)"
        + ("  [dry run — add --apply to execute]" if n_changes else "")
    )


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "rules":
        return _cmd_rules()

    args = build_parser().parse_args(argv)
    directory = args.directory

    if args.undo:
        journal = args.journal or (directory / JOURNAL_NAME)
        try:
            ops = RenamePlan.undo(journal)
        except (FileNotFoundError, PlanError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(f"undone: {len(ops)} rename(s) restored")
        return 0

    try:
        rules = _rules_from_args(args)
        plan = RenamePlan.build(directory, rules, args.filter, args.recursive)
    except (RuleError, PlanError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({"root": str(plan.root), "rows": plan.rows()}, indent=1))

    if plan.problem_count and args.apply:
        _print_plan(plan)
        print("error: refusing to apply — fix the problems above first", file=sys.stderr)
        return 1

    if args.apply:
        try:
            journal = args.journal or (directory / JOURNAL_NAME)
            ops = plan.apply(journal)
        except (PlanError, OSError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        if not args.json:
            print(f"applied: {len(ops)} rename(s). "
                  f"Undo with: bulk-renamer \"{directory}\" --undo")
        return 0

    if not args.json:
        _print_plan(plan)
    if plan.problem_count:
        return 1
    return 0


def _cmd_rules() -> int:
    docs = {
        "replace": "find=<str> replace_with=<str> regex=<bool>",
        "regex": "pattern=<str> replace_with=<str>",
        "prefix": "text=<str>",
        "suffix": "text=<str>",
        "insert": "text=<str> position=<int>",
        "remove": "start=<int> count=<int>",
        "case": "mode=<lower|upper|title|sentence>",
        "extension": "ext=<str> ('' strips the extension)",
        "sanitize": "replacement=<str> (default '_')",
        "number": "template=<str> start=<int> step=<int>  ({name}, {i} placeholders)",
    }
    for kind in RULE_KINDS:
        print(f"{kind:<10} {docs[kind]}")
    print(
        "\nRules apply in this order to every filename stem. "
        "A JSON --rules file runs in file order."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
