# bulk-renamer

Renames a bunch of files. Shows you exactly what it's going to do first, and
lets you undo it after. That's the whole product.

Explorer and Finder still can't do this properly in 2026. The existing tools
are either abandonware, freemium nagware, or they rename your files before
showing you the result. This one doesn't do any of that.

- **Dry-run by default.** Nothing moves until you pass `--apply` or click Apply.
- **One-click undo.** Every apply writes a journal; `--undo` reverses it. No
  trash-bin magic, just the inverse operations.
- **Collision-aware.** Detects conflicts with existing files and between the
  renames themselves (two files renamed to the same name). Refuses to run a
  plan with problems.
- **Order-safe.** Chains and swaps (`a→b`, `b→a`) go through temp names
  internally, so they actually work instead of silently clobbering.
- **Zero dependencies.** Python stdlib. The GUI is a local web page served on
  127.0.0.1 — no Electron, no build step, no telemetry.

## Install

```sh
pip install .        # from a clone of this repo
```

Requires Python 3.10+. That's it.

## CLI

```sh
# preview (this is the default; nothing happens)
bulk-renamer ~/Pictures/vacation --replace IMG vacation

# do it
bulk-renamer ~/Pictures/vacation --replace IMG vacation --apply

# oops
bulk-renamer ~/Pictures/vacation --undo
```

Rules available:

```sh
bulk-renamer rules
```

```
replace    find=<str> replace_with=<str> regex=<bool>
regex      pattern=<str> replace_with=<str>
prefix     text=<str>
suffix     text=<str>
insert     text=<str> position=<int>
remove     start=<int> count=<int>
case       mode=<lower|upper|title|sentence>
extension  ext=<str> ('' strips the extension)
sanitize   replacement=<str> (default '_')
number     template=<str> start=<int> step=<int>  ({name}, {i} placeholders)
```

Flags compose; each rule runs in sequence on every filename. Numbering runs
last and files sort naturally (`file2` before `file10`):

```sh
bulk-renamer . --replace " " _ --case lower --number "{name}_{i:03d}" 1 1
```

For anything nontrivial, write the rules as JSON and get exact ordering:

```sh
bulk-renamer . --rules recipe.json --apply
```

```json
[
  { "kind": "replace", "find": "IMG", "replace_with": "vacation" },
  { "kind": "number", "template": "{name}_{i:03d}", "start": 1, "step": 1 }
]
```

Useful flags: `--filter "*.log"` to touch only some files, `-r` for
subdirectories, `--json` for machine-readable output.

## GUI

```sh
bulk-renamer-gui
```

Opens a local page where you add rules, watch the preview update as you type,
then hit Apply. Same engine, same undo. Serves on 127.0.0.1 only and reads
nothing beyond the directory you point it at.

## Why trust it

- The plan is computed in full before anything is touched, and problem plans
  are refused outright.
- The undo journal is written *before* the first rename happens.
- Renames that could collide mid-flight are staged through hidden temp names.

That said: it renames files on your disk. Preview first, and don't run it on
the only copy of anything you care about. Same advice as for every renamer,
including the ones that cost money.

## Development

```sh
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

43 tests, no network, no fixtures outside tmp dirs. The engine is pure logic;
CLI and GUI are thin shells over it.

## License

MIT. Do what you want.
