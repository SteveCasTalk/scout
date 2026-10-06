"""Background dashboard runs. Only guarded agent captures are exposed as progress."""
from __future__ import annotations
from contextlib import nullcontext
from datetime import datetime
import os
import threading
import time
from .agent import Agent, RunConfig
from .evidence import inventory as evidence_inventory
from .config import ROOT,getenv
from .devices import connected
from .execution_contract import check_support, validate_authorizations
from .capabilities import capabilities, negotiate_case

JOBS: dict[str, dict] = {}
LOCK = threading.Lock()


def snapshot(job_id: str) -> dict | None:
    with LOCK:
        job = JOBS.get(job_id)
        if not job:
            path = ROOT / 'runner-output' / job_id / 'result.json'
            if not path.is_file():
                return None
            import json
            try:
                result = json.loads(path.read_text(encoding='utf-8'))
                return {'run_id': job_id, 'status': 'completed', 'steps': [], 'result': result, 'artifacts': [p.name for p in evidence_inventory(path.parent)]}
            except (OSError, ValueError):
                return None
        return {key: value for key, value in job.items() if not key.startswith('_')}


def respond(job_id: str, text: str | None, stop: bool = False) -> None:
    with LOCK:
        job = JOBS.get(job_id)
        if not job or job['status'] not in {'running', 'awaiting_input'}:
            raise ValueError('This run is no longer active.')
        if stop:
            job['_stop'].set()
        else:
            if job['status'] != 'awaiting_input' or not isinstance(text, str) or not text.strip() or len(text) > 200:
                raise ValueError('Enter 1–200 characters for a run waiting for text.')
            job['_text'] = text
            job['status'] = 'running'
        job['_wake'].set()


def start(payload: dict, run_lock: threading.Lock) -> str:
    case = payload.get('case')
    if not isinstance(case, dict) or any(key not in case for key in ('id', 'revision', 'goal', 'steps', 'expected')):
        raise ValueError('A complete saved test case is required.')
    import re
    package = str(case.get('app_id') or payload.get('package') or '')
    if not re.fullmatch(r'[A-Za-z0-9_.]{3,240}', package):
        raise ValueError('Set a valid app package or bundle ID on the case.')
    if case.get('platform') not in {'Android', 'iOS'}:
        raise ValueError('Select Android or iOS on the case.')
    execution=check_support(case,case['platform'],getenv('SCOUT_ANDROID_DRIVER') or 'appium')
    negotiate_case(case,execution,payload.get('client_capabilities'))
    grants=validate_authorizations(payload.get('authorizations'),execution)
    serial = payload.get('serial')
    adb = getenv('ADB_PATH') or 'adb'
    if not isinstance(serial, str) or serial not in connected(case['platform'], adb):
        raise ValueError('Select a connected device for this case’s platform.')
    steps = payload.get('max_steps', 40)
    if type(steps) is not int or not 1 <= steps <= 100:
        raise ValueError('Action limit must be 1–100.')
    if payload.get('conditions_confirmed') is not True:
        raise ValueError('Confirm starting conditions before running.')
    allow_consent = payload.get('allow_consent', False)
    if type(allow_consent) is not bool:raise ValueError('Prompt consent must be true or false.')
    mode = payload.get('start_mode', 'current')
    if mode not in {'current', 'relaunch'}:
        raise ValueError('Choose current state or relaunch.')
    if not run_lock.acquire(blocking=False):
        raise ValueError('Another dashboard run is active. Wait for it to finish.')
    job_id = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    output = ROOT / 'runner-output' / job_id
    if payload.get('retain_saved_case') is True:
        try:
            import json
            output.mkdir(parents=True, exist_ok=True)
            pinned = output / '.saved-case.json'
            pinned.write_text(json.dumps(case, ensure_ascii=False), encoding='utf-8')
            pinned.chmod(0o600)
        except Exception:
            run_lock.release()
            raise
    with LOCK:
        # Keep active jobs and a bounded recent completion history.
        for key in list(JOBS):
            if len(JOBS) < 100:
                break
            if JOBS[key]['status'] in {'completed', 'error'}:
                del JOBS[key]
        JOBS[job_id] = {'run_id': job_id, 'case_id': case['id'], 'status': 'running', 'started': time.time(), 'steps': [], 'text_request': None, 'cleanup_complete': False, '_stop': threading.Event(), '_wake': threading.Event(), '_text': None}
    def worker():
        agent = None
        try:
            def progress(history):
                visible = [{key: entry.get(key) for key in ('step', 'operation', 'label', 'elapsed_ms', 'screenshot')} for entry in history]
                with LOCK:
                    JOBS[job_id]['steps'] = visible
                    JOBS[job_id]['checkpoint_results'] = list(agent.checkpoint_verdicts.values()) if agent else []
                    JOBS[job_id]['starting_condition_results'] = list(agent.starting_condition_results) if agent else []
            job = JOBS[job_id]
            agent = Agent(RunConfig(package, serial, case, output, adb, steps, 600, str(case.get('assertion_text', '')), allow_consent=allow_consent, mcp_host_text=True, on_progress=progress, should_stop=job['_stop'].is_set,authorizations=grants))
            agent.lease.acquire()
            agent.lease_managed=True
            if mode == 'relaunch':
                agent.device.terminate(package)
            while True:
                with agent.device.screen_recording(output), agent.device.suppress_credential_prompts(), (nullcontext() if agent.execution and agent.execution['lifecycle']['notification_policy']=='preserve' else agent.device.suppress_notification_prompt(package)):
                    result = agent.run() if agent._continuation is None else agent.resume_text(job['_text'])
                result = agent.finalize_evidence(result)
                with LOCK:
                    job['_text'] = None
                if result.get('status') != 'awaiting_input':
                    break
                with LOCK:
                    job['status'] = 'awaiting_input'
                    job['text_request'] = result['text_request']
                    job['_wake'].clear()
                if not job['_stop'].is_set():
                    job['_wake'].wait(900)
                if job['_stop'].is_set() or job['_text'] is None:
                    if agent._continuation is not None:agent._continuation.close()
                    result = agent.finalize_evidence(agent.write_result('Inconclusive', 'Run stopped while waiting for user input.', None))
                    break
                with LOCK:
                    job['text_request'] = None
            progress(agent.history)
            artifacts = [p.name for p in evidence_inventory(output)]
            with LOCK:
                job.update(status='completed', result=result, artifacts=artifacts, text_request=None)
        except Exception as exc:
            message = agent.redact(str(exc)) if agent else type(exc).__name__
            with LOCK:
                JOBS[job_id].update(status='error', error=message[:500])
        finally:
            try:
                if agent:
                    if agent._continuation is not None:agent._continuation.close()
                    try:agent.device.close()
                    finally:agent.lease.release()
            except Exception:
                with LOCK:
                    JOBS[job_id]['cleanup_error']='Device session cleanup failed. Check the device before running again.'
            finally:
                with LOCK:
                    JOBS[job_id]['cleanup_complete']=True
                run_lock.release()
    try:
        threading.Thread(target=worker, daemon=True).start()
    except Exception:
        run_lock.release()
        with LOCK:
            JOBS.pop(job_id, None)
        raise
    return job_id
