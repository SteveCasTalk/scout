"""Validated local fixture library and per-run mitmproxy lifecycle.

No device network settings are changed here. Evidence contains rule IDs and
counts, never captured request bodies, headers, query strings, or WS payloads.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import threading
import time

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal
from .config import ROOT,getenv

STORE = ROOT / '.scout-sandbox'
ID = r'^[A-Za-z0-9_-]{1,60}$'


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Reply(Strict):
    status: int = Field(default=200, ge=200, le=599)
    body: str = Field(default='{}', max_length=64000)
    headers: dict[str, str] = Field(default_factory=lambda: {'Content-Type': 'application/json'})
    delay_ms: int = Field(default=0, ge=0, le=30000)

    @model_validator(mode='after')
    def safe_headers(self):
        if len(self.headers) > 20:
            raise ValueError('At most 20 response headers are supported.')
        for key, value in self.headers.items():
            if not re.fullmatch(r'[A-Za-z0-9-]{1,80}', key) or len(value) > 1000 or '\r' in value or '\n' in value:
                raise ValueError('Invalid response header.')
            if key.lower() in {'content-length', 'transfer-encoding', 'connection', 'content-encoding'}:
                raise ValueError('Transport headers are managed by the proxy.')
        return self


class HttpRule(Strict):
    id: str = Field(pattern=ID)
    host: str = Field(min_length=1, max_length=253)
    path: str = Field(pattern=r'^/[^?#\r\n]*$', max_length=500)
    method: Literal['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'] = 'GET'
    responses: list[Reply] = Field(min_length=1, max_length=20)
    exhaustion: Literal['repeat_last', 'block'] = 'repeat_last'
    required_hits: int = Field(default=1, ge=0, le=100)


class WsFrame(Strict):
    direction: Literal['client', 'server'] = 'server'
    contains: str = Field(default='', max_length=1000)
    action: Literal['replace', 'drop'] = 'replace'
    body: str = Field(default='{}', max_length=64000)


class WsPush(Strict):
    after_ms: int = Field(default=0, ge=0, le=60000)
    body: str = Field(default='{}', max_length=64000)


class WsRule(Strict):
    id: str = Field(pattern=ID)
    host: str = Field(min_length=1, max_length=253)
    path: str = Field(pattern=r'^/[^?#\r\n]*$', max_length=500)
    frames: list[WsFrame] = Field(default_factory=list, max_length=20)
    pushes: list[WsPush] = Field(default_factory=list, max_length=20)
    required_hits: int = Field(default=1, ge=0, le=100)


class Scenario(Strict):
    schema_version: Literal[1] = 1
    id: str = Field(pattern=ID)
    name: str = Field(min_length=1, max_length=120)
    project: str = Field(min_length=1, max_length=100)
    description: str = Field(default='', max_length=2000)
    hosts: list[str] = Field(min_length=1, max_length=20)
    unmatched: Literal['block', 'passthrough'] = 'block'
    http: list[HttpRule] = Field(default_factory=list, max_length=40)
    websocket: list[WsRule] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def consistent(self):
        if not self.http and not self.websocket:
            raise ValueError('Add at least one HTTP or WebSocket rule.')
        if not any(rule.required_hits for rule in [*self.http, *self.websocket]):
            raise ValueError('At least one rule must require a hit to prove routing.')
        if len(set(self.hosts)) != len(self.hosts):
            raise ValueError('Hosts must be unique.')
        for host in self.hosts:
            if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?', host) or '..' in host:
                raise ValueError('Use exact lowercase hostnames without URLs, ports, or wildcards.')
        rules = [*self.http, *self.websocket]
        if len({r.id for r in rules}) != len(rules):
            raise ValueError('Rule IDs must be unique across HTTP and WebSocket rules.')
        seen = set()
        for rule in rules:
            if rule.host not in self.hosts:
                raise ValueError('Every rule host must be included in hosts.')
            key = (type(rule).__name__, rule.host, rule.path, getattr(rule, 'method', 'WS'))
            if key in seen:
                raise ValueError('Duplicate match rules are ambiguous.')
            seen.add(key)
            if isinstance(rule, WsRule) and not rule.frames and not rule.pushes:
                raise ValueError('A WebSocket rule needs a frame action or server push.')
        return self


def validate(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ValueError('Sandbox scenario must be a JSON object.')
    if len(json.dumps(value).encode()) > 400_000:
        raise ValueError('Sandbox scenario exceeds 400 KB.')
    return Scenario.model_validate(value).model_dump()


def fingerprint(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def list_scenarios() -> list[dict]:
    if not STORE.is_dir():
        return []
    return [validate(json.loads(p.read_text())) for p in sorted(STORE.glob('*.json'))]


def save_scenario(value: dict) -> dict:
    value = validate(value)
    STORE.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = STORE / (value['id'] + '.json')
    # Unique temp name also allows two MCP clients to save without partial reads.
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', dir=STORE, delete=False, encoding='utf-8') as f:
        json.dump(value, f, indent=2, ensure_ascii=False)
        temporary = Path(f.name)
    temporary.replace(path)
    return value


def diagnose() -> dict:
    import importlib.util
    installed = importlib.util.find_spec('mitmproxy') is not None
    host = getenv('SCOUT_SANDBOX_HOST', '127.0.0.1')
    port = int(getenv('SCOUT_SANDBOX_PORT', '8899'))
    try:
        ipaddress.ip_address(host)
        if not 1024 <= port <= 65535:
            raise ValueError()
    except ValueError:
        raise ValueError('Sandbox host must be a local IP address and port must be 1024–65535.')
    return {'installed': installed, 'listen_host': host, 'port': port,
            'install_command': 'uv pip install --python .venv/bin/python -e ".[sandbox]"',
            'certificate_directory': str(STORE / 'certificates'),
            'setup': ['Route the test app through this HTTP proxy before running.',
                      'HTTPS/WSS requires this proxy CA trusted by the test app. Pinned apps need a debug build that allows the test CA.',
                      'Physical devices need an explicitly configured reachable SCOUT_SANDBOX_HOST on the same test network; the default is loopback only.',
                      'WebSocket rules modify an established upstream connection; they require a successful real handshake. Binary frames are passed unchanged.',
                      'Only listed hosts are intercepted. Other hosts pass through unchanged. Replay evidence saves hit counts; explicit recordings save sanitized JSON responses locally.']}


CERTIFICATE_LOCK = threading.Lock()


def prepare_certificate() -> dict:
    if not diagnose()['installed']:
        raise ValueError('Install the sandbox extra first: uv pip install --python .venv/bin/python -e \".[sandbox]\"')
    from mitmproxy.certs import CertStore
    directory = STORE / 'certificates'
    with CERTIFICATE_LOCK:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        CertStore.from_store(str(directory), 'mitmproxy', 2048)
    return {'public_certificate': str(directory / 'mitmproxy-ca-cert.pem'), 'device_trust_configured': False,
            'next_step': 'Configure proxy routing and trust the public test CA on your dedicated test device. Keep the private key local.'}


class Session:
    def __init__(self, scenario: dict, output: Path, recording: bool = False):
        self.recording = recording
        if recording:
            from .sandbox_recording import CaptureOptions
            self.scenario = CaptureOptions.model_validate(scenario).model_dump()
        else:
            self.scenario = validate(scenario)
        self.output = output
        self.process = None
        self._lock = None
        self.started = time.monotonic()
        self.failed = False
        self.stopped = False

    def start(self) -> None:
        config = diagnose()
        if not config['installed']:
            raise ValueError('Sandbox requires mitmproxy. Install the sandbox extra using Settings → Sandbox setup.')
        STORE.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Advisory OS lock prevents overlapping MCP and dashboard proxy sessions.
        self._lock = (STORE / 'session.lock').open('a')
        try:
            try:
                if os.name == 'nt':
                    import msvcrt
                    self._lock.seek(0)
                    self._lock.write('0')
                    self._lock.flush()
                    self._lock.seek(0)
                    msvcrt.locking(self._lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise ValueError('Another recording or sandbox replay owns the proxy. Stop it before starting a new session.') from None
            family = socket.AF_INET6 if ipaddress.ip_address(config['listen_host']).version == 6 else socket.AF_INET
            with socket.socket(family) as probe:
                probe.bind((config['listen_host'], config['port']))
            snapshot = self.output / '.sandbox-scenario.json'
            snapshot.write_text(json.dumps(self.scenario), encoding='utf-8')
            snapshot.chmod(0o600)
            env = os.environ.copy()
            env['SCOUT_SANDBOX_SCENARIO'] = str(snapshot)
            env['SCOUT_SANDBOX_OUTPUT'] = str(self.output)
            env['SCOUT_SANDBOX_PARENT_PID'] = str(os.getpid())
            env['SCOUT_SANDBOX_MODE'] = 'record' if self.recording else 'replay'
            env['PYTHONPATH'] = str(ROOT) + os.pathsep + env.get('PYTHONPATH', '')
            command = [sys.executable, '-m', 'scout_mobile.sandbox_worker', '--listen-host', config['listen_host'], '--listen-port', str(config['port']), '-q', '--set', 'flow_detail=0', '--set', 'termlog_verbosity=error', '--set', 'connection_strategy=lazy', '--set', 'upstream_cert=false', '--set', 'confdir=' + str(STORE / 'certificates')]
            hosts = '|'.join(re.escape(host) for host in self.scenario['hosts'])
            command.extend(['--set', 'allow_hosts=^(?:' + hosts + r')(:\d+)?$'])
            if self.recording:
                command.extend(['--set', 'stream_large_bodies=64k'])
            self.process = subprocess.Popen(command, env=env, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise ValueError('Sandbox proxy could not start. Check the sandbox dependency version and listen address.')
                if (self.output / '.sandbox-ready').is_file():
                    return
                time.sleep(0.1)
            raise ValueError('Sandbox proxy did not become ready.')
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        if not self.stopped and self.process and self.process.poll() is not None:
            self.failed = True
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.stopped = True
        if self._lock:
            self._lock.close()
            self._lock = None
        for name in ('.sandbox-scenario.json', '.sandbox-ready'):
            (self.output / name).unlink(missing_ok=True)

    def report(self) -> dict:
        events = []
        path = self.output / '.sandbox-events.jsonl'
        if path.is_file():
            for line in path.read_text(encoding='utf-8').splitlines()[:5000]:
                try:
                    events.append(json.loads(line))
                except ValueError:
                    pass
        counts = {}
        for event in events:
            if event.get('action') in {'mock', 'replace', 'drop', 'push'}:
                counts[event['rule_id']] = counts.get(event['rule_id'], 0) + 1
        requirements = [{'id': r['id'], 'required_hits': r['required_hits'], 'actual_hits': counts.get(r['id'], 0)} for r in [*self.scenario['http'], *self.scenario['websocket']]]
        missing = [r['id'] for r in requirements if r['actual_hits'] < r['required_hits']]
        blocked = sum(e.get('action') in {'unmatched_block', 'exhausted', 'error'} for e in events)
        report = {'scenario_id': self.scenario['id'], 'name': self.scenario['name'], 'fingerprint': fingerprint(self.scenario), 'requirements': requirements, 'missing_rules': missing, 'blocked_events': blocked, 'proxy_failed': self.failed, 'status': 'inconclusive' if self.failed or missing or blocked or len(events) >= 5000 else 'satisfied', 'events': events, 'payloads_recorded': False}
        (self.output / 'sandbox.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        return report
