"""Bounded, local response recording and conversion into editable fixtures."""
from __future__ import annotations
from .config import getenv

import atexit
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import threading
import uuid

from pydantic import Field, model_validator
from .sandbox import STORE, Strict, ID, validate

CAPTURES = STORE / 'captures'
MAX_RECORDS = 100
MAX_BODY = 64000
SENSITIVE_KEY = re.compile(r'password|passwd|secret|token|authorization|cookie|credential|session|otp|pin_code|api.?key|email|phone|mobile_number|address|birth|credit.?card|card.?number|cvv|account.?number|full.?name|display.?name|user.?name|first.?name|last.?name', re.I)
EMAIL = re.compile(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', re.I)
TOKEN = re.compile(r'\bBearer\s+\S+|\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b', re.I)
AUTH_PATH = re.compile(r'/(?:oauth|token|password|otp|credentials)(?:/|$)', re.I)


class CaptureOptions(Strict):
    project: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=120)
    hosts: list[str] = Field(min_length=1, max_length=20)
    paths: list[str] = Field(default_factory=list, max_length=20)
    capture_websocket: bool = True
    duration_seconds: int = Field(default=300, ge=30, le=900)
    redact_keys: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode='after')
    def scope(self):
        if len(set(self.hosts)) != len(self.hosts):
            raise ValueError('Hosts must be unique.')
        for host in self.hosts:
            if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?', host) or '..' in host:
                raise ValueError('Use exact lowercase hostnames without schemes, ports, or wildcards.')
        for path in self.paths:
            if len(path) > 500 or not re.fullmatch(r'/[^?#\r\n]*', path):
                raise ValueError('Paths must be exact URL paths, without query strings.')
        if any(not key or len(key) > 80 for key in self.redact_keys):
            raise ValueError('Additional redaction keys must contain 1–80 characters.')
        return self


def sanitize(value, extra_keys=()):
    """Scrub common keys/patterns before writing; return a type-preserving value."""
    secrets = [getenv(k, '') for k in ('SCOUT_TEST_EMAIL', 'SCOUT_TEST_PASSWORD')]
    extras = {key.lower() for key in extra_keys}
    count = 0

    def blank(item, depth=0):
        if depth > 40:
            raise ValueError('JSON nesting exceeds recording limit.')
        if isinstance(item, dict):
            return {safe_key(key, i): blank(child, depth+1) for i, (key, child) in enumerate(item.items())}
        if isinstance(item, list):
            return [blank(child, depth+1) for child in item]
        if isinstance(item, str):
            return '[REDACTED]'
        if isinstance(item, bool):
            return False
        if isinstance(item, (int, float)):
            return 0
        return None

    def unsafe(text):
        return bool(EMAIL.search(text) or TOKEN.search(text) or any(secret and secret in text for secret in secrets))

    def safe_key(key, index):
        nonlocal count
        if unsafe(key):
            count += 1
            return f'REDACTED_KEY_{index}'
        return key

    def walk(item, depth=0):
        nonlocal count
        if depth > 40:
            raise ValueError('JSON nesting exceeds recording limit.')
        if isinstance(item, dict):
            result = {}
            for i, (key, child) in enumerate(item.items()):
                if SENSITIVE_KEY.search(key) or key.lower() in extras:
                    count += 1
                    result[safe_key(key, i)] = blank(child, depth+1)
                else:
                    result[safe_key(key, i)] = walk(child, depth+1)
            return result
        if isinstance(item, list):
            return [walk(child, depth+1) for child in item]
        if isinstance(item, str) and unsafe(item):
            count += 1
            return '[REDACTED]'
        return item

    return walk(value), count


def safe_path(path: str) -> bool:
    from urllib.parse import unquote
    decoded = unquote(path)
    return (len(path) <= 500 and not EMAIL.search(decoded) and not TOKEN.search(decoded)
            and not AUTH_PATH.search(decoded)
            and not any(getenv(k) and getenv(k) in decoded for k in ('SCOUT_TEST_EMAIL', 'SCOUT_TEST_PASSWORD')))


