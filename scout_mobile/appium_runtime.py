"""Start the installed local Appium server on demand; never install at run time."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from threading import Lock
from urllib.request import urlopen
from urllib.parse import urlsplit

from .config import ROOT
from .device import DeviceError

_LOCK = Lock()
_PROCESS = None


def _ready(url: str) -> bool:
    try:
        with urlopen(url.rstrip('/') + '/status', timeout=1) as response:
            value = json.loads(response.read(16384)).get('value', {})
        return value.get('ready') is True and bool(value.get('build', {}).get('version'))
    except (OSError, ValueError, AttributeError):
        return False


def _environment() -> dict[str, str]:
    env = os.environ.copy()
    env['APPIUM_HOME'] = str(ROOT / 'tooling/appium/.appium')
    if not env.get('ANDROID_HOME'):
        sdk = env.get('ANDROID_SDK_ROOT')
        if not sdk:
            candidate = Path.home() / ('Library/Android/sdk' if sys.platform == 'darwin' else 'Android/Sdk')
            if candidate.is_dir():sdk = str(candidate)
        if sdk:env['ANDROID_HOME'] = sdk
    if not env.get('JAVA_HOME') and sys.platform == 'darwin':
        try:
            found = subprocess.run(['/usr/libexec/java_home'], capture_output=True, text=True, timeout=5)
            if found.returncode == 0:env['JAVA_HOME'] = found.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    return env


def ensure_appium(url: str) -> None:
    """Reuse a healthy server; auto-start only our default local endpoint."""
    global _PROCESS
    if _ready(url):return
    parsed = urlsplit(url)
    if parsed.scheme != 'http' or parsed.hostname not in {'localhost', '127.0.0.1'} or (parsed.port or 80) != 4723 or parsed.path not in {'', '/'}:
        raise DeviceError('The configured Appium server is unavailable. Start it, or use http://127.0.0.1:4723 for automatic startup.')
    with _LOCK:
        if _ready(url):return
        with socket.socket() as probe:
            probe.settimeout(.3)
            occupied = probe.connect_ex(('127.0.0.1', 4723)) == 0
        if occupied:
            raise DeviceError('Port 4723 is occupied but Appium is not ready. Check the server before running.')
        entrypoint = ROOT / 'tooling/appium/node_modules/appium/index.js'
        if not entrypoint.is_file():
            raise DeviceError('Appium server is missing. Follow docs/appium-trial.md to install them once.')
        node = shutil.which('node')
        if not node:raise DeviceError('Node.js is missing from PATH; it is required to start Appium.')
        log_dir = ROOT / 'runner-output'
        log_dir.mkdir(parents=True, exist_ok=True)
        try:
            with (log_dir / 'appium-server.log').open('ab') as log:
                _PROCESS = subprocess.Popen([node, str(entrypoint), '--address', '127.0.0.1', '--port', '4723', '--log-level', 'warn'], cwd=ROOT, env=_environment(), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as exc:
            raise DeviceError(f'Could not start local Appium ({type(exc).__name__}).') from None
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if _ready(url):return
            if _PROCESS.poll() is not None:break
            time.sleep(.2)
        raise DeviceError('Appium did not become ready. See runner-output/appium-server.log and run the appropriate Appium driver doctor.')
