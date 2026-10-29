"""The lab's local web server: a JSON API over `Machine` plus the static page in `web/`.

Stdlib only. It binds to 127.0.0.1, rejects foreign Host headers, and requires `X-Lab: 1` on POST so
a web page you happen to have open cannot drive it.
"""

import json
import os
import re
import subprocess
import sys
import threading
from concurrent.futures import TimeoutError as FutureTimeout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from gbtools.errors import ConvertError

from .emu import Machine

WEB = Path(__file__).parent / "web"
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def describe(m: Machine) -> list[dict]:
    return [
        {
            "name": t.name, "source": t.source, "symbol": t.symbol, "available": all(f.id in m.fields for f in t.fields),
            "fields": [
                {
                    "id": f.id, "path": list(f.path), "label": f.label, "type": f.type, "min": f.min, "max": f.max,
                    "default": f.default, "doc": f.doc, "values": f.values, "restart": f.restart,
                    "available": f.id in m.fields,
                }
                for f in t.fields
            ],
        }
        for t in m.tables
    ]


def replay_names(m: Machine) -> list[str]:
    return sorted(p.stem for p in m.replay_dir.glob("*.json")) if m.replay_dir.is_dir() else []


def name_arg(body: dict) -> str:
    name = body.get("name", "")
    if not isinstance(name, str) or not NAME.match(name):
        raise ApiError(400, "name must be letters, digits, '-' and '_' (at most 64), starting with a letter or digit")
    return name


def make_handler(m: Machine, port: int, repo: Path):
    class Handler(BaseHTTPRequestHandler):
        server_version = "BeatLab"

        def log_message(self, fmt, *args):  # quiet
            pass

        def _send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, status: int = 200) -> None:
            self._send(status, json.dumps(obj).encode(), "application/json")

        def _host_ok(self) -> bool:
            return self.headers.get("Host", "") in (f"localhost:{port}", f"127.0.0.1:{port}")

        def _guard(self, fn) -> None:
            try:
                if not self._host_ok():
                    raise ApiError(403, "unexpected Host header")
                fn()
            except ApiError as e:
                self._json({"error": str(e)}, e.status)
            except (KeyError, ValueError, ConvertError) as e:
                self._json({"error": str(e.args[0] if isinstance(e, KeyError) else e)}, 400)
            except (RuntimeError, FutureTimeout) as e:
                self._json({"error": str(e) or "the emulator did not answer in time"}, 503)

        def do_GET(self) -> None:
            self._guard(self._get)

        def do_POST(self) -> None:
            def post():
                if self.headers.get("X-Lab") != "1":
                    raise ApiError(403, "missing X-Lab header")
                n = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(n) or b"{}")
                except json.JSONDecodeError as e:
                    raise ApiError(400, f"invalid JSON body: {e}") from e
                if not isinstance(body, dict):
                    raise ApiError(400, "body must be a JSON object")
                self._post(urlparse(self.path).path, body)

            self._guard(post)

        # ---- GET ------------------------------------------------------------------------------
        def _get(self) -> None:
            url = urlparse(self.path)
            path, query = url.path, parse_qs(url.query)
            if path in ("/", "/index.html"):
                path = "/index.html"
            if path.startswith("/api/") or path == "/screen.png":
                return self._api_get(path, query)
            f = (WEB / path.lstrip("/")).resolve()
            if WEB.resolve() not in f.parents or not f.is_file():
                raise ApiError(404, "not found")
            self._send(200, f.read_bytes(), TYPES.get(f.suffix, "application/octet-stream"))

        def _api_get(self, path: str, query: dict) -> None:
            if path == "/api/state":
                return self._json({
                    "tables": describe(m), "status": m.call(m.status), "replays": replay_names(m),
                    "replay_dir": str(m.replay_dir), "rom": m.rom.name,
                })
            if path == "/api/values":
                return self._json({"values": m.call(m.values), "status": m.call(m.status), "replays": replay_names(m)})
            if path == "/api/presses":
                after = int(query.get("after", ["0"])[0])

                def grab():
                    ps = [
                        {k: v for k, v in p.items() if k in ("seq", "f", "buttons", "grade", "frames", "windows")}
                        for p in m.presses if p["seq"] > after
                    ]
                    return {"presses": ps, "windows": m.windows(), "frame": m.frame, "seq": m.seq}

                return self._json(m.call(grab))
            if path == "/screen.png":
                return self._send(200, m.call(m.screen_png), "image/png")
            raise ApiError(404, "unknown endpoint")

        # ---- POST -----------------------------------------------------------------------------
        def _post(self, path: str, body: dict) -> None:
            if path == "/api/set":
                if not isinstance(body.get("value"), int) or isinstance(body.get("value"), bool):
                    raise ApiError(400, "value must be an integer")
                return self._json({"value": m.call(lambda: m.set_value(str(body.get("id")), body["value"]))})
            if path == "/api/reset":
                return self._json({"changed": m.call(lambda: m.reset(body.get("table")))})
            if path == "/api/save":
                return self._json({"saved": m.call(lambda: m.save(body.get("table")))})
            if path == "/api/restart":
                return self._json({"ok": m.call(m.restart) or True})
            if path == "/api/input":
                held = body.get("held", [])
                if not isinstance(held, list):
                    raise ApiError(400, "held must be a list of button names")
                return self._json({"ok": m.call(lambda: m.set_virtual(held)) or True})
            if path == "/api/record":
                action = body.get("action")
                if action == "start":
                    m.call(m.start_recording)
                    return self._json({"ok": True})
                if action == "stop":
                    name = name_arg(body)
                    p = m.call(lambda: m.stop_recording(name))
                    return self._json({"saved": str(p), "replays": replay_names(m)})
                raise ApiError(400, "action must be 'start' or 'stop'")
            if path == "/api/replay":
                if body.get("action") == "cancel":
                    return self._json({"ok": m.call(m.stop_replay) or True})
                name = name_arg(body)
                return self._json({"ok": m.call(lambda: m.start_replay(name)) or True})
            if path == "/api/replay/check":
                return self._json(check_headless(m, name_arg(body)))
            raise ApiError(404, "unknown endpoint")

    return Handler


def check_headless(m: Machine, name: str) -> dict:
    """Replay `name` at full speed in a separate headless process and report whether it matches."""
    f = m.replay_dir / f"{name}.json"
    if not f.is_file():
        raise ApiError(404, f"no replay '{name}' in {m.replay_dir}")
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    r = subprocess.run(
        [sys.executable, "-m", "lab", "replay", str(f), "--rom", str(m.rom), "--check"],
        capture_output=True, text=True, env=env, timeout=300,
    )
    return {"ok": r.returncode == 0, "output": (r.stdout + r.stderr).strip()}


def serve(m: Machine, port: int, repo: Path) -> tuple[ThreadingHTTPServer, int]:
    """Start the server on the first free port at or after `port`. Returns it and the port."""
    last = None
    for p in range(port, port + 20):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", p), make_handler(m, p, repo))
        except OSError as e:
            last = e
            continue
        srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True, name="lab-http").start()
        return srv, p
    raise SystemExit(f"lab: no free port in {port}..{port + 19} ({last}); pass --port")
