"""Run session: owns device, evidence, and verification state, and drives the node pipeline.

The observe → choose → re-observe → act loop itself is the engine pipeline (see engine/).
"""
from __future__ import annotations
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date,datetime,timezone
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Callable
from .config import ROOT,getenv
from .device import AndroidDevice, DeviceError, Element, Screen
from .model import ModelError, choose, field_text
from .checkpoints import validate_checkpoints, evaluate as evaluate_checkpoints
from .starting_conditions import validate_starting_conditions, check_starting_conditions
from .execution_contract import check_support, validate_authorizations, fingerprint
from .execution_runtime import Boundary, Protocol, ExecutionBlocked, ObservationIncomplete
from .capabilities import BUILD_IDENTITY
from .device_lease import DeviceLease

# Re-exported for existing importers; the policy lives in safety.py.
from .safety import (GUARD_TEXT, RISKY, CONSENT_GATE, CONSENT_ACTION, EMAIL_VALUE, EMAIL_FIELD, PASSWORD_FIELD,
    PRIVATE_CODE_FIELD, SWIPE_INSTRUCTION, DATE_OF_BIRTH_GATE, SELECTED_DATE_LABEL, DATE_VALUE)
from .engine import RunContext, build_pipeline

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
    mcp_host_text:bool=False
    on_progress:Callable[[list[dict[str,Any]]],None]|None=None
    should_stop:Callable[[],bool]|None=None
    backend:str=''
    appium_url:str=''
    platform:str=''
    authorizations:dict[str,Any]|None=None

