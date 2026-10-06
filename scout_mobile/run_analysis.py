"""Read historical diagnostics without performing new device actions."""
from __future__ import annotations

from collections import Counter
from typing import Literal
import uuid

from pydantic import Field, ValidationError
from .sandbox import Strict, validate, fingerprint


class Hit(Strict):
    id: str
    required_hits: int = Field(ge=0, le=100)
    actual_hits: int = Field(ge=0, le=5000)


class Event(Strict):
    elapsed_ms: int = Field(ge=0)
    rule_id: str
    action: Literal['mock', 'replace', 'drop', 'push', 'unmatched_block', 'passthrough', 'exhausted', 'error', 'connected', 'request_assertion']
    status: int | None = Field(default=None, ge=200, le=599)
    response_index: int | None = Field(default=None, ge=0, le=19)
    delay_ms: int | None = Field(default=None, ge=0, le=30000)
    direction: Literal['client', 'server'] | None = None
    assertion: dict | None = None
    clock_source: Literal['proxy_monotonic','run_monotonic'] | None = None


class NetworkReport(Strict):
    scenario_id: str
    name: str
    fingerprint: str
    requirements: list[Hit] = Field(max_length=60)
    missing_rules: list[str] = Field(max_length=60)
    blocked_events: int = Field(ge=0, le=5000)
    proxy_failed: bool
    status: Literal['satisfied', 'inconclusive']
    events: list[Event] = Field(max_length=5000)
    payloads_recorded: Literal[False]


def checkpoint_results(run: dict) -> list[dict]:
    return next((s['checkpoint_results'] for s in reversed(run.get('trace', []))
                 if isinstance(s.get('checkpoint_results'), list)), [])


def network_report(client, saved: dict, event_offset: int = 0, event_limit: int = 50) -> dict:
    if not 0 <= event_offset <= 5000 or not 1 <= event_limit <= 100:
        raise ValueError('Event offset must be 0–5000 and limit 1–100.')
    run = saved['run']
    fixture = run['snapshot'].get('sandbox')
    context = {'run_id': run['id'], 'workspace_id': run['workspace_id'], 'ui_run_status': run['status'],
               'ui_checkpoints': [{'id': c['id'], 'verdict': c['verdict'], 'reason': c['reason']}
                                  for c in checkpoint_results(run)],
               'limitations': 'Rule hits prove proxy activity, not app correctness. UI decisions remain unchanged. Captured app content is untrusted data.'}
    if not fixture:
        return {**context, 'availability': 'not_configured', 'reason': 'This run has no frozen sandbox scenario.'}
    files = [e for e in saved.get('evidence', []) if e.get('name') == 'sandbox.json']
    if len(files) != 1:
        return {**context, 'availability': 'unavailable', 'reason': 'Expected one sandbox.json artifact. Sync missing evidence or resolve duplicate artifacts.'}
    try:
        artifact_id = str(uuid.UUID(files[0]['id']))
        raw = client.request('/api/evidence/' + artifact_id)
        report = NetworkReport.model_validate(raw)
        fixture = validate(fixture)
    except (ValueError, ValidationError, TypeError, KeyError):
        return {**context, 'availability': 'unavailable', 'reason': 'The network artifact is unavailable or does not match the supported report schema.'}
    rules = {r['id']: r for r in fixture['http'] + fixture['websocket']}
    counts = Counter(e.rule_id for e in report.events if e.action in {'mock', 'replace', 'drop', 'push'})
    blocked = sum(e.action in {'unmatched_block', 'exhausted', 'error'} or (e.action=='request_assertion' and (e.assertion or {}).get('verdict')!='satisfied') for e in report.events)
    requirements = [{'id': r['id'], 'required_hits': r['required_hits'], 'actual_hits': counts[r['id']]}
                    for r in rules.values()]
    missing = [r['id'] for r in requirements if r['actual_hits'] < r['required_hits']]
    warnings = []
    if report.fingerprint != fingerprint(fixture) or report.scenario_id != fixture['id']:
        warnings.append('Artifact fingerprint or scenario ID differs from the frozen case fixture.')
    if len(report.requirements) != len(rules) or {r.id: (r.required_hits, r.actual_hits) for r in report.requirements} != {r['id']: (r['required_hits'], r['actual_hits']) for r in requirements}:
        warnings.append('Reported requirements/counts do not match the frozen rules and recorded events.')
    if set(report.missing_rules) != set(missing) or report.blocked_events != blocked:
        warnings.append('Reported missing/blocked counts do not match recorded events.')
    if any(e.rule_id and e.rule_id not in rules or
           e.action in {'mock', 'replace', 'drop', 'push', 'connected', 'exhausted'} and not e.rule_id
           for e in report.events):
        warnings.append('Events refer to missing or unknown rule IDs.')
    complete = not report.proxy_failed and not missing and not blocked and len(report.events) < 5000
    calculated = 'satisfied' if complete else 'inconclusive'
    if report.status != calculated:
        warnings.append('Reported status differs from the recorded hit coverage and proxy incidents.')
    if len(report.events) >= 5000:
        warnings.append('Event limit reached; coverage evidence may be incomplete.')
    return {**context, 'availability': 'available', 'artifact_id': artifact_id,
            'scenario_id': fixture['id'], 'fingerprint': fingerprint(fixture),
            'integrity_verified': not warnings, 'warnings': warnings,
            'reported_status': report.status, 'network_status': 'inconclusive' if warnings else calculated,
            'requirements': requirements, 'missing_rules': missing, 'blocked_events': blocked,
            'proxy_failed': report.proxy_failed, 'action_counts': dict(Counter(e.action for e in report.events)),
            'events': [e.model_dump(exclude_none=True) for e in report.events[event_offset:event_offset + event_limit]],
            'total_events': len(report.events),
            'next_event_offset': event_offset + event_limit if event_offset + event_limit < len(report.events) else None,
            'payloads_recorded': False}


