"""HTTP fixture replies and text WebSocket manipulation through mitmproxy."""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit
from mitmproxy import ctx, http
from scout_mobile.sandbox import validate


class SandboxAddon:
    def __init__(self):
        self.scenario = validate(json.loads(Path(os.environ['SCOUT_SANDBOX_SCENARIO']).read_text()))
        self.output = Path(os.environ['SCOUT_SANDBOX_OUTPUT'])
        self.counts = {}
        self.tasks = set()
        self.started = time.monotonic()
        self.event_count = 0

    def running(self):
        (self.output / '.sandbox-ready').touch()

    def event(self, rule_id, action, **details):
        if self.event_count >= 5000:
            return
        self.event_count += 1
        # No observed URLs, headers, cookies, query strings, or payload content.
        with (self.output / '.sandbox-events.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps({'elapsed_ms': round((time.monotonic()-self.started)*1000), 'rule_id': rule_id, 'action': action, **details}) + '\n')

    def rule(self, flow, rules, method=False):
        path = urlsplit(flow.request.path).path
        return next((r for r in rules if r['host'] == flow.request.host.lower() and r['path'] == path and (not method or r['method'] == flow.request.method)), None)

    async def request(self, flow: http.HTTPFlow):
        if flow.request.host.lower() not in self.scenario['hosts']:
            return
        ws = self.rule(flow, self.scenario['websocket']) if flow.request.headers.get('upgrade', '').lower() == 'websocket' else None
        if ws:
            flow.metadata['jev_ws_rule'] = ws
            return  # The upstream must complete the real WebSocket handshake.
        rule = self.rule(flow, self.scenario['http'], True)
        if not rule:
            if self.scenario['unmatched'] == 'block':
                flow.response = http.Response.make(502, b'{"error":"No sandbox rule matched"}', {'Content-Type': 'application/json'})
                self.event('', 'unmatched_block')
            else:
                self.event('', 'passthrough')
            return
        position = self.counts.get(rule['id'], 0)
        self.counts[rule['id']] = position + 1
        if position >= len(rule['responses']) and rule['exhaustion'] == 'block':
            flow.response = http.Response.make(502, b'{"error":"Sandbox response sequence exhausted"}')
            self.event(rule['id'], 'exhausted')
            return
        reply = rule['responses'][min(position, len(rule['responses'])-1)]
        await asyncio.sleep(reply['delay_ms']/1000)
        flow.response = http.Response.make(reply['status'], reply['body'].encode(), reply['headers'])
        self.event(rule['id'], 'mock', status=reply['status'], response_index=min(position, len(rule['responses'])-1), delay_ms=reply['delay_ms'])

    def websocket_start(self, flow: http.HTTPFlow):
        rule = flow.metadata.get('jev_ws_rule')
        if not rule:
            return
        self.event(rule['id'], 'connected')
        async def push():
            opened = time.monotonic()
            for packet in sorted(rule['pushes'], key=lambda p: p['after_ms']):
                await asyncio.sleep(max(0, packet['after_ms']/1000 - (time.monotonic()-opened)))
                if flow.websocket is None or flow.websocket.timestamp_end is not None:
                    return
                try:
                    # to_client=True and is_text=True preserve server text-message framing.
                    ctx.master.commands.call('inject.websocket', flow, True, packet['body'].encode(), True)
                    self.event(rule['id'], 'push', direction='server')
                except Exception:
                    self.event(rule['id'], 'error')
                    return
        task = asyncio.create_task(push())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def websocket_message(self, flow: http.HTTPFlow):
        rule = flow.metadata.get('jev_ws_rule')
        if not rule or not flow.websocket:
            return
        message = flow.websocket.messages[-1]
        if message.injected or not message.is_text:
            return
        direction = 'client' if message.from_client else 'server'
        text = message.content.decode('utf-8', errors='replace')
        for frame in rule['frames']:
            if frame['direction'] == direction and frame['contains'] in text:
                if frame['action'] == 'drop':
                    message.drop()
                else:
                    message.content = frame['body'].encode()
                self.event(rule['id'], frame['action'], direction=direction)
                return

    def error(self, flow: http.HTTPFlow):
        if flow.request.host.lower() in self.scenario['hosts']:
            rule = flow.metadata.get('jev_ws_rule') or self.rule(flow, self.scenario['http'], True)
            self.event(rule['id'] if rule else '', 'error')

    def done(self):
        for task in self.tasks:
            task.cancel()


addons = [SandboxAddon()]
