"""Startup build identity, feature negotiation, and read-only readiness checks."""
from __future__ import annotations
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from .config import ROOT, getenv
from .execution_contract import FEATURES, supported

_sources=sorted((ROOT/'scout_mobile').glob('*.py'))
BUILD_IDENTITY={'component':'scout-runner','source_sha256':hashlib.sha256(b''.join(p.name.encode()+p.read_bytes() for p in _sources)).hexdigest(),'source_root':str(ROOT),'python':sys.version.split()[0]}


def capabilities(platform='Android',backend='appium'):
    if platform not in {'Android','iOS'} or backend not in {'appium','adb'}:raise ValueError('Invalid platform or backend.')
    return {'contract_versions':[1,2],'features':sorted(supported(platform,backend)),'platform':platform,'backend':backend,'build':BUILD_IDENTITY,'limits':{'actions':100,'tap_burst_count':5,'observation_samples':5000,'execution_timeout_seconds':1800},'limitations':['Continuous absence requires complete instrumented evidence; sampled UI cannot prove it.','Native burst offsets are requested timing, not verified device delivery timestamps.','Metadata verification does not prove playback, mute, blur, outfit appearance or audio output.','Purchase support is entry-only; checkout commitment is blocked.']}


def negotiate(execution,peer):
    if not execution:return
    if not isinstance(peer,dict) or 2 not in peer.get('contract_versions',[]) or not set(execution['required_capabilities']).issubset(peer.get('features',[])):
        raise ValueError('Runner capability handshake does not support this case; upgrade/reload the component.')


def negotiate_case(case,execution,peer):
    negotiate(execution,peer)
    sandbox=case.get('sandbox') or {}
    if sandbox.get('schema_version')==2:
        needed=['network_contract_v2']
        if any(r.get('assertions') for r in sandbox.get('http',[])):needed.append('request_assertions')
        negotiate({'required_capabilities':needed},peer)


def _health(url,headers=None):
    try:
        with urlopen(Request(url,headers=headers or {}),timeout=.5) as r:
            body=r.read(100000)
            return {'reachable':True,'http_status':r.status,'data':json.loads(body)}
    except HTTPError as e:return {'reachable':True,'http_status':e.code}
    except (OSError,ValueError):return {'reachable':False}


