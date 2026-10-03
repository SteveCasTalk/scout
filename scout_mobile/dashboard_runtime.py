"""Start the local Scout dashboard on demand for prompt-run deep links."""
from __future__ import annotations

import os
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from threading import RLock
from urllib.error import URLError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

from .config import ROOT,getenv

DEFAULT_URL = "http://localhost:5173"
PORT_RANGE = range(5173, 5190)
_PROCESSES: dict[str, subprocess.Popen[bytes]] = {}
_LOCK = RLock()


def _dashboard_ready(port: int) -> bool:
    try:
        with urlopen(f"http://localhost:{port}/api/health", timeout=0.7) as response:
            data = json.loads(response.read(4096))
        return isinstance(data, dict) and data.get("service") == "scout-dashboard" and data.get("status") == "ready"
    except (OSError, URLError, TimeoutError, ValueError):
        return False


def _port_available(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.2)
        return probe.connect_ex(("127.0.0.1", port)) != 0


def _bridge_ready() -> bool:
    try:
        request = Request("http://127.0.0.1:8765/health", headers={"Origin": "http://127.0.0.1:5173"})
        with urlopen(request, timeout=0.7) as response:
            return response.status == 200 and b'"ready"' in response.read(256)
    except (OSError, URLError, TimeoutError):
        return False


def _start_process(key: str, command: list[str], cwd: Path, env: dict[str, str], log_path: Path) -> None:
    with _LOCK:
        process = _PROCESSES.get(key)
        if process and process.poll() is None:
            return
        log = log_path.open("ab")
        try:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                close_fds=True,
                start_new_session=True,
            )
        finally:
            log.close()
        _PROCESSES[key] = process


def ensure_dashboard() -> tuple[str, str | None]:
    """Return a reachable dashboard URL, starting its dev server if needed."""
    configured = getenv("SCOUT_DASHBOARD_URL", "").strip().rstrip("/")
    try:
        parsed = urlsplit(configured or DEFAULT_URL)
        preferred_port = parsed.port or 5173
    except ValueError:
        return DEFAULT_URL, "SCOUT_DASHBOARD_URL is malformed; using the default local dashboard address."
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}:
        return (configured or DEFAULT_URL), None

    # Start the bridge independently: dashboard sign-in/build readiness must not
    # prevent local runs from being available for sync.
    (ROOT / "runner-output").mkdir(parents=True, exist_ok=True)
    initial_bridge_error = _ensure_bridge()
    base_url = f"http://localhost:{preferred_port}"
    if _dashboard_ready(preferred_port):
        errors = []
        if not _bridge_ready():
            error = _ensure_bridge()
            if error:
                errors.append(error)
        return base_url, "; ".join(errors) or None

    for port in PORT_RANGE:
        if port != preferred_port and _dashboard_ready(port):
            bridge_error = _ensure_bridge()
            return f"http://localhost:{port}", bridge_error

    dashboard = ROOT / "dashboard"
    if not (dashboard / "node_modules").is_dir():
        return base_url, "Dashboard dependencies are missing; install them in the dashboard directory."
    npm = shutil.which("npm")
    if not npm:
        return base_url, "npm is not available on the Scout MCP server PATH."

    port = next((candidate for candidate in PORT_RANGE if _port_available(candidate)), None)
    if port is None:
        return base_url, "No free local dashboard port was found between 5173 and 5189."
    base_url = f"http://localhost:{port}"

    log_dir = ROOT / "runner-output"
    log_dir.mkdir(parents=True, exist_ok=True)
    try:
        env = os.environ.copy()
        env["SCOUT_DASHBOARD_PORT"] = str(port)
        _start_process(f"dashboard-{port}", [npm, "run", "dev", "--", "--host", "127.0.0.1", "--strictPort"], dashboard, env, log_dir / "scout-dashboard.log")
    except OSError as exc:
        return base_url, f"Could not start the dashboard: {type(exc).__name__}."

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if _dashboard_ready(port):
            bridge_error = _ensure_bridge()
            return base_url, bridge_error
        time.sleep(0.25)
    return base_url, "; ".join(filter(None, ["Dashboard server did not become ready; see runner-output/scout-dashboard.log.", initial_bridge_error]))


def _ensure_bridge() -> str | None:
    if _bridge_ready():
        return None
    if not _port_available(8765):
        return "The local Scout bridge port 8765 is occupied but did not answer its health check."
    try:
        _start_process("bridge", [sys.executable, "-m", "scout_mobile.local_server"], ROOT, os.environ.copy(), ROOT / "runner-output" / "scout-dashboard.log")
    except OSError as exc:
        return f"Could not start the local Scout bridge: {type(exc).__name__}."
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if _bridge_ready():
            return None
        time.sleep(0.25)
    return "The local Scout bridge did not become ready; see runner-output/scout-dashboard.log."