def folder(recording_id: str) -> Path:
    if not re.fullmatch(ID, recording_id):
        raise ValueError('Invalid recording ID.')
    path = CAPTURES / recording_id
    if not path.is_dir():
        raise ValueError('Recording not found on this machine.')
    return path


def records(path: Path) -> list[dict]:
    items = []
    if (path / 'responses.jsonl').is_file():
        with (path / 'responses.jsonl').open(encoding='utf-8') as source:
            for line in source:
                if len(items) >= MAX_RECORDS:
                    break
                try:
                    items.append(json.loads(line))
                except ValueError:
                    continue  # A concurrent append is retried on the next poll.
    return sorted(items, key=lambda item: item['order'])


def details(recording_id: str, include_bodies=True) -> dict:
    path = folder(recording_id)
    metadata = json.loads((path / 'metadata.json').read_text())
    items = records(path)
    if not include_bodies:
        items = [{key: value for key, value in item.items() if key != 'body'} for item in items]
    stats = {}
    if (path / 'stats.json').is_file():
        try:
            stats = json.loads((path / 'stats.json').read_text())
        except ValueError:
            pass
    return {**metadata, 'records': items, 'record_count': len(items), 'stats': stats}


def list_recordings() -> list[dict]:
    result = []
    if CAPTURES.is_dir():
        for path in sorted(CAPTURES.iterdir(), reverse=True):
            if path.is_dir() and (path / 'metadata.json').is_file():
                try:
                    if MANAGER.owns(path.name):
                        value = MANAGER.get(path.name, False)
                        value.pop('records')
                    else:
                        value = json.loads((path / 'metadata.json').read_text())
                        value['stats'] = json.loads((path / 'stats.json').read_text()) if (path / 'stats.json').is_file() else {}
                        value['record_count'] = value['stats'].get('captured', 0)
                    # A stopped bridge cannot restore live process ownership.
                    if value['status'] in {'starting', 'recording'} and not MANAGER.owns(path.name):
                        value['status'] = 'interrupted'
                    result.append(value)
                except (OSError, ValueError, KeyError):
                    continue
                if len(result) >= 100:
                    break
    return result


def write_metadata(path, metadata):
    temporary = path / '.metadata.tmp'
    temporary.write_text(json.dumps(metadata), encoding='utf-8')
    temporary.replace(path / 'metadata.json')