def diagnose(serial=None,package=None,workspace_id=None):
    checks=[]
    def add(name,status,remedy='',**facts):checks.append({'dependency':name,'status':status,'remedy':remedy,**facts})
    add('python','ready',version=sys.version.split()[0],executable=sys.executable)
    for name in ('TYPESAFE_API_KEY','SCOUT_TEST_EMAIL','SCOUT_TEST_PASSWORD'):
        add('configuration:'+name,'present' if bool(getenv(name)) else 'missing','Set the value locally in .env, then reload MCP/bridge.' if not getenv(name) else '')
    configured=getenv('SCOUT_DASHBOARD_URL','http://localhost:5173')
    from .dashboard_client import local_url
    try:configured=local_url(configured)
    except ValueError:configured='http://localhost:5173';add('dashboard_config','invalid','Use a local dashboard URL on port 5173–5189.')
    dashboard=_health(configured+'/api/health')
    data=dashboard.get('data',{})
    ready=dashboard.get('http_status')==200 and data.get('service')=='scout-dashboard' and data.get('status')=='ready'
    add('dashboard','ready' if ready else 'unavailable','Start the local dashboard with its documented dev command.' if not ready else '',url=configured,peer=data.get('capabilities'))
    if ready:
        auth=_health(configured+'/api/workspaces')
        add('authentication','ready' if auth.get('http_status')==200 else 'unverified','Use the dashboard normal sign-in flow.' if auth.get('http_status')!=200 else '')
        if workspace_id:
            import uuid
            uuid.UUID(workspace_id)
            values=auth.get('data',[])
            exists=isinstance(values,list) and any(isinstance(v,dict) and v.get('id')==workspace_id for v in values)
            add('workspace','ready' if exists else 'unverified','Verify the selected workspace under the signed-in owner.' if not exists else '')
    port=int(getenv('SCOUT_LOCAL_RUNNER_PORT','8765'))
    if not 1024<=port<=65535:raise ValueError('Invalid local bridge port.')
    bridge=_health(f'http://127.0.0.1:{port}/health',{'Origin':configured})
    add('bridge','ready' if bridge.get('data',{}).get('status')=='ready' else 'unavailable','Start scout-local-runner if unavailable.',peer=bridge.get('data',{}).get('capabilities'))
    from urllib.parse import urlsplit
    appium_url=getenv('SCOUT_APPIUM_URL','http://127.0.0.1:4723');parsed=urlsplit(appium_url)
    safe=parsed.scheme=='http' and parsed.hostname in {'localhost','127.0.0.1','::1'} and not (parsed.username or parsed.password or parsed.query or parsed.fragment)
    appium=_health(appium_url.rstrip('/')+'/status') if safe else {}
    if not safe:add('appium_config','invalid','Use a local HTTP Appium URL without credentials.')
    add('appium','ready' if appium.get('data',{}).get('value',{}).get('ready') is True else 'unverified','Use the documented Appium setup/status checks if needed.')
    from .device import AndroidDevice
    try:
        devices=AndroidDevice.connected(getenv('ADB_PATH') or 'adb')
        add('devices','ready' if devices else 'missing','Connect/unlock an authorized Android device.' if not devices else '',serials=devices)
    except Exception:devices=[];add('devices','unavailable','Check adb devices -l and the local ADB executable.')
    from .dashboard_jobs import JOBS, LOCK
    with LOCK:active=[{'run_id':k,'status':v['status']} for k,v in JOBS.items() if v['status'] in {'running','awaiting_input'}]
    add('runner_lock','busy' if active or bridge.get('data',{}).get('run_lock_held') else 'unverified','Wait for active runs; bridge lock state also needs its health response.',active=active)
    if serial:
        if serial not in devices:add('selected_device','missing','Select an attached authorized serial.')
        elif active or __import__('scout_mobile.device_lease',fromlist=['DeviceLease']).DeviceLease.busy(serial) or bridge.get('data',{}).get('run_lock_held'):add('selected_device','busy','Wait for the device owner to finish.')
        else:
            add('selected_device','ready',serial=serial)
            if package:
                import re
                if not re.fullmatch(r'[A-Za-z0-9_.]{3,240}',package):raise ValueError('Invalid app package.')
                try:
                    device=AndroidDevice(serial,getenv('ADB_PATH') or 'adb')
                    installed=device.installed(package)
                    details=device.command('shell','dumpsys','package',package,check=False).stdout.decode(errors='replace') if installed else ''
                    version=re.search(r'versionName=([^\s]+)',details)
                    add('app','installed' if installed else 'missing','Install the prepared feature build.' if not installed else '',package=package,version=version[1] if version else 'unknown',feature_readiness='unverified')
                except Exception:add('app','unverified','Inspect the selected app build with ADB.')
    for journal in (ROOT/'runner-output').glob('*/.lifecycle.json'):
        try:
            value=json.loads(journal.read_text())
            if value.get('phase')!='restored' and (not serial or value.get('device')==serial):add('cleanup','blocked','Reconcile the recorded lifecycle changes before another run.',run_id=journal.parent.name)
        except (ValueError,OSError):add('cleanup','unverified','Inspect an unreadable lifecycle journal.')
    add('sandbox_dependency','present' if importlib.util.find_spec('mitmproxy') else 'missing','Install the optional sandbox extra only when network fixtures are required.')
    add('proxy_routing','unverified','An explicit app-traffic probe is required; listener configuration alone is insufficient.')
    add('app_ca_trust','unverified','Verify the test app trusts the local proxy CA before network acceptance.')
    add('media_verifier','present' if __import__('shutil').which('ffprobe') else 'missing','Optional ffprobe is needed only for media metadata assertions.')
    return {'build':BUILD_IDENTITY,'checks':checks,'readiness':'blocked' if any(c['status']=='blocked' for c in checks) else 'partial','credentials_exposed':False,'device_actions_performed':False}
