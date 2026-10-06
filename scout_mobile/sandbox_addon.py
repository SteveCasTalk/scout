"""HTTP fixture replies and text WebSocket manipulation through mitmproxy."""
from __future__ import annotations
import asyncio
import json
import os
import hashlib
import hmac
import secrets
from pathlib import Path
import time
from urllib.parse import urlsplit
from mitmproxy import ctx, http
from scout_mobile.sandbox import validate
from scout_mobile.network_contract import matches, assert_structure, MISSING


class SandboxAddon:
    def __init__(self):
        self.scenario = validate(json.loads(Path(os.environ['SCOUT_SANDBOX_SCENARIO']).read_text()))
        self.output = Path(os.environ['SCOUT_SANDBOX_OUTPUT'])
        self.counts = {}
        self.tasks = set()
        self.started = time.monotonic()
        self.clock_source='proxy_monotonic'
        if self.scenario['schema_version']==2 and os.environ.get('SCOUT_RUN_MONOTONIC_ORIGIN'):
            origin=float(os.environ['SCOUT_RUN_MONOTONIC_ORIGIN'])
            if __import__('math').isfinite(origin) and 0<=time.monotonic()-origin<=3600:self.started=origin;self.clock_source='run_monotonic'
        self.event_count = 0
        self.salt=secrets.token_bytes(32)
        self.signal_times={}
        self.signals={}
        self.advances={}
        self.assertion_history={}
        self.flow_tasks={}

    def running(self):
        (self.output / '.sandbox-ready').touch()

    def event(self, rule_id, action, **details):
        if self.event_count >= 5000:
            return
        self.event_count += 1
        if self.scenario['schema_version']==2:details['clock_source']=self.clock_source
        # No observed URLs, headers, cookies, query strings, or payload content.
        with (self.output / '.sandbox-events.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps({'elapsed_ms': round((time.monotonic()-self.started)*1000), 'rule_id': rule_id, 'action': action, **details}) + '\n')

    def rule(self, flow, rules, method=False):
        if self.scenario['schema_version']==1:
            path=urlsplit(flow.request.path).path
            return next((r for r in rules if r['host']==flow.request.host.lower() and r['path']==path and (not method or r['method']==flow.request.method)),None)
        candidates=[(r,matches(r,flow.request)) for r in rules]
        candidates=[(r,v) for r,v in candidates if v is not None]
        if len(candidates)>1:raise ValueError('Ambiguous contract matches.')
        if not candidates:return None
        rule,view=candidates[0]
        flow.metadata['scout_request_view']=view
        correlation=rule.get('correlation');token='global'
        if correlation:
            value=view.get(correlation['source'],correlation['key'])
            if value is MISSING:raise ValueError('Required session correlation missing.')
            token=hmac.new(self.salt,json.dumps(value,sort_keys=True).encode(),hashlib.sha256).hexdigest()
        flow.metadata['scout_correlation']=token
        return rule

    def emit(self,name,token):
        key=(name,token)
        self.signal_times[key]=time.monotonic()
        self.advances[key]=self.advances.get(key,0)+1
        self.signals.setdefault(key,asyncio.Event()).set()

    async def request(self, flow: http.HTTPFlow):
        if flow.request.host.lower() not in self.scenario['hosts']:
            return
        if self.event_count>=5000:
            flow.response=http.Response.make(502,b'{"error":"Sandbox evidence limit reached"}');return
        try:
            ws = self.rule(flow, self.scenario['websocket']) if flow.request.headers.get('upgrade', '').lower() == 'websocket' else None
            rule = None if ws else self.rule(flow, self.scenario['http'], True)
        except ValueError:
            flow.response = http.Response.make(502,b'{"error":"Ambiguous match or missing correlation"}')
            self.event('', 'error')
            return
        if ws:
            flow.metadata['jev_ws_rule'] = ws
            return  # The upstream must complete the real WebSocket handshake.
        if not rule:
            if self.scenario['unmatched'] == 'block':
                flow.response = http.Response.make(502, b'{"error":"No sandbox rule matched"}', {'Content-Type': 'application/json'})
                self.event('', 'unmatched_block')
            else:
                self.event('', 'passthrough')
            return
        token=flow.metadata.get('scout_correlation','global')
        count_key=(rule['id'],token) if self.scenario['schema_version']==2 else rule['id']
        position=self.advances.get((rule['advance_on'],token),0) if rule.get('advance_on') else self.counts.get(count_key,0)
        self.counts[count_key]=self.counts.get(count_key,0)+1
        if rule.get('assertions'):
            for result in assert_structure(rule,flow.metadata['scout_request_view'],self.assertion_history.setdefault(count_key,{})):
                self.event(rule['id'],'request_assertion',assertion=result)
        if position >= len(rule['responses']) and rule['exhaustion'] == 'block':
            flow.response = http.Response.make(502, b'{"error":"Sandbox response sequence exhausted"}')
            self.event(rule['id'], 'exhausted')
            return
        reply = rule['responses'][min(position, len(rule['responses'])-1)]
        await asyncio.sleep(reply['delay_ms']/1000)
        flow.response = http.Response.make(reply['status'], reply['body'].encode(), reply['headers'])
        self.event(rule['id'], 'mock', status=reply['status'], response_index=min(position, len(rule['responses'])-1), delay_ms=reply['delay_ms'])
        if rule.get('emit_event'):self.emit(rule['emit_event'],token)

    def websocket_start(self, flow: http.HTTPFlow):
        rule = flow.metadata.get('jev_ws_rule')
        if not rule:
            return
        self.event(rule['id'], 'connected')
        opened=time.monotonic()
        token=flow.metadata.get('scout_correlation','global')
        async def push(packet):
            origin=opened
            if packet.get('trigger_event'):
                key=(packet['trigger_event'],token)
                signal=self.signals.setdefault(key,asyncio.Event())
                try:await asyncio.wait_for(signal.wait(),600)
                except asyncio.TimeoutError:self.event(rule['id'],'error');return
                origin=self.signal_times[key]
            await asyncio.sleep(max(0,origin+packet['after_ms']/1000-time.monotonic()))
            if flow.websocket is None or flow.websocket.timestamp_end is not None:return
            try:
                ctx.master.commands.call('inject.websocket',flow,True,packet['body'].encode(),True)
                self.event(rule['id'],'push',direction='server')
            except Exception:self.event(rule['id'],'error')
        for packet in rule['pushes']:
            task=asyncio.create_task(push(packet));self.tasks.add(task)
            self.flow_tasks.setdefault(id(flow),set()).add(task)
            task.add_done_callback(self.tasks.discard)

    def websocket_end(self,flow):
        tasks=self.flow_tasks.pop(id(flow),set())
        if self.scenario['schema_version']==2 and any(not t.done() for t in tasks):
            rule=flow.metadata.get('jev_ws_rule')
            if rule:self.event(rule['id'],'error')
        for task in tasks:task.cancel()

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
            try:rule = flow.metadata.get('jev_ws_rule') or self.rule(flow, self.scenario['http'], True)
            except ValueError:rule=None
            self.event(rule['id'] if rule else '', 'error')

    def done(self):
        for task in self.tasks:
            task.cancel()


addons = [SandboxAddon()]
