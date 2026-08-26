#!/usr/bin/env python3
"""Tiny local server for the PRD Builder.

Serves prd-generator.html as a static file (like `python3 -m http.server`)
and adds one extra endpoint, POST /save, so the browser tool can write the
generated PRD directly into this folder instead of only offering a browser
download. Everything stays on localhost, so nothing leaves this machine.

Run it from this folder:   python3 server.py
Then open:                 http://localhost:4321/prd-generator.html
"""

import json
import re
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DIR = Path(__file__).resolve().parent
MAX_BODY_BYTES = 2_000_000  # 2 MB is more than enough for a PRD


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "untitled"


class Handler(SimpleHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/save":
            self._send_json(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0 or length > MAX_BODY_BYTES:
            self._send_json(400, {"error": "invalid or oversized request body"})
            return

        try:
            data = json.loads(self.rfile.read(length))
            feature_name = str(data["featureName"])
            markdown = str(data["markdown"])
        except (KeyError, ValueError, json.JSONDecodeError):
            self._send_json(400, {"error": "expected JSON: {featureName, markdown}"})
            return

        if not markdown.strip():
            self._send_json(400, {"error": "markdown is empty"})
            return

        # Mirror the folder-picker layout: <app-name>/prd.md
        slug = slugify(feature_name)
        project_dir = DIR / slug
        project_dir.mkdir(parents=True, exist_ok=True)
        target = project_dir / "prd.md"
        target.write_text(markdown, encoding="utf-8")

        self._send_json(
            200,
            {"ok": True, "filename": f"{slug}/prd.md", "path": str(target)},
        )

    def log_message(self, fmt, *args):
        sys.stderr.write(f"{self.address_string()} - {fmt % args}\n")


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 4321
    handler = partial(Handler, directory=str(DIR))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"PRD Builder server running at http://localhost:{port}/prd-generator.html")
    server.serve_forever()


if __name__ == "__main__":
    main()
