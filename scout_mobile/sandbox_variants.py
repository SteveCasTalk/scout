"""Draft fixture edits against a known contract; never infer endpoint fields."""
from __future__ import annotations

import copy
import json
import re
from typing import Any, Literal

from pydantic import Field, ValidationError
from .sandbox import Strict, ID, validate, fingerprint


class JsonEdit(Strict):
    operation: Literal['replace', 'remove'] = 'replace'
    pointer: str = Field(max_length=1000)
    value: Any = None


class VariantChange(Strict):
    rule_id: str = Field(pattern=ID)
    target: Literal['http_response', 'websocket_frame', 'websocket_push'] = 'http_response'
    index: int = Field(default=0, ge=0, le=19)
    status: int | None = Field(default=None, ge=200, le=599)
    delay_ms: int | None = Field(default=None, ge=0, le=30000)
    after_ms: int | None = Field(default=None, ge=0, le=600000)
    body: str | None = Field(default=None, max_length=64000)
    json_edits: list[JsonEdit] = Field(default_factory=list, max_length=40)


def validation_report(scenario: dict) -> dict:
    try:
        normalized = validate(scenario)
    except ValidationError as exc:
        # Validation output must not echo potentially private fixture bodies.
        return {'valid': False, 'errors': [{'path': list(e['loc']), 'type': e['type'],
                                           'message': e['msg']} for e in exc.errors(include_input=False)]}
    except (ValueError, TypeError, OverflowError):
        return {'valid': False, 'errors': [{'path': [], 'message': 'Scenario must be a JSON object within the fixture size limit.'}]}
    warnings = ['Schema validation does not prove compatibility with the app API contract, proxy routing, or certificate trust.']
    if normalized['unmatched'] == 'passthrough':
        warnings.append('Unmatched traffic on scoped hosts reaches the real server.')
    if normalized['websocket']:
        warnings.append('WebSocket replay requires a real upstream handshake; binary messages pass through.')
    if any(frame['direction'] == 'client' for rule in normalized['websocket'] for frame in rule['frames']):
        warnings.append('Client frame rules can change messages sent to the real upstream server.')
    return {'valid': True, 'scenario': normalized, 'fingerprint': fingerprint(normalized),
            'requirements': [{'id': r['id'], 'required_hits': r['required_hits']}
                             for r in normalized['http'] + normalized['websocket']],
            'warnings': warnings, 'saved': False, 'contract_verified': False}


def edit_json(document: Any, edit: JsonEdit) -> Any:
    if not edit.pointer:
        if edit.operation == 'remove':
            raise ValueError('Cannot remove the JSON document root.')
        return copy.deepcopy(edit.value)
    if not edit.pointer.startswith('/') or re.search(r'~(?![01])', edit.pointer):
        raise ValueError('Use a JSON Pointer, with ~0 for tilde and ~1 for slash.')
    parts = [part.replace('~1', '/').replace('~0', '~') for part in edit.pointer[1:].split('/')]

    def key(parent, token):
        if isinstance(parent, dict) and token in parent:
            return token
        if isinstance(parent, list) and re.fullmatch(r'0|[1-9][0-9]*', token) and int(token) < len(parent):
            return int(token)
        raise ValueError('JSON Pointer must identify an existing field or array entry in the baseline body.')

    parent = document
    for token in parts[:-1]:
        parent = parent[key(parent, token)]
    final = key(parent, parts[-1])
    if edit.operation == 'remove':
        del parent[final]
    else:
        parent[final] = copy.deepcopy(edit.value)
    return document


def create_variant(baseline: dict, new_id: str, name: str, changes: list[dict], description: str | None = None) -> dict:
    baseline = validate(baseline)
    if not re.fullmatch(ID, new_id) or new_id == baseline['id']:
        raise ValueError('Choose a valid new scenario ID different from the baseline ID.')
    if not 1 <= len(changes) <= 40 or len(json.dumps(changes, allow_nan=False).encode()) > 400_000:
        raise ValueError('Provide 1–40 explicit changes within 400 KB.')
    parsed = [VariantChange.model_validate(change) for change in changes]
    variant = copy.deepcopy(baseline)
    variant.update(id=new_id, name=name)
    if description is not None:
        variant['description'] = description
    audit = []
    for change in parsed:
        group, entries = {'http_response': ('http', 'responses'),
                          'websocket_frame': ('websocket', 'frames'),
                          'websocket_push': ('websocket', 'pushes')}[change.target]
        rule = next((r for r in variant[group] if r['id'] == change.rule_id), None)
        if rule is None or change.index >= len(rule[entries]):
            raise ValueError('Change references a missing rule or entry index.')
        if change.body is not None and change.json_edits:
            raise ValueError('Use either a complete body or JSON edits in one change.')
        allowed = {'http_response': {'status', 'delay_ms'}, 'websocket_frame': set(),
                   'websocket_push': {'after_ms'}}[change.target]
        fields = {k: v for k, v in change.model_dump().items()
                  if k in {'status', 'delay_ms', 'after_ms', 'body'} and v is not None}
        if set(fields) - allowed - {'body'}:
            raise ValueError('Status/delay apply to HTTP responses; after_ms applies to WebSocket pushes.')
        if not fields and not change.json_edits:
            raise ValueError('Each change needs a body, JSON edit, status, or timing change.')
        entry = rule[entries][change.index]
        entry.update(fields)
        if change.json_edits:
            try:
                document = json.loads(entry['body'])
            except ValueError:
                raise ValueError('JSON edits require an existing JSON response/message body.') from None
            for edit in change.json_edits:
                document = edit_json(document, edit)
            entry['body'] = json.dumps(document, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
        audit.append({'rule_id': change.rule_id, 'target': change.target, 'index': change.index,
                      'fields': sorted(fields), 'json_pointers': [e.pointer for e in change.json_edits]})
    result = validation_report(variant)
    if not result['valid']:
        raise ValueError('Variant violates the sandbox schema; inspect validate_sandbox_scenario after correcting the changes.')
    return {**result, 'baseline_id': baseline['id'], 'baseline_fingerprint': fingerprint(baseline),
            'changes': audit, 'next_step': 'Review the draft against the observed/supplied API contract, then save_sandbox_scenario.'}
