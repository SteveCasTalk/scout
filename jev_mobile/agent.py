"""Observe → choose → re-observe → act loop with independent outcome verification."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import re
import time
from typing import Any
from .config import ROOT
from .device import AndroidDevice, DeviceError, Element, Screen
from .model import ModelError, choose, field_text

GUARD_TEXT='This application is not supported on rooted devices or emulators.'
RISKY=re.compile(r'\b(?:pay|purchase|buy|transfer|delete account|subscribe|withdraw)\b',re.I)
CONSENT_GATE=re.compile(r'\b(?:user agreement|terms of (?:use|service)|privacy policy|consent|personal data processing)\b',re.I)
CONSENT_ACTION=re.compile(r'^\s*(?:i\s+agree|agree(?:\s+and\s+continue)?|accept(?:\s+all)?|continue\s+and\s+accept|allow|authorize|consent|grant|start|continue|confirm|submit|yes)\s*$',re.I)
EMAIL_VALUE=re.compile(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b',re.I)
EMAIL_FIELD=re.compile(r'email|e-mail|username|user name|account',re.I)
PASSWORD_FIELD=re.compile(r'password|passcode|pass word|passwd',re.I)
COMPANION_TUTORIAL=re.compile(r'\bswipe\s+up\s+to\s+select\s+your\s+companion\b',re.I)

@dataclass
class RunConfig:
    package:str
    serial:str
    test_case:dict[str,Any]
    output:Path
    adb:str='adb'
    max_steps:int=40
    timeout_seconds:int=180
    expected_text:str=''
    test_email:str=''
    test_password:str=''
    allow_consent:bool=False

class Agent:
    def __init__(self,config:RunConfig):
        self.config=config
        self.device=AndroidDevice(config.serial,config.adb)
        self.history:list[dict[str,Any]]=[]
        self.started=time.monotonic()
        self.credential_used=False
        self.tutorial_swipe_attempted=False
        self.verification={'status':'not_run','method':'exact_visible_text','expected_text':config.expected_text,'observed_text':''}
        self.output=config.output
        self.output.mkdir(parents=True,exist_ok=True)
        self.test_email=config.test_email or os.getenv('JEV_TEST_EMAIL','')
        self.test_password=config.test_password or os.getenv('JEV_TEST_PASSWORD','')
        self.secrets=[s for s in (self.test_email,self.test_password) if s]

    def elapsed_ms(self)->int:return round((time.monotonic()-self.started)*1000)

    def redact(self,value:str)->str:
        for secret in self.secrets:value=value.replace(secret,'<test credential>')
        return EMAIL_VALUE.sub('<email>',value)

    def redact_object(self,value:Any)->Any:
        if isinstance(value,str):return self.redact(value)
        if isinstance(value,list):return [self.redact_object(item) for item in value]
        if isinstance(value,dict):return {key:self.redact_object(item) for key,item in value.items()}
        return value

    def public_screen(self,screen:Screen)->dict[str,Any]:
        if 'Google Password Manager' in screen.text or 'Save password for UAT-AI Avatar?' in screen.text:
            return {'fingerprint':screen.fingerprint,'text':'Android credential prompt','elements':[]}
        text=self.redact(screen.text)
        return {'fingerprint':screen.fingerprint,'text':text,'elements':[{**e.public(),'label':self.redact(e.public()['label']),'value':self.redact(e.public()['value'])} for e in screen.elements]}

    def screenshot(self,screen:Screen,index:int)->str|None:
        # Once credentials are used, capture only screens with no input fields or visible account values.
        if 'Google Password Manager' in screen.text or 'Save password for UAT-AI Avatar?' in screen.text or any(secret in screen.xml for secret in self.secrets):return None
        # A focused credential field may show unrelated personal suggestions in the keyboard before typing.
        if any(e.focused and e.sensitive for e in screen.elements):return None
        # Avoid capturing transition/loading frames with an empty accessibility tree after login input.
        if self.credential_used and not screen.text.strip() and not screen.elements:return None
        if self.credential_used and (any(e.role=='textbox' for e in screen.elements) or EMAIL_VALUE.search(screen.text)):
            return None
        path=self.output/f'{index:03d}.png'
        self.device.screenshot(path)
        return path.name

    def credential_for(self,element:Element,screen:Screen)->tuple[str,str]|None:
        if element.password:return self.test_password,'password'
        label=f'{element.label} {element.resource_id} {element.class_name}'
        if PASSWORD_FIELD.search(label):return self.test_password,'password'
        if EMAIL_FIELD.search(label):return self.test_email,'email'
        if element.role=='textbox' and 'Enter your email address' in screen.text and not any(e.password for e in screen.elements):
            return self.test_email,'email'
        return None

    def wait(self,previous:Screen,seconds:float=4)->Screen:
        return self.device.wait_for_change(previous,min(seconds,5))

    @staticmethod
    def focused_text_field(screen:Screen,previous:Element)->Element|None:
        focused=[element for element in screen.elements if element.role=='textbox' and element.focused]
        if previous.resource_id:
            same_id=[element for element in focused if element.resource_id==previous.resource_id]
            if len(same_id)==1:return same_id[0]
        if len(focused)==1:return focused[0]
        if not focused:return None
        px,py=previous.center
        nearest=min(focused,key=lambda element:abs(element.center[0]-px)+abs(element.center[1]-py))
        distance=abs(nearest.center[0]-px)+abs(nearest.center[1]-py)
        return nearest if distance<=screen.height*.4 else None

    @staticmethod
    def consent_confirmation_required(label:str,screen_text:str)->bool:
        """Do not accept consent/legal gates unless a user explicitly authorizes it."""
        if re.fullmatch(r'\s*i\s+agree\s*',label,re.I):
            return True
        return bool(CONSENT_GATE.search(screen_text) and CONSENT_ACTION.fullmatch(label))

    def repeated_without_progress(self,operation:str,selected:Element,screen:Screen)->bool:
        return any(
            prior.get('operation')==operation
            and prior.get('label')==selected.label
            and prior.get('resource_id')==selected.resource_id
            and prior.get('before_fingerprint')==screen.fingerprint
            and prior.get('after_fingerprint')==screen.fingerprint
            for prior in reversed(self.history[-5:])
        )

    def write_result(self,status:str,reason:str,screen:Screen|None)->dict[str,Any]:
        case=self.config.test_case
        result={'schema_version':1,'source':'Jev Android runner','case_id':case.get('id'),'revision':case.get('revision'),'project':self.redact(str(case.get('project','General'))),'case_title':self.redact(str(case.get('title',''))),'goal':self.redact(str(case.get('goal',''))),'case_steps':self.redact(str(case.get('steps',''))),'expected_result':self.redact(str(case.get('expected',''))),'package':self.config.package,'platform':'Android','device':self.config.serial,'build':self.device.command('shell','dumpsys','package',self.config.package,check=False).stdout.decode(errors='replace').split('versionName=',1)[-1].splitlines()[0][:120] if self.device.installed(self.config.package) else 'unknown','status':status,'notes':self.redact(reason),'expected_text':self.redact(self.config.expected_text),'observed_text':self.redact(screen.text) if screen else '','verification':self.redact_object(self.verification),'elapsed_ms':self.elapsed_ms(),'steps':self.history,'created':datetime.now(timezone.utc).isoformat(),'credential_values_recorded':False}
        (self.output/'result.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        (self.output/'trace.json').write_text(json.dumps(self.history,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        jev_calls=[{'step':entry['step'],**entry['jev']} for entry in self.history if 'jev' in entry]
        (self.output/'jev-output.json').write_text(json.dumps({'schema_version':1,'source':'Jev decision audit','case_id':case.get('id'),'device':self.config.serial,'calls':jev_calls},indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        return result

    def verify_result(self,screen:Screen,step:int)->bool:
        expected=self.config.expected_text.strip()
        observed=self.redact(screen.text)[:8000]
        matched=bool(expected and expected.casefold() in screen.text.casefold())
        status='passed' if matched else 'failed' if expected else 'inconclusive'
        self.verification={'status':status,'method':'exact_visible_text','expected_text':self.redact(expected),'observed_text':observed}
        self.history.append({'step':step,'elapsed_ms':self.elapsed_ms(),'operation':'VERIFY_RESULT','verification':self.verification.copy(),'screen':self.public_screen(screen),'screenshot':self.screenshot(screen,step)})
        return matched

    def run(self)->dict[str,Any]:
        screen=None
        try:
            self.device.launch(self.config.package)
            screen=self.device.wait_for_content(20)
            initial=self.screenshot(screen,0)
            self.history.append({'step':0,'elapsed_ms':self.elapsed_ms(),'operation':'OBSERVE','screen':self.public_screen(screen),'screenshot':initial})
            if GUARD_TEXT in screen.text:
                return self.write_result('Execution error','The app blocks rooted devices and emulators before authentication. Use a permitted physical device or emulator-enabled UAT build.',screen)
            goal_text=str(self.config.test_case.get('goal','')).strip()
            assertion=self.config.expected_text.strip()
            verification_only=(not str(self.config.test_case.get('steps','')).strip() and re.match(r'^(verify|confirm|check|observe)\b',goal_text,re.I))
            if verification_only:
                matched=self.verify_result(screen,1)
                if matched:return self.write_result('Passed',f'Exact visible-text assertion passed: {assertion}',screen)
                if assertion:return self.write_result('Failed',f'Exact visible-text assertion failed. Expected on screen: {assertion}',screen)
                return self.write_result('Inconclusive','This verification case has no exact visible-text assertion.',screen)
            goal=self.redact(f"{self.config.test_case.get('goal','')}\nSteps:\n{self.config.test_case.get('steps','')}\nExpected:\n{self.config.test_case.get('expected','')}")
            for step in range(1,self.config.max_steps+1):
                if time.monotonic()-self.started>self.config.timeout_seconds:
                    return self.write_result('Execution error','Runner time limit reached.',screen)
                foreground=self.device.foreground()
                if foreground=='com.android.credentialmanager':
                    prompt=self.device.observe()
                    cancel=next((e for e in prompt.elements if e.label.casefold()=='cancel' and 'TAP' in e.operations),None)
                    known_prompt='Google Password Manager' in prompt.text or 'Save password for UAT-AI Avatar?' in prompt.text
                    if not known_prompt or not cancel:
                        return self.write_result('Execution error','An unrecognized Android credential prompt interrupted the app.',prompt)
                    self.device.tap(cancel)
                    screen=self.device.wait_for_change(prompt,4)
                    self.history.append({'step':step,'elapsed_ms':self.elapsed_ms(),'operation':'DISMISS_SAVED_PASSWORD','screen':self.public_screen(screen),'screenshot':self.screenshot(screen,step)})
                    continue
                if foreground and foreground!=self.config.package:
                    return self.write_result('Execution error',f'App left the allowed package; foreground is {foreground}.',screen)
                tutorial_visible=bool(COMPANION_TUTORIAL.search(screen.text))
                if tutorial_visible and self.tutorial_swipe_attempted:
                    return self.write_result('Inconclusive','The upward swipe did not advance past the companion tutorial; stopped before tapping covered feed controls.',screen)
                public=self.public_screen(screen)
                decision=choose(screen.elements,public['text'],goal,self.history)
                op=decision['operation']
                if tutorial_visible and op!='SWIPE_UP':
                    return self.write_result('Inconclusive','The tutorial overlay is visible; stopped before tapping covered feed controls because its required upward swipe was not selected.',screen)
                if tutorial_visible:
                    self.tutorial_swipe_attempted=True
                selected=next((e for e in screen.elements if e.index==decision['target']),None)
                entry={'step':step,'elapsed_ms':self.elapsed_ms(),'operation':op,'target':decision['target'],'label':self.redact(selected.label) if selected else None,'resource_id':selected.resource_id if selected else None,'confidence':decision['confidence'],'model':decision['model'],'latency_ms':decision['latency_ms'],'before_fingerprint':screen.fingerprint,'jev':self.redact_object(decision['jev'])}
                if op=='DONE':
                    final=self.device.observe()
                    entry['screen']=self.public_screen(final)
                    entry['screenshot']=self.screenshot(final,step)
                    self.history.append(entry)
                    if self.verify_result(final,step+1):
                        return self.write_result('Passed',f'Exact visible-text assertion passed: {self.config.expected_text.strip()}',final)
                    if not self.config.expected_text.strip():
                        return self.write_result('Inconclusive','The agent declared DONE, but this case has no exact visible-text assertion.',final)
                    return self.write_result('Failed',f'Exact visible-text assertion failed. Expected on screen: {self.config.expected_text.strip()}',final)
                if op=='BLOCKED':
                    self.history.append(entry)
                    return self.write_result('Inconclusive','The agent could not progress using observed controls.',screen)
                if op in {'TAP','TYPE_TEXT'} and selected and self.consent_confirmation_required(selected.label,public['text']) and not self.config.allow_consent:
                    entry['blocked_by_safety']='explicit user confirmation required for a legal or consent action'
                    self.history.append(entry)
                    return self.write_result('Inconclusive','Stopped before a legal or consent action. Explicit user confirmation is required to proceed.',screen)
                if selected and RISKY.search(selected.label):
                    self.history.append(entry)
                    return self.write_result('Execution error',f'Runner stopped before a consequential control: {selected.label}',screen)
                if op in {'TAP','TYPE_TEXT'} and selected and self.repeated_without_progress(op,selected,screen):
                    entry['blocked_by_safety']='same action repeated without an observable screen change'
                    self.history.append(entry)
                    return self.write_result('Inconclusive',f'Stopped before repeating {op} on {selected.label!r}; the prior action produced no observable screen change.',screen)
                if op in {'TAP','TYPE_TEXT'}:
                    fresh=self.device.observe()
                    same=next((e for e in fresh.elements if e.signature==selected.signature and op in e.operations),None) if selected else None
                    if not same:
                        entry['stale']=True
                        self.history.append(entry)
                        screen=fresh
                        continue
                    if op=='TAP':self.device.tap(same)
                    else:
                        if not same.focused:
                            self.device.tap(same)
                            focused_screen=self.device.observe()
                            if self.device.foreground()=='com.android.credentialmanager':
                                cancel=next((e for e in focused_screen.elements if e.label.casefold()=='cancel' and 'TAP' in e.operations),None)
                                known_prompt='Google Password Manager' in focused_screen.text or 'Save password for UAT-AI Avatar?' in focused_screen.text
                                if not known_prompt or not cancel:
                                    raise DeviceError('An unrecognized Android credential prompt interrupted text entry.')
                                self.device.tap(cancel)
                                focused_screen=self.device.wait_for_change(focused_screen,4)
                            focused_field=self.focused_text_field(focused_screen,same)
                            if not focused_field:
                                raise DeviceError('The intended text field did not gain focus.')
                            same=focused_field
                        credential=self.credential_for(same,fresh)
                        if credential:
                            value,kind=credential
                            if not value:
                                self.history.append(entry)
                                return self.write_result('Execution error',f'JEV_TEST_{kind.upper()} is missing from local .env.',screen)
                            self.credential_used=True
                            entry['text_source']=f'local {kind} credential'
                        else:
                            if re.search(r'auth|sign[ -]?in|log[ -]?in|password|credential', goal, re.I):
                                raise DeviceError('Could not identify this authentication field as email or password; no account value was sent to a text model.')
                            value=field_text(goal,same,public['text'],self.history)
                            entry['text_source']='text model'
                            entry['text']=self.redact(value)
                        self.device.type_text(same,value)
                        # The Samsung IME covers the submit control while editing.
                        # Close it before the next observation so locators refer to tappable UI.
                        self.device.back()
                elif op=='SWIPE_UP':
                    if tutorial_visible:entry['gesture']=self.device.swipe_companion_next_item(screen.width,screen.height)
                    else:self.device.swipe('up',screen.width,screen.height)
                elif op=='SWIPE_DOWN':self.device.swipe('down',screen.width,screen.height)
                elif op=='BACK':self.device.back()
                elif op=='WAIT':time.sleep(.7)
                else:raise ModelError(f'Unsupported operation: {op}')
                next_screen=self.wait(screen,4 if op!='WAIT' else 1)
                entry['after_fingerprint']=next_screen.fingerprint
                entry['page_changed']=next_screen.fingerprint!=screen.fingerprint
                entry['elapsed_ms']=self.elapsed_ms()
                entry['screen']=self.public_screen(next_screen)
                entry['screenshot']=self.screenshot(next_screen,step)
                self.history.append(entry)
                screen=next_screen
                if GUARD_TEXT in screen.text:
                    return self.write_result('Execution error','The app rejected this emulator before authentication.',screen)
            return self.write_result('Inconclusive',f'Maximum {self.config.max_steps} actions reached without a verified outcome.',screen)
        except (DeviceError,ModelError,OSError,ValueError) as exc:
            return self.write_result('Execution error',str(exc),screen)