class RecordingManager:
    """Owned by the local bridge; MCP tools use the bridge to share this state."""
    def __init__(self):
        self.lock = threading.RLock()
        self.session = None
        self.recording_id = None
        self.timer = None
        atexit.register(self.stop_active)

    def owns(self, recording_id):
        with self.lock:
            return self.recording_id == recording_id and self.session is not None

    def start(self, options):
        options = CaptureOptions.model_validate(options).model_dump()
        from .sandbox import Session
        with self.lock:
            if self.session and self.session.process.poll() is not None:
                self.stop(self.recording_id)
            if self.session:
                raise ValueError('Stop the active recording before starting another.')
            recording_id = datetime.now(timezone.utc).strftime('record-%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8]
            STORE.mkdir(parents=True, mode=0o700, exist_ok=True)
            CAPTURES.mkdir(mode=0o700, exist_ok=True)
            path = CAPTURES / recording_id
            path.mkdir(parents=True, mode=0o700)
            metadata = {'id': recording_id, 'options': options, 'status': 'starting', 'started_at': datetime.now(timezone.utc).isoformat(), 'response_bodies_redacted': True, 'request_data_recorded': False}
            write_metadata(path, metadata)
            session = Session(options, path, recording=True)
            try:
                session.start()
            except Exception:
                metadata['status'] = 'error'
                write_metadata(path, metadata)
                raise
            self.session, self.recording_id = session, recording_id
            metadata['status'] = 'recording'
            write_metadata(path, metadata)
            self.timer = threading.Timer(options['duration_seconds'], lambda: self.stop(recording_id))
            self.timer.daemon = True
            self.timer.start()
            return details(recording_id)

    def stop(self, recording_id):
        with self.lock:
            if self.recording_id == recording_id and self.session:
                self.session.stop()
                metadata_path = folder(recording_id) / 'metadata.json'
                metadata = json.loads(metadata_path.read_text())
                metadata.update(status='error' if self.session.failed else 'stopped', stopped_at=datetime.now(timezone.utc).isoformat())
                write_metadata(metadata_path.parent, metadata)
                if self.timer:
                    self.timer.cancel()
                self.session = self.recording_id = self.timer = None
            return self.get(recording_id)

    def stop_active(self):
        with self.lock:
            if self.recording_id:
                self.stop(self.recording_id)

    def get(self, recording_id, include_bodies=True):
        with self.lock:
            if self.owns(recording_id) and self.session.process.poll() is not None:
                self.stop(recording_id)
            value = details(recording_id, include_bodies)
            if value['status'] in {'starting', 'recording'} and not self.owns(recording_id):
                value['status'] = 'interrupted'
            return value


MANAGER = RecordingManager()


def draft(recording_id, capture_ids, scenario_id, name):
    recording = MANAGER.get(recording_id)
    if recording['status'] in {'recording', 'starting'}:
        raise ValueError('Stop recording before creating a fixture draft.')
    if not isinstance(capture_ids, list) or not 1 <= len(capture_ids) <= MAX_RECORDS or any(not isinstance(i, str) for i in capture_ids):
        raise ValueError('Select 1–100 captures.')
    if len(set(capture_ids)) != len(capture_ids):
        raise ValueError('Select each capture once.')
    selected = [r for r in recording['records'] if r['id'] in capture_ids]
    if len(selected) != len(capture_ids):
        raise ValueError('Some selected captures are missing.')
    http_rules, ws_rules = {}, {}
    for item in selected:
        key = (item['host'], item['path'], item.get('method', 'WS'))
        if item['protocol'] == 'http':
            if not 200 <= item['status'] <= 599:
                raise ValueError('Selected HTTP status is unsupported for replay.')
            rule = http_rules.setdefault(key, {'id': f'http_{len(http_rules)+1}', 'host': item['host'], 'path': item['path'], 'method': item['method'], 'responses': [], 'exhaustion': 'repeat_last', 'required_hits': 1})
            rule['responses'].append({'status': item['status'], 'body': item['body'], 'headers': {'Content-Type': 'application/json'}, 'delay_ms': min(item['delay_ms'], 30000)})
        else:
            if item['after_ms'] > 60000:
                raise ValueError('WebSocket replay supports the first 60 seconds of a connection. Select earlier frames or create a manual scenario.')
            if key in ws_rules and ws_rules[key]['connection'] != item['connection']:
                raise ValueError('Select frames from one WebSocket connection per endpoint.')
            rule = ws_rules.setdefault(key, {'id': f'ws_{len(ws_rules)+1}', 'host': item['host'], 'path': item['path'], 'frames': [{'direction': 'server', 'contains': '', 'action': 'drop', 'body': ''}], 'pushes': [], 'required_hits': 1, 'connection': item['connection']})
            rule['pushes'].append({'after_ms': item['after_ms'], 'body': item['body']})
    for rule in ws_rules.values():
        rule.pop('connection')
    return validate({'id': scenario_id, 'name': name, 'project': recording['options']['project'],
                     'description': 'Draft from redacted recording '+recording_id+'. Review placeholders and API compatibility before saving. HTTP delays are capped at 30s; WS replay drops upstream server text and injects selected frames after a real handshake.',
                     'hosts': sorted({r['host'] for r in selected}), 'unmatched': 'passthrough',
                     'http': list(http_rules.values()), 'websocket': list(ws_rules.values())})
