#!/usr/bin/env python3
"""Tiny local server for the PRD Builder.

Serves prd-generator.html as a static file (like `python3 -m http.server`)
and adds two extra endpoints. POST /save lets the browser tool write the
generated PRD directly into this folder instead of only offering a browser
download. GET /config tells the page which LLM base URL and model to default
to, which the page cannot work out on its own because a browser cannot read
your Claude Code settings. Everything stays on localhost, so nothing leaves
this machine.

Run it from this folder:   python3 server.py
Then open:                 http://localhost:4321/prd-generator.html
Self-check:                python3 server.py --selftest
"""

import json
import re
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DIR = Path(__file__).resolve().parent
MAX_BODY_BYTES = 2_000_000  # 2 MB is more than enough for a PRD
DEFAULT_BASE_URL = "https://api.anthropic.com"
DEFAULT_MODEL = "claude-sonnet-5"


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "untitled"


def settings_path() -> Path:
    """Return the path to the user's Claude Code settings on Windows, macOS or Linux."""
    return Path.home() / ".claude" / "settings.json"


def strip_alias_suffix(model: str) -> str:
    """Drop a trailing bracket suffix from a model name, for example "[1m]".

    Claude Code accepts a proxy alias like your-model-name[1m], but a
    LiteLLM proxy rejects that same name on /v1/messages with a 400. The bracket is
    a Claude Code routing hint, not part of the model name the endpoint knows.
    """
    stripped = re.sub(r"\[[^\]]*\]\s*$", "", model).strip()
    return stripped or model


def read_config(path=None) -> dict:
    """Return the base URL and model for the page, from the Claude Code settings.

    ANTHROPIC_BASE_URL supplies the base URL and ANTHROPIC_DEFAULT_SONNET_MODEL
    supplies the model. Either one falls back to its hardcoded default when the
    file is missing, unreadable, malformed, or silent on that name. The trailing
    slash comes off the base URL, because the page appends /v1/messages itself.
    A trailing bracket suffix comes off the model. See strip_alias_suffix.
    """
    path = path or settings_path()
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        env = data.get("env") or {}
        raw = {name: env.get(name) or data.get(name) for name in
               ("ANTHROPIC_BASE_URL", "ANTHROPIC_DEFAULT_SONNET_MODEL")}
    except (OSError, ValueError, AttributeError):
        raw = {}

    def pick(name, fallback):
        value = raw.get(name)
        return value.strip() if isinstance(value, str) and value.strip() else fallback

    return {
        "baseUrl": pick("ANTHROPIC_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
        "model": strip_alias_suffix(pick("ANTHROPIC_DEFAULT_SONNET_MODEL", DEFAULT_MODEL)),
    }


class Handler(SimpleHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        # /config reflects a file the user can edit while the server runs.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/config":
            self._send_json(200, read_config())
            return
        super().do_GET()

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


def selftest():
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "settings.json"
        defaults = {"baseUrl": DEFAULT_BASE_URL, "model": DEFAULT_MODEL}

        assert read_config(p) == defaults, "missing file"

        p.write_text('{"env": {"ANTHROPIC_BASE_URL": "https://proxy.example.com/",'
                     ' "ANTHROPIC_DEFAULT_SONNET_MODEL": "proxy-sonnet"}}')
        assert read_config(p) == {"baseUrl": "https://proxy.example.com",
                                 "model": "proxy-sonnet"}, "env values, slash stripped"

        p.write_text('{"env": {"ANTHROPIC_DEFAULT_SONNET_MODEL": "claude-5-sonnet-il2[1m]"}}')
        assert read_config(p)["model"] == "claude-5-sonnet-il2", "bracket suffix stripped"

        p.write_text('{"ANTHROPIC_BASE_URL": "https://top.example.com",'
                     ' "ANTHROPIC_DEFAULT_SONNET_MODEL": "top-sonnet"}')
        assert read_config(p) == {"baseUrl": "https://top.example.com",
                                 "model": "top-sonnet"}, "top-level values"

        p.write_text('{"env": {"ANTHROPIC_BASE_URL": "https://only-url.example.com"}}')
        assert read_config(p) == {"baseUrl": "https://only-url.example.com",
                                 "model": DEFAULT_MODEL}, "one name set, not the other"

        p.write_text('{"env": {"ANTHROPIC_BASE_URL": "  ",'
                     ' "ANTHROPIC_DEFAULT_SONNET_MODEL": "  "}}')
        assert read_config(p) == defaults, "blank values"

        p.write_text('{"env": {}}')
        assert read_config(p) == defaults, "no names"

        p.write_text('{"env": "not-a-dict"}')
        assert read_config(p) == defaults, "wrong shape"

        p.write_text("{ broken json")
        assert read_config(p) == defaults, "bad json"

    assert strip_alias_suffix("plain-model") == "plain-model", "no suffix to strip"
    assert strip_alias_suffix("a[1m] ") == "a", "trailing space after the suffix"
    assert strip_alias_suffix("a[1m]-b") == "a[1m]-b", "suffix not at the end, left alone"
    assert strip_alias_suffix("[1m]") == "[1m]", "nothing left, so keep the original"

    print("selftest ok")


def main():
    args = sys.argv[1:]
    if args and args[0] == "--selftest":
        selftest()
        return

    port = int(args[0]) if args else 4321
    handler = partial(Handler, directory=str(DIR))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    cfg = read_config()
    print(f"PRD Builder server running at http://localhost:{port}/prd-generator.html")
    print(f"Defaults: base URL {cfg['baseUrl']}, model {cfg['model']}")
    server.serve_forever()


if __name__ == "__main__":
    main()