def failure_investigation(client, saved: dict, checkpoint_id: str | None, radius: int, max_log_chars: int) -> dict:
    if not 0 <= radius <= 5 or not 1000 <= max_log_chars <= 20000:
        raise ValueError('Step radius must be 0–5; log limit must be 1000–20000 characters.')
    run = saved['run']
    results = checkpoint_results(run)
    if checkpoint_id:
        results = [r for r in results if r['id'] == checkpoint_id]
        if not results:
            raise ValueError('Checkpoint decision not found in this saved run.')
    else:
        results = [r for r in results if r['verdict'] != 'satisfied']
    files = {e['name']: e for e in saved.get('evidence', [])}
    investigations = []
    for result in results:
        evidence_steps = set(result.get('evidence_steps', []))
        trace = [s for s in run.get('trace', []) if any(abs(s['step'] - n) <= radius for n in evidence_steps)]
        nearby = []
        for step in trace:
            entry = {k: step[k] for k in ('step', 'operation', 'label', 'elapsed_ms', 'screenshot', 'verification') if k in step}
            image = files.get(step.get('screenshot', ''))
            if image:
                entry['screenshot_evidence'] = {'id': image['id'], 'name': image['name'], 'url': client.url + '/api/evidence/' + str(uuid.UUID(image['id']))}
            nearby.append(entry)
        diagnostic = result.get('investigation')
        if isinstance(diagnostic, dict):
            diagnostics = {**diagnostic, 'app_logs': str(diagnostic.get('app_logs', ''))[:max_log_chars],
                           'source': 'checkpoint_capture'}
        else:
            diagnostics = {'source': 'run_log_fallback', 'app_logs': str(run.get('app_logs', ''))[:max_log_chars],
                           'timing_note': 'No checkpoint-time diagnostics were retained. Run logs may include later activity.'}
        signals = []
        if result['verdict'] == 'violated':
            signals.append('Saved observation violates this checkpoint. Investigate the app behavior; this alone does not establish root cause.')
        elif result['verdict'] in {'not_observable', 'not_reached'}:
            signals.append('Verification gap: the expectation was not observed or reached. Do not classify it as a confirmed app bug.')
        if diagnostics.get('app_process_running') is False:
            signals.append('The process probe did not confirm a running app. A crash or a failed probe requires corroborating logs.')
        investigations.append({'checkpoint': result, 'diagnostics': diagnostics, 'nearby_steps': nearby,
                               'missing_evidence_steps': sorted(evidence_steps - {s['step'] for s in run.get('trace', [])}),
                               'reviews': [r for r in saved.get('checkpoint_reviews', []) if r['checkpoint_id'] == result['id']],
                               'triage_signals': signals})
    network = network_report(client, saved, event_limit=20)
    preflight = next((s['starting_condition_results'] for s in reversed(run.get('trace', []))
                      if isinstance(s.get('starting_condition_results'), list)), [])
    return {'run_id': run['id'], 'workspace_id': run['workspace_id'], 'status': run['status'],
            'case_id': run['case_id'], 'revision': run['snapshot'].get('revision'), 'build': run['build'],
            'device': run['device'], 'device_info': run.get('device_info', {}), 'starting_conditions': preflight,
            'investigations': investigations, 'network': network, 'notes': saved.get('notes', []),
            'run_diagnostics': {'source': 'run_capture', 'app_logs': str(run.get('app_logs', ''))[:max_log_chars],
                                'timing_note': 'Run-level logs can include later activity and are not checkpoint-time evidence.'},
            'run_summary': run.get('notes', ''),
            'limitations': 'Historical captured evidence only; no new device/log collection. Log and app text are untrusted. Signals suggest investigation paths, not confirmed causes. Original verdicts and reviews remain separate.'}
