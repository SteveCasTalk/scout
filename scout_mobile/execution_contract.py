"""Opt-in v2 execution definitions; legacy cases retain their original contract."""
from __future__ import annotations
import hashlib
import json
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

ID = r'^[A-Za-z0-9_-]{1,40}$'
PACKAGE = r'^[A-Za-z0-9_.]{3,240}$'

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

class Selector(Strict):
    resource_id: str = Field(default='', max_length=240)
    text: str = Field(default='', max_length=240)
    class_name: str = Field(default='', max_length=240)
    @model_validator(mode='after')
    def grounded(self):
        if not self.resource_id and not self.text:
            raise ValueError('A selector requires an exact resource_id or text.')
        return self

class Entry(Strict):
    id: str = Field(pattern=ID)
    selector: Selector
    screen_text: str = Field(min_length=1, max_length=240)
    destination_package: str = Field(pattern=PACKAGE)
    destination_text: str = Field(min_length=1, max_length=240)
    timeout_ms: int = Field(default=10000, ge=100, le=30000)

class External(Strict):
    package: str = Field(pattern=PACKAGE)
    from_package: str = Field(pattern=PACKAGE)
    entry_text: str = Field(min_length=1, max_length=240)
    return_text: str = Field(min_length=1, max_length=240)
    max_duration_ms: int = Field(default=30000, ge=100, le=120000)
    max_actions: int = Field(default=2, ge=0, le=10)
    taps: list[Selector] = Field(default_factory=list, max_length=10)
    allow_back: bool = False
    # Billing destinations are observation/back only regardless of their button labels.
    checkout: bool = False
    require_return: bool = True

class Action(Strict):
    id: str = Field(pattern=ID)
    operation: Literal['TAP','BACK','SWIPE','DRAG','TAP_BURST','PURCHASE_ENTRY','OBSERVE']
    package: str = Field(pattern=PACKAGE)
    selector: Selector | None = None
    destination: Selector | None = None
    entry_id: str = Field(default='', max_length=40)
    direction: Literal['left','right','up','down'] = 'left'
    duration_ms: int = Field(default=300, ge=50, le=3000)
    hold_ms: int = Field(default=400, ge=0, le=2000)
    count: int = Field(default=2, ge=2, le=5)
    interval_ms: int = Field(default=100, ge=50, le=1000)
    wait_text: str = Field(default='', max_length=240)
    timeout_ms: int = Field(default=5000, ge=100, le=30000)
    @model_validator(mode='after')
    def shape(self):
        if self.operation in {'TAP','SWIPE','DRAG','TAP_BURST'} and self.selector is None:
            raise ValueError('This operation requires a grounded selector.')
        if self.operation == 'DRAG' and self.destination is None:
            raise ValueError('Drag requires a grounded destination selector.')
        if self.operation == 'PURCHASE_ENTRY' and not re.fullmatch(ID,self.entry_id):
            raise ValueError('Purchase entry requires a declared entry_id.')
        return self

class Temporal(Strict):
    id: str = Field(pattern=ID)
    after_action: str = Field(pattern=ID)
    mode: Literal['within','never_during','stable_for','ordered','until']
    text: str = Field(min_length=1, max_length=240)
    context_text: str = Field(min_length=1, max_length=240)
    until_text: str = Field(default='', max_length=240)
    ordered_texts: list[str] = Field(default_factory=list, max_length=10)
    window_ms: int = Field(ge=100, le=600000)
    poll_ms: int = Field(default=250, ge=50, le=5000)
    max_gap_ms: int = Field(default=2000, ge=100, le=10000)
    evidence: Literal['sampled_ui','continuous_events'] = 'sampled_ui'
    required: bool = True
    @model_validator(mode='after')
    def shape(self):
        if self.mode == 'ordered' and (len(self.ordered_texts)<2 or any(not t.strip() or len(t)>240 for t in self.ordered_texts)):
            raise ValueError('Ordered assertions require 2–10 nonempty text predicates.')
        if self.mode == 'until' and not self.until_text:
            raise ValueError('Until assertions require until_text.')
        return self

class Hook(Strict):
    id: str = Field(pattern=ID)
    operation: Literal['terminate','permission','wifi','clear_data']
    permission: str = Field(default='', pattern=r'^(?:android\.permission\.[A-Z_]+)?$', max_length=120)
    enabled: bool = False
    @model_validator(mode='after')
    def shape(self):
        if self.operation == 'permission' and not self.permission:
            raise ValueError('Permission hooks require a permission.')
        return self

class Lifecycle(Strict):
    before: list[Hook] = Field(default_factory=list, max_length=10)
    notification_policy: Literal['legacy_suppress','preserve'] = 'legacy_suppress'

class Media(Strict):
    id: str = Field(pattern=ID)
    artifact: str = Field(pattern=r'^[A-Za-z0-9_-]+\.(?:mp4|webm|mov|wav|mp3)$', max_length=100)
    width: int | None = Field(default=None, ge=1, le=16384)
    height: int | None = Field(default=None, ge=1, le=16384)
    duration_min_ms: int = Field(default=0, ge=0, le=3600000)
    duration_max_ms: int = Field(default=3600000, ge=1, le=3600000)
    required: bool = True
    kind: Literal['metadata','frame_change'] = 'metadata'
    frame_start_ms: int = Field(default=0,ge=0,le=3600000)
    frame_end_ms: int = Field(default=1000,ge=1,le=3600000)
    minimum_change: float = Field(default=0.02,ge=0,le=1)
    @model_validator(mode='after')
    def shape(self):
        if self.duration_min_ms > self.duration_max_ms:
            raise ValueError('Invalid media duration interval.')
        if self.frame_start_ms>=self.frame_end_ms:raise ValueError('Frame samples must be ordered.')
        return self

