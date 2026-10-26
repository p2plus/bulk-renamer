"""Local web GUI: a stdlib HTTP server on 127.0.0.1 plus one static HTML page.

No dependencies, no build step. The server speaks JSON and never touches
anything outside the directory you point it at.
"""
from __future__ import annotations

import argparse
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .engine import PlanError, RenamePlan, RuleError, load_rules_file

STATIC_DIR = Path(__file__).parent / "static"
MAX_BODY = 1 << 20  # 1 MB of JSON is plenty for a rules payload


class Handler(BaseHTTPRequestHandler):
    server_version = "bulk-renamer/1.0"

    # ---------------------------------------------------------------- helpers
    def _json(self, obj, status: int = 200) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message: str, status: int = 400) -> None:
        self._json({"error": message}, status)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_BODY:
            raise ValueError("request body too large")
        return json.loads(self.rfile.read(length) or b"{}")

    def log_message(self, fmt, *args):  # quiet by default
        if getattr(self.server, "verbose", False):
            super().log_message(fmt, *args)

    # ------------------------------------------------------------------ routes
    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            page = (STATIC_DIR / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
            return
        if url.path == "/api/files":
            qs = parse_qs(url.query)
            root = Path(qs.get("dir", [""])[0]).expanduser()
            if not root.is_dir():
                return self._error(f"not a directory: {root}")
            pattern = qs.get("filter", ["*"])[0] or "*"
            recursive = qs.get("recursive", ["0"])[0] == "1"
            from fnmatch import fnmatch
            it = root.rglob("*") if recursive else root.iterdir()
            files = sorted(
                str(f.relative_to(root))
                for f in it if f.is_file() and fnmatch(f.name, pattern)
            )
            return self._json({"root": str(root.resolve()), "files": files})
        return self._error("not found", 404)

    def do_POST(self):
        url = urlparse(self.path)
        try:
            body = self._body()
        except (ValueError, json.JSONDecodeError) as e:
            return self._error(f"bad request body: {e}")

        if url.path in ("/api/plan", "/api/apply"):
            try:
                plan = self._plan_from(body)
            except (RuleError, PlanError) as e:
                return self._error(str(e))
            if url.path == "/api/plan":
                return self._json({
                    "root": str(plan.root), "rows": plan.rows(),
                    "problems": plan.problem_count, "changes": len(plan.changes),
                })
            journal = Path(body.get("journal") or (plan.root / ".bulk-renamer-undo.json"))
            try:
                plan.apply(journal)
            except (PlanError, OSError) as e:
                return self._error(str(e))
            return self._json({
                "applied": len(plan.changes), "journal": str(journal),
            })

        if url.path == "/api/undo":
            journal = Path(body.get("journal") or "")
            if not body.get("journal"):
                root = Path(body.get("dir", "")).expanduser()
                if not root.is_dir():
                    return self._error(f"not a directory: {root}")
                journal = root / ".bulk-renamer-undo.json"
            try:
                ops = RenamePlan.undo(journal)
            except (FileNotFoundError, PlanError) as e:
                return self._error(str(e))
            return self._json({"undone": len(ops)})

        return self._error("not found", 404)

    @staticmethod
    def _plan_from(body: dict) -> RenamePlan:
        root = Path(str(body.get("dir", ""))).expanduser()
        rules = body.get("rules") or []
        if body.get("rules_file"):
            rules = load_rules_file(Path(body["rules_file"]))
        from .engine import Rule
        rules = [r if isinstance(r, Rule) else Rule.from_json(r) for r in rules]
        return RenamePlan.build(
            root, rules,
            file_filter=str(body.get("filter", "*")) or "*",
            recursive=bool(body.get("recursive", False)),
        )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="bulk-renamer-gui",
                                 description="bulk-renamer web UI on localhost")
    ap.add_argument("--port", type=int, default=0,
                    help="port to listen on (default: pick a free one)")
    ap.add_argument("--no-browser", action="store_true",
                    help="don't open the browser automatically")
    args = ap.parse_args(argv)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}"
    print(f"bulk-renamer GUI at {url}  (Ctrl-C to stop)")
    if not args.no_browser:
        threading.Timer(0.3, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
