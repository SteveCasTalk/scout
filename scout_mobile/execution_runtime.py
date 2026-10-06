"""Deterministic actions and sampled assertions owned by the existing device runner."""
from __future__ import annotations
import json
import math
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from .device import BOUNDS, DeviceError, Element
from .execution_contract import Selector
from .temporal import TemporalState

class ExecutionBlocked(DeviceError):pass
class ObservationIncomplete(DeviceError):pass


def locate(screen, selector, tap=False):
    """Exact dynamic matching, including observed non-clickable gesture nodes."""
    selector=Selector.model_validate(selector).model_dump()
    try:root=ET.fromstring(screen.xml)
    except ET.ParseError:raise ExecutionBlocked('Invalid hierarchy; target cannot be grounded.') from None
    matches=[]
    def visit(node, visible=True):
        a=node.attrib
        visible=visible and a.get('displayed','true')!='false' and a.get('enabled','true')!='false'
        label=a.get('text','').strip() or a.get('content-desc','').strip()
        cls=a.get('class',node.tag)
        if visible and all(not selector[k] or selector[k]==v for k,v in [('resource_id',a.get('resource-id','')),('text',label),('class_name',cls)]):
            b=BOUNDS.fullmatch(a.get('bounds',''))
            if b:
                rect=tuple(map(int,b.groups()))
                if 0<=rect[0]<rect[2]<=screen.width and 0<=rect[1]<rect[3]<=screen.height:
                    actionable=a.get('clickable')=='true' or a.get('checkable')=='true'
                    if not tap or actionable:
                        matches.append(Element('typed','textbox' if 'EditText' in cls else 'control',label,a.get('resource-id',''),cls,'',rect,('TAP',) if actionable else (),False,password=a.get('password')=='true'))
        for child in node:visit(child,visible)
    visit(root)
    if len(matches)!=1:raise ExecutionBlocked('Selector is missing, disabled, or ambiguous; no action dispatched.')
    return matches[0]


def selector_matches(element,selector):
    return bool(element and all(not selector.get(k) or selector[k]==v for k,v in [('resource_id',element.resource_id),('text',element.label),('class_name',element.class_name)]))

class Boundary:
    def __init__(self,agent):
        self.agent=agent;self.target=agent.config.package;self.current=self.target
        self.flows={f['package']:f for f in agent.execution['external_flows']}
        self.active=None;self.entered=0;self.count=0;self.return_verified=True
        checkout={e['destination_package'] for e in agent.execution['purchase_entries']}
        self.checkout=checkout|{'com.android.vending'}
    def check(self,package,screen):
        now=time.monotonic()
        if not package:raise ExecutionBlocked('Unknown foreground package; no action allowed.')
        if self.active and (now-self.entered)*1000>self.active['max_duration_ms']:
            raise ExecutionBlocked('Approved external flow exceeded its return deadline.')
        if package==self.target:
            if self.active and self.active['return_text'].casefold() not in screen.text.casefold():
                raise ExecutionBlocked('Returned to the target package without the expected return screen.')
            self.active=None;self.current=package;self.return_verified=True
            return
        if package!=self.current:
            flow=self.flows.get(package)
            if not flow or flow['from_package']!=self.current or flow['entry_text'].casefold() not in screen.text.casefold():
                raise ExecutionBlocked('Unexpected or unverified external destination: '+package)
            self.active=flow;self.entered=now;self.count=0;self.current=package;self.return_verified=False
        elif not self.active:
            raise ExecutionBlocked('External package has no approved entry transition.')
    def authorize(self,operation,element=None):
        if self.current==self.target:return
        flow=self.active
        if operation in {'OBSERVE','WAIT','DONE'}:return
        if self.count>=flow['max_actions']:raise ExecutionBlocked('External action budget exhausted.')
        if operation=='BACK' and flow['allow_back']:
            self.count+=1;return
        if self.current in self.checkout or flow['checkout']:
            raise ExecutionBlocked('Checkout is observation-only; payment confirmation is outside purchase-entry scope.')
        if operation!='TAP' or not any(selector_matches(element,s) for s in flow['taps']):
            raise ExecutionBlocked('This external control/action is not explicitly approved.')
        self.count+=1


