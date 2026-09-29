"""Loopback-only HTTP bridge between the local dashboard and Jev's ADB runner."""
from __future__ import annotations

from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import threading
from urllib.parse import parse_qs, unquote, urlsplit

from .agent import Agent, RunConfig
from .config import ROOT, load_local_env
from .device import AndroidDevice


load_local_env()
HOST = "127.0.0.1"
PORT = int(os.getenv("JEV_LOCAL_RUNNER_PORT", "8765"))
PACKAGE = os.getenv("JEV_APP_PACKAGE", "com.wallet.walkthedog.uat")
ALLOWED_ORIGINS = {"http://localhost:5173", "http://127.0.0.1:5173"}
MAX_BODY = 1_000_000
RUN_LOCK = threading.Lock()
CASE_FIELDS = ("id", "revision", "goal", "steps", "expected")


class Handler(BaseHTTPRequestHandler):
    server_version = "JevLocalRunner/1.0"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _headers(self, status: int, content_type: str = "application/json", length: int = 0) -> None:
        origin = self.headers.get("Origin", "")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if _allowed_origin(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _json(self, status: int, value: object) -> None:
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self._headers(status, length=len(data))
        self.wfile.write(data)

    def _browser_request_allowed(self) -> bool:
        return _allowed_origin(self.headers.get("Origin", "")) and self.headers.get("Host", "").split(":", 1)[0] in {"localhost", "127.0.0.1"}

    def do_OPTIONS(self) -> None:
        if not self._browser_request_allowed():
            self._json(403, {"error": "Origin is not allowed."})
            return
        self._headers(204, length=0)

    def do_GET(self) -> None:
        if not self._browser_request_allowed():
            self._json(403, {"error": "Origin is not allowed."})
            return
        parsed = urlsplit(self.path)
        if parsed.path == "/health":
            self._json(200, {"status": "ready"})
            return
        if parsed.path == "/devices":
            try:
                adb = os.getenv("ADB_PATH") or "adb"
                self._json(200, {"devices": AndroidDevice.connected(adb)})
            except Exception as exc:
                self._json(503, {"error": f"Could not query Android devices: {type(exc).__name__}"})
            return
        if parsed.path == "/runs":
            root = ROOT / "runner-output"
            cursor = parse_qs(parsed.query).get("before", [""])[0]
            if cursor and not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", cursor):
                self._json(400, {"error": "Invalid run cursor."})
                return
            runs = []
            if root.is_dir():
                folders = sorted((path for path in root.iterdir() if path.is_dir() and (not cursor or path.name < cursor)), key=lambda path: path.name, reverse=True)
                for folder in folders:
                    result_path = folder / "result.json"
                    if not result_path.is_file():
                        continue
                    try:
                        result = json.loads(result_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        continue
                    if not isinstance(result, dict) or not str(result.get("case_id", "")).startswith("prompt-"):
                        continue
                    artifacts = sorted(path.name for path in folder.iterdir() if path.is_file() and (path.suffix in {".png", ".mp4"} or path.name in {"result.json", "trace.json", "jev-output.json", "run-verification.json"}))
                    runs.append({"run_id": folder.name, "result": result, "artifacts": artifacts})
            page = runs[:50]
            next_cursor = page[-1]["run_id"] if len(runs) > 50 else None
            self._json(200, {"runs": page, "next_cursor": next_cursor})
            return
        match = re.fullmatch(r"/runs/([A-Za-z0-9_-]{1,80})/artifacts/([^/]+)", parsed.path)
        if match:
            run_id, encoded_name = match.groups()
            name = unquote(encoded_name)
            if name not in {"result.json", "trace.json", "jev-output.json", "run-verification.json"} and not re.fullmatch(r"\d{3}\.png|screen-recording-\d+\.mp4", name):
                self._json(400, {"error": "Unsupported artifact."})
                return
            root = (ROOT / "runner-output").resolve()
            folder = (root / run_id).resolve()
            artifact = (folder / name).resolve()
            if folder.parent != root or artifact.parent != folder or not artifact.is_file():
                self._json(404, {"error": "Artifact not found."})
                return
            content_type = "image/png" if name.endswith(".png") else "video/mp4" if name.endswith(".mp4") else "application/json"
            try:
                data = artifact.read_bytes()
                self._headers(200, content_type, len(data))
                self.wfile.write(data)
            except OSError:
                self._json(500, {"error": "Could not read artifact."})
            return
        self._json(404, {"error": "Not found."})

    def do_POST(self) -> None:
        if not self._browser_request_allowed():
            self._json(403, {"error": "Origin is not allowed."})
            return
        if urlsplit(self.path).path != "/run":
            self._json(404, {"error": "Not found."})
            return
        if not RUN_LOCK.acquire(blocking=False):
            self._json(409, {"error": "Another Jev run is already active on this device runner."})
            return
        try:
            raw_length = self.headers.get("Content-Length", "")
            if not raw_length.isdigit() or int(raw_length) > MAX_BODY:
                self._json(413, {"error": "Request must contain at most 1 MB of JSON."})
                return
            try:
                payload = json.loads(self.rfile.read(int(raw_length)))
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._json(400, {"error": "Invalid JSON."})
                return
            if not isinstance(payload, dict):
                self._json(400, {"error": "Expected a JSON object."})
                return
            case = payload.get("case")
            if not isinstance(case, dict) or any(key not in case for key in CASE_FIELDS):
                self._json(400, {"error": "Test case is missing id, revision, goal, steps, or expected."})
                return
            package = str(payload.get("package") or PACKAGE)
            if not re.fullmatch(r"[A-Za-z0-9_.]{3,240}", package):
                self._json(400, {"error": "Invalid Android package name."})
                return
            serial = payload.get("serial")
            if serial is not None and not isinstance(serial, str):
                self._json(400, {"error": "serial must be a device serial string."})
                return
            max_steps = payload.get("max_steps", 40)
            if type(max_steps) is not int or not 1 <= max_steps <= 100:
                self._json(400, {"error": "max_steps must be between 1 and 100."})
                return

            adb = os.getenv("ADB_PATH") or "adb"
            devices = AndroidDevice.connected(adb)
            if serial:
                if serial not in devices:
                    self._json(400, {"error": f"Android device {serial} is not connected and authorized."})
                    return
                device_serial = serial
            elif len(devices) == 1:
                device_serial = devices[0]
            else:
                self._json(409, {"error": "Select one connected Android device.", "devices": devices})
                return

            output = ROOT / "runner-output" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            assertion = str(case.get("assertion_text", "")).strip()
            device = AndroidDevice(device_serial, adb)
            with device.screen_recording(output), device.suppress_credential_prompts(), device.suppress_notification_prompt(package):
                result = Agent(RunConfig(package, device_serial, case, output, adb, max_steps, 180, assertion)).run()
            artifacts = sorted(path.name for path in output.iterdir() if path.is_file() and (path.suffix in {".png", ".mp4"} or path.name in {"result.json", "trace.json", "jev-output.json"}))
            self._json(200, {"run_id": output.name, "result": result, "artifacts": artifacts})
        except Exception as exc:
            self._json(500, {"error": f"Jev runner failed: {type(exc).__name__}: {str(exc)[:300]}"})
        finally:
            RUN_LOCK.release()


def main() -> None:
    load_local_env()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Jev local runner listening at http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _allowed_origin(origin: str) -> bool:
    if origin in ALLOWED_ORIGINS:
        return True
    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except ValueError:
        return False
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}:
        return False
    if port is not None and 5173 <= port <= 5189:
        return True
    try:
        configured = urlsplit(os.getenv("JEV_DASHBOARD_URL", ""))
    except ValueError:
        return False
    return bool(configured.netloc and parsed.netloc == configured.netloc and configured.hostname in {"localhost", "127.0.0.1"})


if __name__ == "__main__":
    main()
