"""Bridge-owned saved-case regressions with pinned revisions and durable summaries."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import threading
import time
import uuid
from urllib.parse import urlencode
from .config import ROOT,getenv
from .dashboard_client import DashboardClient, sync_run
from . import dashboard_jobs
from .devices import connected
from .execution_contract import check_support, validate_authorizations
from .capabilities import capabilities, negotiate_case

STORE = ROOT/'runner-output'/'.library-sessions'
ID = r'^[A-Za-z0-9_-]{1,80}$'


class Sessions:
    def __init__(self):
        self.lock=threading.RLock()
        self.items={}

    def persist(self, session):
        STORE.mkdir(parents=True,exist_ok=True)
        path=STORE/(session['session_id']+'.json')
        temporary=path.with_suffix('.tmp')
        temporary.write_text(json.dumps({k:v for k,v in session.items() if not k.startswith('_')},ensure_ascii=False),encoding='utf-8')
        temporary.replace(path)

    def publish_matrix(self, session, client):
        if session.get('kind') != 'matrix':return
        with self.lock:
            summary={k:session[k] for k in ('status','current_case_index','active_run_id','skipped_entry_ids','stop_reason','error','finished_at') if k in session}
            summary['outcomes']=[{k:r[k] for k in ('entry_id','case_id','revision','run_id','status','dashboard_run_id','runner_error','sync_error','evidence_failures') if k in r} for r in session['outcomes']]
        try:
            client.request('/api/scenario-matrices',{'action':'progress','workspace_id':session['workspace_id'],
                           'batch_id':session['request_id'],'summary':summary})
            session.pop('report_sync_error',None)
        except (ValueError,OSError):
            session['report_sync_error']='Matrix progress could not sync. Child results and frozen definitions remain local.'

    def start(self, packet, run_lock):
        request_id=packet.get('request_id')
        if not isinstance(request_id,str):raise ValueError('A UUID request_id is required for safe start retries.')
        session_id='session-'+uuid.UUID(request_id).hex
        signature=hashlib.sha256(json.dumps(packet,sort_keys=True).encode()).hexdigest()
        existing=self.snapshot(session_id)
        if existing:
            if existing.get('request_signature')!=signature:
                raise ValueError('Request ID already has different settings. Use a new request ID for a new run.')
            return existing
        if packet.get('conditions_confirmed') is not True:
            raise ValueError('Review and confirm prerequisites before running. Device checks still determine whether they are met.')
        client=DashboardClient(packet['dashboard_url'])
        if not isinstance(packet.get('workspace_id'),str):raise ValueError('Workspace ID is required.')
        uuid.UUID(packet['workspace_id'])
        mode,limit,consent=packet.get('start_mode','current'),packet.get('max_steps',40),packet.get('allow_consent',False)
        if mode not in {'current','relaunch'} or type(limit) is not int or not 1<=limit<=100 or type(consent) is not bool:
            raise ValueError('Invalid start mode, action limit, or consent setting.')
        matrix_id=packet.get('matrix_id')
        if matrix_id:
            uuid.UUID(matrix_id)
            if packet.get('cases') is not None or mode!='relaunch' or type(packet.get('continue_on_failure',False)) is not bool:
                raise ValueError('Matrix runs require relaunch mode and a boolean continue_on_failure; do not also supply cases.')
            if any(type(packet.get(k)) is not int or packet[k]<1 for k in ('expected_matrix_revision','expected_case_revision')):
                raise ValueError('Review and specify the matrix and base case revisions before running.')
            preview=client.request('/api/scenario-matrices?'+urlencode({'workspace':packet['workspace_id'],'id':matrix_id}))
            cases=[preview['case']]
        else:
            selected=packet.get('cases')
            if not isinstance(selected,list) or not 1<=len(selected)<=100:
                raise ValueError('Select 1–100 saved cases in execution order.')
            cases=client.request('/api/library',{'action':'freeze','workspace':packet['workspace_id'],'cases':selected,'runner_capabilities':capabilities()})['cases']
        platform=cases[0]['platform']
        if any(c['platform']!=platform or not re.fullmatch(r'[A-Za-z0-9_.]{3,240}',c['app_id']) for c in cases):
            raise ValueError('Select one platform and set an app package or bundle ID on every case.')
        grants=packet.get('authorizations') or {}
        if not isinstance(grants,dict):raise ValueError('Authorizations must be a per-case-ID mapping.')
        if set(grants)-{c['id'] for c in cases}:raise ValueError('Authorizations refer to an unselected case.')
        for c in cases:
            execution=check_support(c,platform,getenv('SCOUT_ANDROID_DRIVER') or 'appium')
            negotiate_case(c,execution,packet.get('client_capabilities'))
            validate_authorizations(grants.get(c['id']),execution)
        serial=packet.get('serial')
        if not isinstance(serial,str) or serial not in connected(platform,getenv('ADB_PATH') or 'adb'):
            raise ValueError('Choose an authorized connected device for this platform. Never guess when several devices are available.')
        if not run_lock.acquire(blocking=False):
            raise ValueError('Another run or regression is active. Wait for it to finish.')
        session=None
        try:
            matrix=None
            if matrix_id:
                matrix=client.request('/api/scenario-matrices',{'action':'freeze','runner_capabilities':capabilities(),'workspace_id':packet['workspace_id'],
                    'matrix_id':matrix_id,'batch_id':request_id,'request_signature':signature,
                    'expected_revision':packet['expected_matrix_revision'],'expected_case_revision':packet['expected_case_revision'],
                    **({'variant_ids':packet['variant_ids']} if packet.get('variant_ids') is not None else {}),
                    'settings':{'serial':serial,'max_steps':limit,'start_mode':mode,'allow_consent':consent,
                                'continue_on_failure':packet.get('continue_on_failure',False),'conditions_confirmed':True}})
                cases=matrix['cases']
                for c in cases:
                    execution=check_support(c,platform,getenv('SCOUT_ANDROID_DRIVER') or 'appium')
                    negotiate_case(c,execution,packet.get('client_capabilities'));validate_authorizations(grants.get(c['id']),execution)
            session={'session_id':session_id,'workspace_id':packet['workspace_id'],'dashboard_url':client.url,
                     'request_id':request_id,'request_signature':signature,'kind':'matrix' if matrix else 'regression',
                     'status':'running','started_at':datetime.now(timezone.utc).isoformat(),'serial':serial,
                     'start_mode':mode,'cases':[{'id':c['id'],'revision':c['revision'],'title':c['title'],
                                              'entry_id':c.get('matrix',{}).get('variant_id',c['id']),
                                              'variant_label':c.get('matrix',{}).get('variant_label','')} for c in cases],
                     'total_cases':len(cases),'current_case_index':0,'active_run_id':None,'outcomes':[],
                     'max_steps':limit,'allow_consent':consent,'conditions_confirmed':True,'authorizations':grants,
                     'continue_on_failure':packet.get('continue_on_failure',False) if matrix else False,
                     'skipped_case_ids':[],'skipped_entry_ids':[],'_stop':threading.Event(),'_client':client}
            if matrix:session.update(matrix_id=matrix_id,matrix_revision=matrix['matrix_revision'],matrix_name=matrix['matrix_name'])
            with self.lock:
                for key in list(self.items):
                    if len(self.items)<100:break
                    if self.items[key]['status'] not in {'running','awaiting_input','stopping'}:
                        del self.items[key]
                self.items[session_id]=session
                self.persist(session)
            threading.Thread(target=self.worker,args=(session,cases,client,mode,limit,consent,run_lock),daemon=True).start()
        except Exception:
            with self.lock:
                self.items.pop(session_id,None)
            run_lock.release()
            raise
        return self.snapshot(session_id)

    def worker(self,session,cases,client,mode,limit,consent,run_lock):
        try:
            self.publish_matrix(session,client)
            for index,case in enumerate(cases):
                with self.lock:
                    if session['_stop'].is_set():
                        break
                    run_id=dashboard_jobs.start({'case':case,'serial':session['serial'],'start_mode':mode,
                                                'max_steps':limit,'allow_consent':consent,'conditions_confirmed':True,
                                                'retain_saved_case':True,'client_capabilities':capabilities(case['platform'],getenv('SCOUT_ANDROID_DRIVER') or 'appium'),'authorizations':session.get('authorizations',{}).get(case['id'])},threading.Lock())
                    session.update(current_case_index=index,active_run_id=run_id)
                    self.persist(session)
                self.publish_matrix(session,client)
                last_status=None
                while True:
                    job=dashboard_jobs.snapshot(run_id)
                    if not job:
                        raise ValueError('The active run disappeared. Completed results remain in runner-output.')
                    with self.lock:
                        session['status']='stopping' if session['_stop'].is_set() else job['status'] if job['status'] in {'running','awaiting_input'} else 'running'
                    if session['status']!=last_status:
                        last_status=session['status']
                        self.publish_matrix(session,client)
                    if session['_stop'].is_set() and job['status'] in {'running','awaiting_input'}:
                        try:dashboard_jobs.respond(run_id,None,True)
                        except ValueError:pass
                    if job['status'] in {'completed','error'} and job.get('cleanup_complete',True):
                        break
                    time.sleep(0.4)
                outcome={'case_id':case['id'],'entry_id':case.get('matrix',{}).get('variant_id',case['id']),'revision':case['revision'],'run_id':run_id,
                         'status':job.get('result',{}).get('status','Execution error')}
                if job['status']=='error':
                    outcome['runner_error']=job.get('error','Runner failed.')
                else:
                    try:outcome.update(sync_run(client,run_id,session['workspace_id']))
                    except (OSError,ValueError,KeyError):
                        outcome['sync_error']='Result retained locally. Retry sync_run_result for this run.'
                if job.get('cleanup_error'):
                    outcome['runner_error']=job['cleanup_error']
                with self.lock:
                    session['outcomes'].append(outcome)
                    self.persist(session)
                self.publish_matrix(session,client)
                network_invalid=session['kind']=='matrix' and job.get('result',{}).get('sandbox',{}).get('status')!='satisfied'
                if outcome.get('sync_error') or outcome.get('runner_error') or outcome['status'] in {'Blocked','Execution error'} or network_invalid or (outcome['status']!='Passed' and not session['continue_on_failure']):
                    session['stop_reason']='sync_failed' if outcome.get('sync_error') else 'runner_error' if outcome.get('runner_error') or outcome['status']=='Execution error' else 'starting_conditions_blocked' if outcome['status']=='Blocked' else 'sandbox_unverified' if network_invalid else 'non_passing_case'
                    break
            with self.lock:
                completed={row['entry_id'] for row in session['outcomes']}
                session.update(status='stopped' if session['_stop'].is_set() else 'completed',
                               skipped_case_ids=[c['id'] for c in cases if c.get('matrix',{}).get('variant_id',c['id']) not in completed],
                               skipped_entry_ids=[c.get('matrix',{}).get('variant_id',c['id']) for c in cases if c.get('matrix',{}).get('variant_id',c['id']) not in completed],
                               finished_at=datetime.now(timezone.utc).isoformat())
                self.persist(session)
        except Exception as exc:
            with self.lock:
                completed={r['entry_id'] for r in session['outcomes']}
                session.update(status='error',error=str(exc)[:500],finished_at=datetime.now(timezone.utc).isoformat(),
                               skipped_case_ids=[c['id'] for c in cases if c.get('matrix',{}).get('variant_id',c['id']) not in completed],
                               skipped_entry_ids=[c.get('matrix',{}).get('variant_id',c['id']) for c in cases if c.get('matrix',{}).get('variant_id',c['id']) not in completed])
                self.persist(session)
        finally:
            try:
                self.publish_matrix(session,client)
                with self.lock:self.persist(session)
            except (OSError,ValueError):
                pass
            active=session.get('active_run_id')
            if active:
                job=dashboard_jobs.snapshot(active)
                if job and not job.get('cleanup_complete',True):
                    try:dashboard_jobs.respond(active,None,True)
                    except ValueError:pass
                    while not (dashboard_jobs.snapshot(active) or {}).get('cleanup_complete',True):
                        time.sleep(0.4)
            run_lock.release()

    def snapshot(self,session_id):
        if not re.fullmatch(ID,session_id):
            raise ValueError('Invalid session ID.')
        with self.lock:
            session=self.items.get(session_id)
            if session:
                value=json.loads(json.dumps({k:v for k,v in session.items() if not k.startswith('_')}))
            else:
                path=STORE/(session_id+'.json')
                if not path.is_file():
                    return None
                value=json.loads(path.read_text())
                if value['status'] in {'running','awaiting_input','stopping'}:
                    value.update(status='interrupted',error='The bridge restarted. Completed child results can be synced; execution is not resumed automatically.')
                    if value.get('kind')=='matrix':
                        value['skipped_entry_ids']=[c['entry_id'] for c in value['cases'] if c['entry_id'] not in {r['entry_id'] for r in value['outcomes']}]
                        self.publish_matrix(value,DashboardClient(value['dashboard_url']))
                        self.persist(value)
        if value.get('active_run_id'):
            job=dashboard_jobs.snapshot(value['active_run_id'])
            if job:
                value.update(steps=job.get('steps',[])[-20:],checkpoint_results=job.get('checkpoint_results',[]),
                             starting_condition_results=job.get('starting_condition_results',[]),
                             text_request=job.get('text_request') if value['status']=='awaiting_input' else None)
                last=value['steps'][-1] if value['steps'] else {}
                value['latest_screenshot']={'run_id':value['active_run_id'],'filename':last['screenshot']} if last.get('screenshot') else None
        return value

    def respond(self,session_id,text=None,stop=False):
        with self.lock:
            session=self.items.get(session_id)
            if not session or session['status'] not in {'running','awaiting_input','stopping'}:
                raise ValueError('Session is no longer active. Interrupted sessions cannot be resumed.')
            if stop:
                session['_stop'].set()
                session['status']='stopping'
                self.persist(session)
            if session['active_run_id']:
                try:dashboard_jobs.respond(session['active_run_id'],text,stop)
                except ValueError:
                    if not stop:raise
            elif not stop:
                raise ValueError('The session is not waiting for input.')
        return {'accepted':True,'session_id':session_id,'stop_requested':stop}

    def stop_active(self):
        with self.lock:
            for session in self.items.values():
                if session['status'] in {'running','awaiting_input','stopping'}:
                    self.respond(session['session_id'],stop=True)


SESSIONS=Sessions()
