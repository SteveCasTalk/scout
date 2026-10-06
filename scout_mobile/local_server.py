"""Loopback-only bridge between the Scout dashboard and mobile runner."""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import threading
from urllib.parse import parse_qs, unquote, urlsplit

from .agent import Agent, RunConfig
from . import dashboard_jobs
from .evidence import inventory as evidence_inventory, allowed as evidence_allowed
from .config import ROOT, load_local_env, getenv
from .devices import connected
from .branding import PRODUCT_NAME
from .capabilities import capabilities, negotiate_case
from .execution_contract import check_support, validate_authorizations


load_local_env()
HOST = "127.0.0.1"
PORT = int(getenv("SCOUT_LOCAL_RUNNER_PORT", "8765"))
PACKAGE = getenv("SCOUT_APP_PACKAGE", "com.wallet.walkthedog.uat")
ALLOWED_ORIGINS = {"http://localhost:5173", "http://127.0.0.1:5173"}
MAX_BODY = 1_000_000
RUN_LOCK = threading.Lock()
CASE_FIELDS = ("id", "revision", "goal", "steps", "expected")


class Handler(BaseHTTPRequestHandler):
    server_version = "ScoutLocalRunner/1.0"

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
        job_match = re.fullmatch(r"/jobs/([A-Za-z0-9_-]{1,80})", parsed.path)
        if job_match:
            job = dashboard_jobs.snapshot(job_match.group(1))
            self._json(200 if job else 404, job or {"error": "Run session not found. The bridge may have restarted."})
            return
        if parsed.path == "/health":
            self._json(200, {"status": "ready", "capabilities": capabilities("Android",getenv("SCOUT_ANDROID_DRIVER") or "appium"), "run_lock_held": RUN_LOCK.locked()})
            return
        session_match = re.fullmatch(r'/library-sessions/([A-Za-z0-9_-]{1,80})',parsed.path)
        if session_match:
            try:
                from .library_sessions import SESSIONS
                value=SESSIONS.snapshot(session_match.group(1))
                self._json(200 if value else 404,value or {'error':'Saved-library session not found.'})
            except (ValueError,OSError) as exc:
                self._json(400,{'error':str(exc)[:300]})
            return
        if parsed.path == "/sandbox":
            try:
                from .sandbox import diagnose, list_scenarios
                self._json(200, {"diagnostics": diagnose(), "scenarios": list_scenarios()})
            except (ValueError, OSError) as exc:
                self._json(400, {"error": str(exc)[:300]})
            return
        recording_match = re.fullmatch(r"/sandbox/recordings/([A-Za-z0-9_-]{1,60})", parsed.path)
        if parsed.path == "/sandbox/recordings" or recording_match:
            try:
                from .sandbox_recording import MANAGER, list_recordings
                value = MANAGER.get(recording_match.group(1), parse_qs(parsed.query).get('bodies', ['1'])[0] != '0') if recording_match else {'recordings': list_recordings()}
                self._json(200, value)
            except (ValueError, OSError) as exc:
                self._json(400, {'error': str(exc)[:300]})
            return
        if parsed.path == "/devices":
            try:
                adb = getenv("ADB_PATH") or "adb"
                self._json(200, {"devices": connected(parse_qs(parsed.query).get("platform", ["Android"])[0], adb)})
            except Exception as exc:
                self._json(503, {"error": f"Could not query devices: {type(exc).__name__}"})
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
                    artifacts = [p.name for p in evidence_inventory(folder)]
                    runs.append({"run_id": folder.name, "result": result, "artifacts": artifacts})
            page = runs[:50]
            next_cursor = page[-1]["run_id"] if len(runs) > 50 else None
            self._json(200, {"runs": page, "next_cursor": next_cursor})
            return
        match = re.fullmatch(r"/runs/([A-Za-z0-9_-]{1,80})/artifacts/([^/]+)", parsed.path)
        if match:
            run_id, encoded_name = match.groups()
            name = unquote(encoded_name)
            if not evidence_allowed(ROOT/"runner-output"/run_id,name):
                self._json(400, {"error": "Unsupported artifact."})
                return
            root = (ROOT / "runner-output").resolve()
            folder = (root / run_id).resolve()
            artifact = (folder / name).resolve()
            if folder.parent != root or artifact.parent != folder or not artifact.is_file():
                self._json(404, {"error": "Artifact not found."})
                return
            content_type = __import__("mimetypes").guess_type(name)[0] or "application/octet-stream"
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
        path = urlsplit(self.path).path
        session_match=re.fullmatch(r'/library-sessions/([A-Za-z0-9_-]{1,80})/(input|stop)',path)
        if path=='/library-sessions' or session_match:
            try:
                length=self.headers.get('Content-Length','')
                if not length.isdigit() or int(length)>MAX_BODY:
                    raise ValueError('Request must contain at most 1 MB of JSON.')
                packet=json.loads(self.rfile.read(int(length)))
                if not isinstance(packet,dict):raise ValueError('Expected a JSON object.')
                from .library_sessions import SESSIONS
                value=SESSIONS.start(packet,RUN_LOCK) if not session_match else SESSIONS.respond(session_match.group(1),packet.get('text'),session_match.group(2)=='stop')
                self._json(202,value)
            except (ValueError,OSError,KeyError,TypeError) as exc:
                self._json(400,{'error':str(exc)[:300]})
            return
        recording_match = re.fullmatch(r"/sandbox/recordings/([A-Za-z0-9_-]{1,60})/(stop|draft)", path)
        if path == '/sandbox/recordings' or recording_match:
            try:
                length = self.headers.get('Content-Length', '')
                if not length.isdigit() or int(length) > MAX_BODY:
                    raise ValueError('Request must contain at most 1 MB of JSON.')
                packet = json.loads(self.rfile.read(int(length)))
                if not isinstance(packet, dict):
                    raise ValueError('Expected a JSON object.')
                from .sandbox_recording import MANAGER, draft
                if not recording_match:
                    value = MANAGER.start(packet)
                elif recording_match.group(2) == 'stop':
                    value = MANAGER.stop(recording_match.group(1))
                    if parse_qs(urlsplit(self.path).query).get('bodies', ['1'])[0] == '0':
                        value['records'] = [{key: item for key, item in record.items() if key != 'body'} for record in value['records']]
                else:
                    value = draft(recording_match.group(1), packet.get('capture_ids'), packet.get('scenario_id'), packet.get('name'))
                self._json(200, value)
            except (ValueError, OSError) as exc:
                self._json(400, {'error': str(exc)[:300]})
            return
        if path in {"/sandbox", "/sandbox/certificate"}:
            try:
                length = self.headers.get("Content-Length", "")
                if not length.isdigit() or int(length) > MAX_BODY:
                    raise ValueError("Request must contain at most 1 MB of JSON.")
                from .sandbox import save_scenario, prepare_certificate
                packet = json.loads(self.rfile.read(int(length)))
                self._json(200, prepare_certificate() if path.endswith("/certificate") else save_scenario(packet))
            except (ValueError, UnicodeDecodeError, OSError) as exc:
                self._json(400, {"error": str(exc)[:300]})
            return
        if path == "/compare-platforms":
            try:
                length = self.headers.get("Content-Length", "")
                if not length.isdigit() or int(length) > MAX_BODY:
                    raise ValueError("Request must contain at most 1 MB of JSON.")
                packet = json.loads(self.rfile.read(int(length)))
                from .platform_comparison import assess
                self._json(200, assess(packet))
            except (ValueError, UnicodeDecodeError) as exc:
                self._json(400, {"error": str(exc)[:300]})
            except Exception as exc:
                self._json(503, {"error": f"Could not assess platform comparison: {str(exc)[:200]}"})
            return
        if path == "/jobs" or re.fullmatch(r"/jobs/[A-Za-z0-9_-]{1,80}/(input|stop)", path):
            try:
                length = self.headers.get("Content-Length", "")
                if not length.isdigit() or int(length) > MAX_BODY:
                    raise ValueError("Request must contain at most 1 MB of JSON.")
                payload = json.loads(self.rfile.read(int(length)))
                if not isinstance(payload, dict):
                    raise ValueError("Expected a JSON object.")
                if path == "/jobs":
                    job_id = dashboard_jobs.start(payload, RUN_LOCK)
                    self._json(202, {"run_id": job_id})
                else:
                    dashboard_jobs.respond(path.split('/')[2], payload.get('text'), path.endswith('/stop'))
                    self._json(200, {"accepted": True})
            except (ValueError, UnicodeDecodeError) as exc:
                self._json(400, {"error": str(exc)[:300]})
            except Exception as exc:
                self._json(500, {"error": f"Could not start run: {type(exc).__name__}"})
            return
        if path != "/run":
            self._json(404, {"error": "Not found."})
            return
        if not RUN_LOCK.acquire(blocking=False):
            self._json(409, {"error": "Another Scout run is already active on this device runner."})
            return
        agent = None
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
            package = str(payload.get("package") or case.get("app_id") or (PACKAGE if case.get("platform", "Android") == "Android" else ""))
            if not re.fullmatch(r"[A-Za-z0-9_.]{3,240}", package):
                self._json(400, {"error": "Invalid app package or bundle ID."})
                return
            serial = payload.get("serial")
            if serial is not None and not isinstance(serial, str):
                self._json(400, {"error": "serial must be a device serial string."})
                return
            max_steps = payload.get("max_steps", 40)
            if type(max_steps) is not int or not 1 <= max_steps <= 100:
                self._json(400, {"error": "max_steps must be between 1 and 100."})
                return

            execution=check_support(case,case.get("platform","Android"),getenv("SCOUT_ANDROID_DRIVER") or "appium")
            negotiate_case(case,execution,payload.get("client_capabilities"))
            grants=validate_authorizations(payload.get("authorizations"),execution)
            adb = getenv("ADB_PATH") or "adb"
            devices = connected(case.get("platform", "Android"), adb)
            if serial:
                if serial not in devices:
                    self._json(400, {"error": f"Device {serial} is not connected and authorized."})
                    return
                device_serial = serial
            elif len(devices) == 1:
                device_serial = devices[0]
            else:
                self._json(409, {"error": "Select one connected device for this platform.", "devices": devices})
                return

            output = ROOT / "runner-output" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            assertion = str(case.get("assertion_text", "")).strip()
            agent = Agent(RunConfig(package, device_serial, case, output, adb, max_steps, 180, assertion,authorizations=grants))
            device = agent.device
            agent.lease.acquire();agent.lease_managed=True
            with device.screen_recording(output), device.suppress_credential_prompts(), (nullcontext() if execution and execution["lifecycle"]["notification_policy"]=="preserve" else device.suppress_notification_prompt(package)):
                result = agent.run()
            result = agent.finalize_evidence(result)
            artifacts = [p.name for p in evidence_inventory(output)]
            self._json(200, {"run_id": output.name, "result": result, "artifacts": artifacts})
        except Exception as exc:
            self._json(500, {"error": f"Scout runner failed: {type(exc).__name__}: {str(exc)[:300]}"})
        finally:
            try:
                if agent:
                    try:agent.device.close()
                    finally:agent.lease.release()
            finally:RUN_LOCK.release()


def main() -> None:
    load_local_env()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"{PRODUCT_NAME} local runner listening at http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        from .library_sessions import SESSIONS
        SESSIONS.stop_active()
        from .sandbox_recording import MANAGER
        MANAGER.stop_active()
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
        configured = urlsplit(getenv("SCOUT_DASHBOARD_URL", ""))
    except ValueError:
        return False
    return bool(configured.netloc and parsed.netloc == configured.netloc and configured.hostname in {"localhost", "127.0.0.1"})


if __name__ == "__main__":
    main()