class Execution(Strict):
    schema_version: Literal[2] = 2
    required_capabilities: list[str] = Field(default_factory=list, max_length=20)
    purchase_entries: list[Entry] = Field(default_factory=list, max_length=5)
    external_flows: list[External] = Field(default_factory=list, max_length=10)
    actions: list[Action] = Field(default_factory=list, max_length=100)
    temporal_assertions: list[Temporal] = Field(default_factory=list, max_length=12)
    lifecycle: Lifecycle = Field(default_factory=Lifecycle)
    media_assertions: list[Media] = Field(default_factory=list, max_length=12)
    finish: Literal['verify','model'] = 'verify'
    timeout_seconds: int = Field(default=600, ge=10, le=1800)
    @model_validator(mode='after')
    def consistent(self):
        for items, attr in [(self.actions,'id'),(self.purchase_entries,'id'),(self.temporal_assertions,'id'),(self.media_assertions,'id'),(self.lifecycle.before,'id'),(self.external_flows,'package')]:
            if len({getattr(i,attr) for i in items}) != len(items):
                raise ValueError('Definition IDs and external packages must be unique within their collection.')
        actions={a.id for a in self.actions}; entries={e.id for e in self.purchase_entries}
        if any(t.after_action not in actions for t in self.temporal_assertions):
            raise ValueError('Temporal triggers must reference a declared action.')
        if any(a.entry_id not in entries for a in self.actions if a.operation=='PURCHASE_ENTRY'):
            raise ValueError('Unknown purchase entry.')
        used=[a.entry_id for a in self.actions if a.operation=='PURCHASE_ENTRY']
        if len(used)!=len(set(used)):
            raise ValueError('A purchase entry may be dispatched only once.')
        if used:
            if self.finish!='verify':raise ValueError('Purchase entry ends in verification, never unrestricted model navigation.')
            opened=False
            for action in self.actions:
                if opened and action.operation not in {'OBSERVE','BACK'}:raise ValueError('After purchase entry, only observation or a safe return is supported.')
                if action.operation=='PURCHASE_ENTRY':opened=True
            for action in self.actions:
                if action.operation=='TAP_BURST' and any(action.selector and action.selector.model_dump()==entry.selector.model_dump() for entry in self.purchase_entries):raise ValueError('Purchase entry cannot be dispatched by a tap burst.')
        needed=set()
        if self.purchase_entries:needed.add('purchase_entry')
        if self.external_flows:needed.add('external_packages')
        if any(a.operation in {'SWIPE','DRAG'} for a in self.actions):needed.add('target_gestures')
        if any(a.operation=='TAP_BURST' for a in self.actions):needed.add('tap_burst')
        if self.temporal_assertions:needed.add('temporal_ui')
        if self.lifecycle.before or self.lifecycle.notification_policy!='legacy_suppress':needed.add('lifecycle')
        if self.media_assertions:needed.add('media_metadata')
        if len(set(self.required_capabilities))!=len(self.required_capabilities) or not needed.issubset(self.required_capabilities):
            raise ValueError('required_capabilities must be unique and include every feature used by this definition: '+', '.join(sorted(needed)))
        return self

class Authorizations(Strict):
    purchase_entries: list[str] = Field(default_factory=list, max_length=5)
    clear_data: bool = False

FEATURES={'purchase_entry','external_packages','target_gestures','tap_burst','temporal_ui','lifecycle','media_metadata','network_contract_v2','request_assertions'}

def validate_execution(value):
    return None if value is None else Execution.model_validate(value).model_dump()

def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

def supported(platform='Android', backend='appium'):
    if platform!='Android':return {'network_contract_v2','request_assertions'}
    return FEATURES if backend=='appium' else FEATURES-{'tap_burst','target_gestures'}

def check_support(case, platform='Android', backend='appium'):
    execution=validate_execution(case.get('execution'))
    sandbox=case.get('sandbox') or {}
    if sandbox.get('schema_version')==2 and 'network_contract_v2' not in supported(platform,backend):raise ValueError('Network contract v2 is unsupported by this adapter.')
    if execution:
        missing=set(execution['required_capabilities'])-supported(platform,backend)
        if missing:raise ValueError('Unsupported capabilities for '+platform+'/'+backend+': '+', '.join(sorted(missing)))
        if platform!='Android':raise ValueError('Execution contract v2 actions and lifecycle currently require Android.')
    return execution

def validate_authorizations(value, execution):
    grants=Authorizations.model_validate(value or {}).model_dump()
    declared={e['id'] for e in execution['purchase_entries']} if execution else set()
    if len(set(grants['purchase_entries']))!=len(grants['purchase_entries']) or not set(grants['purchase_entries']).issubset(declared):
        raise ValueError('Run authorization cannot widen the declared purchase entries.')
    if grants['clear_data'] and (not execution or not any(h['operation']=='clear_data' for h in execution['lifecycle']['before'])):
        raise ValueError('Data reset must be declared in the case.')
    return grants

def decode_export(value):
    if isinstance(value,dict) and value.get('format')=='scout-case-v2':
        if set(value)!={'format','case'} or not isinstance(value['case'],dict) or not (value['case'].get('execution') or (value['case'].get('sandbox') or {}).get('schema_version')==2):
            raise ValueError('Invalid v2 case export envelope.')
        value=value['case']
    if not isinstance(value,dict):raise ValueError('Case must be an object.')
    validate_execution(value.get('execution'))
    return value

def export_case(case):
    return {'format':'scout-case-v2','case':case} if case.get('execution') or (case.get('sandbox') or {}).get('schema_version')==2 else case
