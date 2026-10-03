"""Observe scoped JSON responses without modifying requests or responses."""
from __future__ import annotations
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit
from mitmproxy import http
from scout_mobile.sandbox_recording import CaptureOptions, MAX_BODY, MAX_RECORDS, sanitize, safe_path


class RecordingAddon:
    def __init__(self):
        self.options = CaptureOptions.model_validate(json.loads(Path(os.environ['SCOUT_SANDBOX_SCENARIO']).read_text())).model_dump()
        self.output = Path(os.environ['SCOUT_SANDBOX_OUTPUT'])
        self.started = time.monotonic()
        self.order = 0
        self.count = 0
        self.stats = {'captured': 0, 'skipped': 0, 'redacted_fields': 0, 'limit_reached': False, 'errors': 0}
        self.persist_stats()

    def persist_stats(self):
        temporary = self.output / '.stats.tmp'
        temporary.write_text(json.dumps(self.stats))
        temporary.replace(self.output / 'stats.json')

    def running(self):
        (self.output / '.sandbox-ready').touch()

    def scoped(self, flow):
        path = urlsplit(flow.request.path).path
        return (flow.request.host.lower() in self.options['hosts'] and safe_path(path)
                and (not self.options['paths'] or path in self.options['paths']))

    def skip(self):
        self.stats['skipped'] += 1
        self.persist_stats()

    def requestheaders(self, flow: http.HTTPFlow):
        if self.scoped(flow):
            self.order += 1
            flow.metadata['jev_capture_order'] = self.order

    def capture(self, metadata, content):
        if self.count >= MAX_RECORDS:
            self.stats['limit_reached'] = True
            self.persist_stats()
            return
        try:
            if content is None or len(content) > MAX_BODY:
                self.skip()
                return
            def invalid(_):
                raise ValueError('Non-finite JSON value')
            parsed = json.loads(content, parse_constant=invalid)
            cleaned, redactions = sanitize(parsed, self.options['redact_keys'])
            body = json.dumps(cleaned, ensure_ascii=False, indent=2, allow_nan=False)
            if len(body.encode()) > MAX_BODY:
                self.skip()
                return
        except (ValueError, UnicodeError, RecursionError, OverflowError):
            self.skip()
            return
        self.count += 1
        self.stats['captured'] = self.count
        self.stats['redacted_fields'] += redactions
        # Only sanitized response content reaches disk. No live request data or headers.
        with (self.output / 'responses.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps({**metadata, 'id': f'capture_{self.count}', 'body': body, 'redactions': redactions, 'elapsed_ms': round((time.monotonic()-self.started)*1000)}, ensure_ascii=False)+'\n')
        self.persist_stats()

    def response(self, flow: http.HTTPFlow):
        if not self.scoped(flow) or not flow.response:
            return
        if flow.response.status_code == 101:
            return
        if 'json' not in flow.response.headers.get('Content-Type', '').lower():
            self.skip()
            return
        try:
            content = flow.response.content
        except ValueError:
            self.skip()
            return
        self.capture({'protocol': 'http', 'host': flow.request.host.lower(), 'path': urlsplit(flow.request.path).path,
                      'method': flow.request.method, 'status': flow.response.status_code,
                      'order': flow.metadata.get('jev_capture_order', self.order),
                      'delay_ms': max(0, round(((flow.response.timestamp_end or time.time())-flow.request.timestamp_start)*1000))}, content)

    def websocket_start(self, flow: http.HTTPFlow):
        if self.options['capture_websocket'] and self.scoped(flow):
            flow.metadata['jev_capture_ws_opened'] = time.monotonic()

    def websocket_message(self, flow: http.HTTPFlow):
        opened = flow.metadata.get('jev_capture_ws_opened')
        if opened is None or not flow.websocket:
            return
        message = flow.websocket.messages[-1]
        if message.from_client or message.injected:
            return
        if not message.is_text:
            self.skip()
            return
        self.order += 1
        self.capture({'protocol': 'websocket', 'host': flow.request.host.lower(), 'path': urlsplit(flow.request.path).path,
                      'connection': flow.id, 'order': self.order, 'after_ms': round((time.monotonic()-opened)*1000)}, message.content)

    def error(self, flow: http.HTTPFlow):
        if self.scoped(flow):
            self.stats['errors'] += 1
            self.persist_stats()


addons = [RecordingAddon()]