def check_action(agent,operation,element,screen,purchase=False):
    from .agent import RISKY
    label=element.label if element else ''
    if element and (element.password or element.role=='textbox'):
        raise ExecutionBlocked('Typed actions cannot enter credentials or arbitrary text.')
    if agent.consent_confirmation_required(label,screen.text) and not agent.config.allow_consent:
        raise ExecutionBlocked('Explicit consent authorization is required.')
    if element and RISKY.search(label) and not purchase:
        raise ExecutionBlocked('Consequential control remains blocked: '+agent.redact(label))
    if operation=='TAP_BURST' and (agent.consent_confirmation_required(label,screen.text) or agent.boundary.current!=agent.config.package):
        raise ExecutionBlocked('Burst is not allowed for consent or external controls.')
    agent.boundary.authorize(operation,element)

class Protocol:
    def __init__(self,agent):
        if (agent.output/'execution-evidence.json').exists():raise ExecutionBlocked('This output directory already contains execution evidence. Use a new run directory; consumed actions cannot be retried.')
        self.a=agent;self.spec=agent.execution;self.samples=[];self.results=[]
        self.events=[];self.consumed=set();self.truncated=False
    def event(self,name,**details):
        self.events.append({'event':name,'elapsed_ms':self.a.elapsed_ms(),**details})
        self.save()
    def save(self):
        path=self.a.output/'execution-evidence.json'
        temporary=path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'schema_version':2,'contract_fingerprint':__import__('scout_mobile.execution_contract',fromlist=['fingerprint']).fingerprint(self.spec),'consumed_purchase_entries':sorted(self.consumed),'events':self.events,'samples':self.samples,'assertions':self.results,'truncated':self.truncated},indent=2)+'\n')
        temporary.replace(path)
    def observe(self):
        if self.a.config.should_stop and self.a.config.should_stop():raise ObservationIncomplete('Stopped during deterministic observation.')
        if time.monotonic()-self.a.started>self.spec['timeout_seconds']:raise ObservationIncomplete('Execution time budget reached.')
        screen=self.a.device.observe();package=self.a.device.foreground()
        self.a.boundary.check(package,screen)
        return screen,package
    def wait_screen(self,text,timeout_ms,package=None):
        deadline=time.monotonic()+timeout_ms/1000
        while True:
            screen,current=self.observe()
            if (not package or current==package) and text.casefold() in screen.text.casefold():return screen
            if time.monotonic()>=deadline:raise ObservationIncomplete('Expected screen was not established within the bounded wait.')
            time.sleep(.1)
    def run_action(self,action):
        a=self.a
        screen,package=self.observe()
        if package!=action['package']:raise ExecutionBlocked('Action package does not match fresh foreground.')
        op=action['operation'];element=None;destination=None;entry=None
        if op=='PURCHASE_ENTRY':
            entry=next(e for e in self.spec['purchase_entries'] if e['id']==action['entry_id'])
            if package!=a.config.package or entry['id'] not in a.authorizations['purchase_entries'] or entry['id'] in self.consumed:
                raise ExecutionBlocked('Purchase entry lacks unused run authorization.')
            if entry['screen_text'].casefold() not in screen.text.casefold():raise ExecutionBlocked('Purchase entry screen precondition not established.')
            element=locate(screen,entry['selector'],tap=True)
            # Never authorize transfers, deletion, or withdrawal through an entry exception.
            if re.search(r'\b(?:transfer|withdraw|delete account)\b',element.label,re.I):raise ExecutionBlocked('Not a purchase-entry control.')
        elif action['selector']:
            element=locate(screen,action['selector'],tap=op in {'TAP','TAP_BURST'})
        if action['destination']:destination=locate(screen,action['destination'])
        check_action(a,'TAP' if entry else op,element,screen,purchase=bool(entry))
        if destination:check_action(a,'DRAG',destination,screen)
        index=len(a.history)
        record={'step':index,'operation':op,'action_id':action['id'],'label':a.redact(element.label) if element else None,'resource_id':element.resource_id if element else None,'target_bounds':list(element.bounds) if element else None,'destination_bounds':list(destination.bounds) if destination else None,'before_fingerprint':screen.fingerprint,'foreground':package,'elapsed_ms':a.elapsed_ms()}
        a.history.append(record)
        if entry:
            # Persist the allowance before dispatch. An ambiguous input failure is never retried.
            self.consumed.add(entry['id']);record['coverage']='purchase_entry_only'
            self.event('purchase_entry_consumed',entry_id=entry['id'],action_id=action['id'])
        self.event('action_start',action_id=action['id'])
        record['dispatch_start_ms']=a.elapsed_ms()
        if op in {'TAP','PURCHASE_ENTRY'}:a.device.tap(element)
        elif op=='BACK':a.device.back()
        elif op=='SWIPE':
            x1,y1,x2,y2=element.bounds;cx,cy=element.center
            points={'left':(int(x1+(x2-x1)*.85),cy,int(x1+(x2-x1)*.15),cy),'right':(int(x1+(x2-x1)*.15),cy,int(x1+(x2-x1)*.85),cy),'up':(cx,int(y1+(y2-y1)*.85),cx,int(y1+(y2-y1)*.15)),'down':(cx,int(y1+(y2-y1)*.15),cx,int(y1+(y2-y1)*.85))}
            coords=points[action['direction']]
            if coords[:2]==coords[2:]:raise ExecutionBlocked('Target bounds are too small for this gesture.')
            a.device.swipe_coordinates(*coords,action['duration_ms']);record['gesture']={'start':coords[:2],'end':coords[2:],'duration_ms':action['duration_ms']}
        elif op=='DRAG':
            if not hasattr(a.device,'drag_coordinates'):raise ExecutionBlocked('Adapter cannot perform a drag with explicit hold.')
            a.device.drag_coordinates(*element.center,*destination.center,action['duration_ms'],action['hold_ms'])
        elif op=='TAP_BURST':
            if not hasattr(a.device,'tap_burst'):raise ExecutionBlocked('Adapter cannot dispatch a native bounded tap burst.')
            record['burst']=a.device.tap_burst(element,action['count'],action['interval_ms'])
        trigger=time.monotonic()
        record['dispatch_end_ms']=round((trigger-a.started)*1000);self.event('action_end',action_id=action['id'])
        triggered=[r for r in self.spec['temporal_assertions'] if r['after_action']==action['id']]
        if triggered:self.temporals(triggered,trigger)
        if entry:
            screen=self.wait_screen(entry['destination_text'],entry['timeout_ms'],entry['destination_package'])
        elif action['wait_text']:screen=self.wait_screen(action['wait_text'],action['timeout_ms'])
        else:screen,_=self.observe()
        record.update(screen=a.public_screen(screen),screenshot=a.screenshot(screen,index),after_fingerprint=screen.fingerprint,page_changed=screen.fingerprint!=record['before_fingerprint'])
        a.assess_checkpoints(screen,index)
        if a.config.on_progress:a.config.on_progress(a.history)
        return screen
    def temporals(self,rules,trigger):
        states=[TemporalState(r,round((trigger-self.a.started)*1000)) for r in rules]
        try:
            while any(not s.done for s in states):
                start=time.monotonic();screen,_=self.observe();end=time.monotonic()
                text=screen.text.casefold()
                start_ms=round((start-self.a.started)*1000);end_ms=round((end-self.a.started)*1000)
                for state in states:
                    if state.done:continue
                    rule=state.rule
                    context=bool(text.strip()) and rule['context_text'].casefold() in text
                    found=rule['text'].casefold() in text
                    terminal=bool(rule['until_text'] and rule['until_text'].casefold() in text)
                    hits=[i for i,t in enumerate(rule['ordered_texts']) if t.casefold() in text]
                    if len(self.samples)<5000:
                        self.samples.append({'assertion_id':rule['id'],'start_ms':start_ms,'end_ms':end_ms,'context':context,'predicate':found,'terminal':terminal,'ordered_hits':hits,'fingerprint':screen.fingerprint})
                    else:
                        self.truncated=True;state.good=False
                    state.feed(start_ms,end_ms,context,found,terminal,hits)
                active=[s for s in states if not s.done]
                if active:time.sleep(min(min(s.rule['poll_ms'] for s in active)/1000,max(0,(min(s.deadline for s in active)-end_ms)/1000)))
        finally:
            self.results.extend(s.result() for s in states);self.save()

    def run(self):
        screen=None
        for action in self.spec['actions']:screen=self.run_action(action)
        if self.a.boundary.active and self.a.boundary.active['require_return']:raise ObservationIncomplete('Approved external flow has not returned to its expected target screen.')
        return screen or self.observe()[0]
    def outcome(self):
        expected=[r for r in self.spec['temporal_assertions'] if r['required']]
        identities={r['id'] for r in expected}
        required=[r for r in self.results if r['required'] and r['id'] in identities and r.get('evidence_source')=='sampled_ui']
        if any(r['verdict']=='violated' for r in required):return 'Failed'
        if len(required)!=len(expected) or any(r['verdict']!='satisfied' for r in required):return 'Inconclusive'
        return 'Passed'