class Agent:
    def __init__(self,config:RunConfig):
        self.config=config
        if config.platform and config.test_case.get('platform') and config.platform!=config.test_case['platform']:raise ValueError('Run platform conflicts with the test case.')
        self.platform=config.platform or config.test_case.get('platform') or 'Android'
        if self.platform not in {'Android','iOS'}:raise ValueError('Platform must be Android or iOS.')
        backend=config.backend or ('appium' if self.platform=='iOS' else getenv('SCOUT_ANDROID_DRIVER') or 'appium')
        if self.platform=='iOS' and backend!='appium':raise ValueError('iOS requires Appium/XCUITest.')
        self.backend=backend
        self.lease=DeviceLease(config.serial)
        self.lease_managed=False
        self.execution=check_support(config.test_case,self.platform,backend)
        self.authorizations=validate_authorizations(config.authorizations,self.execution)
        self.boundary=Boundary(self) if self.execution else None
        self.protocol=None
        self.lifecycle=None
        if self.platform=='iOS':
            from .ios_device import AppiumIOSDevice
            self.device=AppiumIOSDevice(config.serial,config.package,config.appium_url or getenv('SCOUT_APPIUM_URL') or 'http://127.0.0.1:4723')
        elif backend=='appium':
            from .appium_device import AppiumAndroidDevice
            self.device=AppiumAndroidDevice(config.serial,config.adb,config.appium_url or getenv('SCOUT_APPIUM_URL') or 'http://127.0.0.1:4723')
        elif backend=='adb':
            self.device=AndroidDevice(config.serial,config.adb)
        else:
            raise ValueError('SCOUT_ANDROID_DRIVER must be adb or appium.')
        self.history:list[dict[str,Any]]=[]
        self.checkpoints=validate_checkpoints(config.test_case.get('checkpoints', []))
        self.starting_conditions=validate_starting_conditions(config.test_case.get('starting_conditions'))
        self.starting_condition_results=[]
        self.checkpoint_observations=[]
        self.checkpoint_verdicts={item['id']:{**item,'verdict':'not_reached','confidence':0.0,'reason':'Checkpoint has not been evaluated.','evidence_steps':[],'observed':''} for item in self.checkpoints}
        self.started=time.monotonic()
        self.sandbox_session=None
        self.credential_used=False
        self.instruction_swipe_attempted=False
        self.date_gate_attempted=False
        self.verification={'status':'not_run','method':'exact_visible_text','expected_text':config.expected_text,'observed_text':''}
        self.output=config.output
        self.output.mkdir(parents=True,exist_ok=True)
        self.test_email=config.test_email or getenv('SCOUT_TEST_EMAIL','')
        self.test_password=config.test_password or getenv('SCOUT_TEST_PASSWORD','')
        self.secrets=[s for s in (self.test_email,self.test_password) if s]
        if self.execution and self.redact_object(self.execution)!=self.execution:
            raise ValueError('Execution definitions cannot contain locally configured credential values.')
        self.checkpoints=self.redact_object(self.checkpoints)
        self.checkpoint_verdicts=self.redact_object(self.checkpoint_verdicts)
        self._continuation=None
        self._pending_text=False
        self._pause_started:float|None=None
        self._evidence_pool:ThreadPoolExecutor|None=None
        self._pending_screenshots:list[tuple[str,Future]]=[]
        if self.execution:
            from .lifecycle import Lifecycle
            self.protocol=Protocol(self)
            self.lifecycle=Lifecycle(self)
        self.pipeline=build_pipeline()

    # Model seams. Nodes call these so the model client stays swappable (and patchable in tests).
    def decide(self,*args:Any,**kwargs:Any)->dict[str,Any]:return choose(*args,**kwargs)

    def generate_text(self,*args:Any,**kwargs:Any)->str:return field_text(*args,**kwargs)

    def elapsed_ms(self)->int:return round((time.monotonic()-self.started)*1000)

    def device_timing_details(self,name:str)->dict[str,int]:
        value=getattr(self.device,name,{})
        return dict(value) if isinstance(value,dict) else {}

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

    def screenshot_path(self,screen:Screen,index:int)->Path|None:
        """Privacy policy for evidence capture: the destination path, or None when this screen must not be captured."""
        if self.platform=='iOS' and not self.device.capture_safe(screen):return None
        # Once credentials are used, capture only screens with no input fields or visible account values.
        if 'Google Password Manager' in screen.text or 'Save password for UAT-AI Avatar?' in screen.text or any(secret in screen.xml for secret in self.secrets):return None
        # A focused credential field may show unrelated personal suggestions in the keyboard before typing.
        if any(e.focused and e.sensitive for e in screen.elements):return None
        # Avoid capturing transition/loading frames with an empty accessibility tree after login input.
        if self.credential_used and not screen.text.strip() and not screen.elements:return None
        if self.credential_used and (any(e.role=='textbox' for e in screen.elements) or EMAIL_VALUE.search(screen.text)):
            return None
        return self.output/f'{index:03d}.png'

    def screenshot(self,screen:Screen,index:int)->str|None:
        path=self.screenshot_path(screen,index)
        if path is None:return None
        self.device.screenshot(path)
        return path.name

    def screenshot_deferred(self,screen:Screen,index:int)->str|None:
        """Capture in the background; flush_screenshots() must run before the next device action.

        After a credential is used, capture stays synchronous so nothing can change between the
        privacy check and the capture.
        """
        if self.credential_used:return self.screenshot(screen,index)
        path=self.screenshot_path(screen,index)
        if path is None:return None
        if self._evidence_pool is None:self._evidence_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='scout-evidence')
        self._pending_screenshots.append((path.name,self._evidence_pool.submit(self._capture,path)))
        return path.name

    def _capture(self,path:Path)->None:
        # Write then rename so a live viewer never reads a partial PNG.
        partial=path.with_name(path.name+'.part')
        try:
            self.device.screenshot(partial)
            partial.replace(path)
        finally:
            partial.unlink(missing_ok=True)

    def flush_screenshots(self,raise_errors:bool=True)->list[str]:
        """Wait for deferred captures. Returns failures, or raises the first one."""
        pending,self._pending_screenshots=self._pending_screenshots,[]
        failures=[]
        for name,future in pending:
            try:future.result()
            except (DeviceError,OSError) as exc:
                if raise_errors:
                    self.flush_screenshots(raise_errors=False)
                    raise DeviceError(f'Screenshot {name} could not be captured: {exc}') from None
                failures.append(f'{name}: {exc}')
        return failures

    def close_evidence(self)->None:
        self.flush_screenshots(raise_errors=False)
        if self._evidence_pool is not None:
            self._evidence_pool.shutdown(wait=True)
            self._evidence_pool=None

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
    def screen_cycle(fingerprints:list[str],max_period:int=4)->int|None:
        """Return a navigation cycle only after observing it three times."""
        for period in range(2,min(max_period,len(fingerprints)//2)+1):
            if len(fingerprints)>=period*3 and fingerprints[-period:]==fingerprints[-2*period:-period]:
                return period
        return None

    def recent_screen_cycle(self,screen:Screen)->int|None:
        fingerprints=[]
        # Keep enough observations to confirm the longest supported cycle three times.
        for entry in self.history[-12:]:
            fingerprint=entry.get('after_fingerprint') or entry.get('screen',{}).get('fingerprint')
            if fingerprint:fingerprints.append(fingerprint)
        if not fingerprints or fingerprints[-1]!=screen.fingerprint:
            fingerprints.append(screen.fingerprint)
        return self.screen_cycle(fingerprints)

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
        if re.fullmatch(r'\s*save\s*',label,re.I) and re.search(r'by\s+saving.{0,80}\bi\s+agree\b',screen_text,re.I):
            return True
        return bool(CONSENT_GATE.search(screen_text) and CONSENT_ACTION.fullmatch(label))

    @staticmethod
    def _selected_date(screen:Screen)->date|None:
        for element in screen.elements:
            if not element.checked:
                continue
            match=SELECTED_DATE_LABEL.search(element.label)
            if not match:
                continue
            try:return datetime.strptime(match.group(1),'%B %d, %Y').date()
            except ValueError:continue
        return None

    def _base_date_gate_step(self,screen:Screen)->Screen|None:
        """Complete a date-of-birth gate with its already-selected value, once."""
        if self.platform=='iOS':return None  # Native picker values follow explicit case instructions.
        if self.date_gate_attempted:
            return None
        if not DATE_OF_BIRTH_GATE.search(screen.text) or not re.search(r'\b(?:save|continue|submit)\b',screen.text,re.I):
            return None
        submit_label=next((label for label in ('Save','Continue','Submit') if re.search(rf'\b{label}\b',screen.text,re.I)), 'Save')
        if self.consent_confirmation_required(submit_label,screen.text) and not self.config.allow_consent:
            return None
        self.flush_screenshots()
        self.date_gate_attempted=True

        def tap_and_wait(current:Screen,element:Element,stage:str)->Screen:
            before=current
            self.device.tap(element)
            following=self.wait(before,5)
            record={'step':len(self.history),'elapsed_ms':self.elapsed_ms(),'operation':'BASE_STEP_TAP','label':element.label,'target':element.index,'base_step':'Date gate: '+stage,'before_fingerprint':before.fingerprint,'after_fingerprint':following.fingerprint,'page_changed':before.fingerprint!=following.fingerprint,'screen':self.public_screen(following)}
            record['screenshot']=self.screenshot(following,len(self.history)+1)
            self.history.append(record)
            return following

        current=screen
        selected_date=None
        date_value=DATE_VALUE.search(current.text)
        if date_value:
            try:selected_date=date(*(int(part) for part in date_value.groups()))
            except ValueError:raise DeviceError('The displayed date is invalid; submit was not pressed.') from None
        else:
            field=next((e for e in current.elements if DATE_OF_BIRTH_GATE.search(e.label) and 'TAP' in e.operations),None)
            if not field:
                raise DeviceError('Date-of-birth gate is visible but its date field is not actionable; no date was entered.')
            picker=tap_and_wait(current,field,'open date picker')
            selected_date=self._selected_date(picker)
            if not selected_date:
                raise DeviceError('Date picker has no preselected date; Jev will not guess or scroll through dates.')
            confirm=next((e for e in picker.elements if e.label.casefold()=='confirm' and 'TAP' in e.operations),None)
            if not confirm:
                raise DeviceError('Birthday picker has no enabled Confirm action; no date was saved.')
            current=tap_and_wait(picker,confirm,f'confirm preselected date {selected_date.isoformat()}')

        visible_date=DATE_VALUE.search(current.text)
        if not visible_date or tuple(map(int,visible_date.groups()))!=(selected_date.year,selected_date.month,selected_date.day):
            raise DeviceError('The form did not show the confirmed date; no date was saved and submit was not pressed.')
        save=next((e for e in current.elements if e.label.casefold() in {'save','continue','submit'} and 'TAP' in e.operations),None)
        if not save:
            raise DeviceError('Date was selected, but submit is still disabled; stopping without repeating date entry.')
        if self.consent_confirmation_required(save.label,current.text) and not self.config.allow_consent:
            raise DeviceError('Submitting the date also accepts Terms/Privacy consent; this run is not authorized to continue.')
        return tap_and_wait(current,save,f'submit confirmed date {selected_date.isoformat()}')

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
        missing=self.flush_screenshots(raise_errors=False)
        if missing:reason+=' Evidence: screenshot capture failed for '+'; '.join(missing)[:500]+'.'
        if self.checkpoints:
            if status not in {'Execution error','Blocked'} and (status=='Passed' or self.checkpoint_outcome()=='Failed'):status=self.checkpoint_outcome()
            reason=reason+' Checkpoints: '+', '.join(item['id']+'='+item['verdict'] for item in self.checkpoint_verdicts.values())
            self.history.append({'step':max((item['step'] for item in self.history),default=-1)+1,'elapsed_ms':self.elapsed_ms(),'operation':'VERIFY_CHECKPOINTS','checkpoint_results':list(self.checkpoint_verdicts.values()),'screenshot':None})
        if self.execution and status not in {'Blocked','Execution error'}:
            from .media_verification import verify_metadata
            existing={r['id'] for r in self.protocol.results if r.get('verifier')}
            self.protocol.results.extend(verify_metadata(self.output,[r for r in self.execution['media_assertions'] if r['id'] not in existing]))
            temporal=self.protocol.outcome()
            media=[r for r in self.protocol.results if r.get('verifier') and r['required']]
            if temporal=='Failed' or any(r['verdict']=='violated' for r in media):status='Failed'
            elif status!='Failed' and (temporal=='Inconclusive' or any(r['verdict']!='satisfied' for r in media)):status='Inconclusive'
            self.protocol.save()
        if self.boundary and self.boundary.active and self.boundary.active['require_return'] and status not in {'Blocked','Execution error'}:
            status='Inconclusive';reason+=' Approved external flow has not returned to its expected target screen.'
        sandbox_report=None
        if self.sandbox_session:
            self.sandbox_session.stop()
            sandbox_report=self.sandbox_session.report()
            if sandbox_report['status']!='satisfied' and status not in {'Blocked','Execution error'}:
                status='Inconclusive'
                reason+=' Sandbox evidence incomplete: required rule hits missing or proxy requests blocked. This does not establish an app bug.'
        device_info=self.capture_device_info()
        result={'suite':self.redact(str(case.get('suite','Prompt runs'))),'ticket_key':self.redact(str(case.get('ticket_key',''))),'preconditions':self.redact(str(case.get('preconditions',''))),'starting_conditions':self.redact_object(self.starting_conditions),'starting_condition_results':self.redact_object(self.starting_condition_results),'checkpoints':self.checkpoints,'checkpoint_results':list(self.checkpoint_verdicts.values()),'schema_version':1,'source':'Scout iOS runner' if self.platform=='iOS' else 'Scout Android runner','case_id':case.get('id'),'revision':case.get('revision'),'project':self.redact(str(case.get('project','General'))),'case_title':self.redact(str(case.get('title',''))),'goal':self.redact(str(case.get('goal',''))),'case_steps':self.redact(str(case.get('steps',''))),'expected_result':self.redact(str(case.get('expected',''))),'package':self.config.package,'platform':self.platform,'device':self.config.serial,'build':device_info.get('app_version','unknown'),'device_info':device_info,'app_logs':self.capture_app_logs(),'status':status,'notes':self.redact(reason),'expected_text':self.redact(self.config.expected_text),'observed_text':self.redact(screen.text) if screen else '','verification':self.redact_object(self.verification),'elapsed_ms':self.elapsed_ms(),'steps':self.history,'created':datetime.now(timezone.utc).isoformat(),'credential_values_recorded':False}
        if sandbox_report:
            result['sandbox']=sandbox_report
            result['sandbox_scenario']=self.sandbox_session.scenario
        if self.execution:
            result['reason_code']={'Passed':'verified','Failed':'assertion_violated','Inconclusive':'evidence_incomplete','Blocked':'execution_blocked','Execution error':'runner_error'}.get(status,'unknown')
            result['execution']={'schema_version':2,'contract_fingerprint':fingerprint(self.execution),'definition':self.execution,'component':BUILD_IDENTITY,'assertions':self.protocol.results,'evidence':'execution-evidence.json','cleanup_failed':bool(self.lifecycle.failed)}
        if case.get('matrix'):
            result['matrix']=case['matrix']
        (self.output/'result.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        (self.output/'trace.json').write_text(json.dumps(self.history,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        jev_calls=[{'step':entry['step'],**entry['jev']} for entry in self.history if 'jev' in entry]
        (self.output/'jev-output.json').write_text(json.dumps({'schema_version':1,'source':'Jev decision audit','case_id':case.get('id'),'device':self.config.serial,'calls':jev_calls},indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        return result

    def finalize_evidence(self, result: dict) -> dict:
        if self.lifecycle and self.lifecycle.failed:
            result['original_status']=result['status']
            result['status']='Blocked'
            result['notes']+='\nLifecycle cleanup failed; subsequent runs require reconciliation.'
            result['cleanup_failed']=True
            result['reason_code']='cleanup_failed'
            if result.get('execution'):result['execution']['cleanup_failed']=True
            (self.output/'result.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
        error=getattr(self.device,'recording_error','')
        if error and result.get('status')!='awaiting_input':
            result['notes']=result.get('notes','')+'\nEvidence: '+error
            (self.output/'result.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        return result

    def capture_device_info(self)->dict[str,str]:
        if self.platform=='iOS':
            try:return self.redact_object(self.device.metadata())
            except Exception:return {'package':self.config.package,'automation_backend':self.backend}
        info={'package':self.config.package,'automation_backend':self.backend}
        if self.backend=='appium':info['session_start_ms']=str(self.device.session_start_ms)
        for key,prop in [('manufacturer','ro.product.manufacturer'),('model','ro.product.model'),('android_version','ro.build.version.release'),('api_level','ro.build.version.sdk')]:
            try:info[key]=self.device.command('shell','getprop',prop,timeout=5,check=False).stdout.decode(errors='replace').strip()[:120]
            except Exception:pass
        try:info['screen_size']=self.device.command('shell','wm','size',timeout=5,check=False).stdout.decode(errors='replace').strip().splitlines()[-1][:80]
        except Exception:pass
        try:
            details=self.device.command('shell','dumpsys','package',self.config.package,timeout=10,check=False).stdout.decode(errors='replace')
            match=re.search(r'versionName=([^\s]+)',details)
            if match:info['app_version']=match.group(1)[:120]
        except Exception:pass
        return self.redact_object(info)

    def capture_app_logs(self,max_chars:int=20000)->str:
        """Capture a bounded tail for the app process only; logcat may be unavailable."""
        if self.platform=='iOS':return self.redact(self.device.app_logs(max_chars))[:max_chars]
        try:
            pid=self.device.command('shell','pidof',self.config.package,timeout=5,check=False).stdout.decode(errors='replace').strip().split()
            if not pid or not pid[0].isdigit():return ''
            raw=self.device.command('shell','logcat','-d','-t','300',f'--pid={pid[0]}',timeout=10,check=False).stdout.decode(errors='replace')
            return self.redact(raw[-max_chars:])[:max_chars]
        except Exception:return ''

    def capture_checkpoint_investigation(self)->dict[str,Any]:
        """Record diagnostics while a failed checkpoint's observed state still exists."""
        foreground='unknown'
        running=False
        try:foreground=self.device.foreground()[:240] or 'unknown'
        except Exception:pass
        try:running=self.device.running(self.config.package) if self.platform=='iOS' else bool(self.device.command('shell','pidof',self.config.package,timeout=5,check=False).stdout.strip())
        except Exception:pass
        return {'captured_at':datetime.now(timezone.utc).isoformat(),'elapsed_ms':self.elapsed_ms(),'foreground':self.redact(foreground),'app_process_running':running,'app_logs':self.capture_app_logs(6000)}

    def assess_checkpoints(self,screen:Screen,step:int,final:bool=False)->None:
        if not self.checkpoints:return
        observation={'step':step,'text':self.redact(screen.text)[:8000], 'elements':self.public_screen(screen)['elements'][:40]}
        self.checkpoint_observations.append(observation)
        self.checkpoint_observations=self.checkpoint_observations[-8:]
        active=[item for item in self.checkpoints if not (item['scope']=='during_run' and self.checkpoint_verdicts[item['id']]['verdict'] in {'satisfied','violated'})]
        try:
            results=evaluate_checkpoints(active,self.checkpoint_observations,self.redact(str(self.config.test_case.get('goal',''))),final)
        except ModelError as exc:
            results=[{**item,'verdict':'not_observable','confidence':0.0,'reason':self.redact(str(exc)),'evidence_steps':[],'observed':''} for item in active if final or item['scope']=='during_run']
        investigation=None
        for result in results:
            if result['verdict']=='violated':
                if investigation is None:investigation=self.capture_checkpoint_investigation()
                result['investigation']=investigation
            self.checkpoint_verdicts[result['id']]=self.redact_object(result)

    def during_run_requirements_met(self)->bool:
        """True when the case has required during-run checkpoints and every one of them is already satisfied."""
        during=[self.checkpoint_verdicts[item['id']]['verdict'] for item in self.checkpoints if item['required'] and item['scope']=='during_run']
        return bool(during) and all(verdict=='satisfied' for verdict in during)

    def checkpoint_outcome(self)->str:
        required=[value for value in self.checkpoint_verdicts.values() if value['required']]
        if any(value['verdict']=='violated' for value in required):return 'Failed'
        if required and all(value['verdict']=='satisfied' for value in required):return 'Passed'
        return 'Inconclusive'

    def verify_result(self,screen:Screen,step:int,timings_ms:dict[str,int]|None=None)->bool:
        if self.checkpoints:
            self.verify_checkpoint_final(screen,step)
            return self.checkpoint_outcome()=='Passed'
        expected=self.config.expected_text.strip()
        observed=self.redact(screen.text)[:8000]
        matched=bool(expected and expected.casefold() in screen.text.casefold())
        status='passed' if matched else 'failed' if expected else 'inconclusive'
        self.verification={'status':status,'method':'exact_visible_text','expected_text':self.redact(expected),'observed_text':observed}
        started=time.perf_counter()
        screenshot=self.screenshot(screen,step)
        phases=dict(timings_ms or {})
        phases['screenshot_ms']=round((time.perf_counter()-started)*1000)
        self.history.append({'step':step,'elapsed_ms':self.elapsed_ms(),'operation':'VERIFY_RESULT','verification':self.verification.copy(),'screen':self.public_screen(screen),'screenshot':screenshot,'timings_ms':phases})
        return matched

    def verify_checkpoint_final(self,screen:Screen,step:int)->None:
        self.history.append({'step':step,'elapsed_ms':self.elapsed_ms(),'operation':'VERIFY_RESULT','screen':self.public_screen(screen),'screenshot':self.screenshot(screen,step)})
        self.assess_checkpoints(screen,step,True)
        self.verification={'status':self.checkpoint_outcome().lower(),'method':'checkpoint_evidence','expected_text':'; '.join(item['expected'] for item in self.checkpoints if item['required'])[:8000],'observed_text':self.redact(screen.text)[:8000]}
        self.history[-1]['verification']=self.verification.copy()

    def run(self)->dict[str,Any]:
        if self._continuation is not None:
            raise ModelError('This Scout run is paused; continue it with resume_text().')
        self._continuation=self._run_loop()
        return self._advance(start=True)

    def resume_text(self,value:str)->dict[str,Any]:
        if self._continuation is None or not self._pending_text:
            raise ModelError('This Scout run is not waiting for text input.')
        if not isinstance(value,str) or not value.strip() or len(value)>200:
            raise ModelError('Text input must contain 1–200 characters.')
        return self._advance(value)

    def _advance(self,value:str|None=None,start:bool=False)->dict[str,Any]:
        try:
            return next(self._continuation) if start else self._continuation.send(value)
        except StopIteration as finished:
            self._continuation=None
            self._pending_text=False
            return self.finalize_evidence(finished.value) if self.execution and not self.lease_managed else finished.value

    def _save_partial_trace(self,entries:list[dict[str,Any]]|None=None)->None:
        entries=entries if entries is not None else self.history
        (self.output/'trace.json').write_text(json.dumps(entries,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        jev_calls=[{'step':entry['step'],**entry['jev']} for entry in entries if 'jev' in entry]
        (self.output/'jev-output.json').write_text(json.dumps({'schema_version':1,'source':'Jev decision audit','case_id':self.config.test_case.get('id'),'device':self.config.serial,'calls':jev_calls},indent=2,ensure_ascii=False)+'\n',encoding='utf-8')

    def _run_loop(self)->dict[str,Any]:
        ctx=RunContext(self)
        try:
            return (yield from self.pipeline.run(ctx))
        except ExecutionBlocked as exc:
            return self.write_result('Blocked',str(exc),ctx.screen)
        except ObservationIncomplete as exc:
            return self.write_result('Inconclusive',str(exc),ctx.screen)
        except (DeviceError,ModelError,OSError,ValueError) as exc:
            return self.write_result('Execution error',str(exc),ctx.screen)
        finally:
            self.pipeline.teardown(ctx)
