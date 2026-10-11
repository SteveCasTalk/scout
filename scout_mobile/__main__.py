"""Run a mobile test and save a reviewable evidence bundle."""
from __future__ import annotations
import argparse
from datetime import datetime
import json
import os
from contextlib import nullcontext
from pathlib import Path
from .agent import Agent,RunConfig
from .config import ROOT,load_local_env,getenv
from .devices import connected
from .branding import PRODUCT_NAME
from .execution_contract import decode_export
from contextlib import nullcontext

def sandbox_routing(argv:list[str])->int:
    """`scout sandbox-routing up|down|status --serial S [--port 8898 ...]`: explicit device routing."""
    from .sandbox_routing import RoutingError, down, status, up
    parser=argparse.ArgumentParser(prog='scout sandbox-routing',description='Route an Android device through the Scout sandbox proxy (adb reverse + global HTTP proxy), or undo it.')
    parser.add_argument('action',choices=['up','down','status'])
    parser.add_argument('--serial',required=True)
    parser.add_argument('--port',type=int,action='append',default=[],help='Extra host port to adb-reverse, e.g. a local media server (repeatable; up only)')
    parser.add_argument('--adb',default=getenv('ADB_PATH') or 'adb')
    args=parser.parse_args(argv)
    try:
        result=up(args.serial,args.port,args.adb) if args.action=='up' else down(args.serial,args.adb) if args.action=='down' else status(args.serial,args.adb)
    except RoutingError as exc:
        print(f'Sandbox routing error: {exc}')
        return 2
    print(json.dumps(result,indent=2))
    if args.action=='up':print('Device HTTP traffic now only works during sandbox runs. Undo with: scout sandbox-routing down --serial '+args.serial)
    return 0

def main()->int:
    import sys
    if sys.argv[1:2]==['sandbox-routing']:
        load_local_env()
        return sandbox_routing(sys.argv[2:])
    parser=argparse.ArgumentParser(description=f'{PRODUCT_NAME} mobile test runner')
    parser.add_argument('run',nargs='?',default='run',choices=['run','nodes'],help='run a test (default) or list the run pipeline nodes')
    parser.add_argument('--case',type=Path,help='Exported dashboard test-case JSON')
    parser.add_argument('--goal',help='Goal for a one-off test; use --case for repeatable runs')
    parser.add_argument('--steps',default='')
    parser.add_argument('--expected',default='')
    parser.add_argument('--expected-text',default='',help='Exact visible text required for a Passed result')
    parser.add_argument('--package',help='Android package ID or iOS bundle ID')
    parser.add_argument('--platform',choices=['Android','iOS'],help='Defaults to the exported case platform or Android')
    parser.add_argument('--serial',help='Required when multiple devices are attached')
    parser.add_argument('--adb',default=getenv('ADB_PATH') or 'adb')
    parser.add_argument('--driver',choices=['adb','appium'],default='',help='Android execution backend; defaults to SCOUT_ANDROID_DRIVER or appium')
    parser.add_argument('--appium-url',default='',help='Local Appium URL; defaults to SCOUT_APPIUM_URL or http://127.0.0.1:4723')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--max-steps',type=int,default=40)
    parser.add_argument('--allow-purchase-entry',action='append',default=[],help='Authorize a declared purchase-entry ID for this run only')
    parser.add_argument('--allow-clear-data',action='store_true',help='Authorize a declared app-data reset')
    parser.add_argument('--allow-device-prompts',action='store_true',help='Leave Android autofill and credential providers enabled during the run; notification prompts remain suppressed')
    args=parser.parse_args()
    if args.run=='nodes':
        load_local_env()
        return print_nodes()
    if args.case:
        case=decode_export(json.loads(args.case.read_text(encoding='utf-8')))
        for required in ('id','revision','goal','steps','expected'):
            if required not in case:parser.error(f'Case JSON is missing {required}.')
    elif args.goal:
        case={'id':None,'revision':None,'title':args.goal[:160],'goal':args.goal,'steps':args.steps,'expected':args.expected}
    else:parser.error('Supply --case or --goal.')
    load_local_env()
    platform=args.platform or case.get('platform') or 'Android'
    if args.platform and case.get('platform') and args.platform!=case['platform']:parser.error('Platform conflicts with the exported case.')
    case['platform']=platform
    package=args.package or case.get('app_id') or ('com.wallet.walkthedog.uat' if platform=='Android' else '')
    if not package:parser.error('iOS requires --package with the app bundle ID.')
    devices=connected(platform,args.adb)
    if args.serial and args.serial not in devices:parser.error(f'Device {args.serial} is not connected and authorized.')
    if not args.serial and len(devices)!=1:parser.error(f'Expected one connected device; found {len(devices)}. Select --serial explicitly.')
    serial=args.serial or devices[0]
    if not 1<=args.max_steps<=100:parser.error('--max-steps must be 1–100.')
    output=args.output or ROOT/'runner-output'/datetime.now().strftime('%Y%m%d-%H%M%S')
    output=output.resolve()
    assertion=args.expected_text or case.get('assertion_text','')
    agent=Agent(RunConfig(package,serial,case,output,args.adb,args.max_steps,180,assertion,backend=args.driver,appium_url=args.appium_url,authorizations={'purchase_entries':args.allow_purchase_entry,'clear_data':args.allow_clear_data}))
    device=agent.device
    prompt_policy=nullcontext() if args.allow_device_prompts else device.suppress_credential_prompts()
    try:
        agent.lease.acquire()
        agent.lease_managed=True
        with device.screen_recording(output),prompt_policy,(nullcontext() if agent.execution and agent.execution['lifecycle']['notification_policy']=='preserve' else device.suppress_notification_prompt(package)):
            result=agent.run()
        result=agent.finalize_evidence(result)
    finally:
        try:device.close()
        finally:agent.lease.release()
    print(json.dumps({'status':result['status'],'notes':result['notes'],'result':str(output/'result.json'),'trace':str(output/'trace.json')},ensure_ascii=False))
    return 0 if result['status'] in ('Passed','Inconclusive') else 2

def print_nodes()->int:
    """Print the assembled pipeline, including installed plugins and disabled nodes."""
    from .engine import PipelineError, build_pipeline
    try:pipeline=build_pipeline()
    except PipelineError as exc:
        print(f'Pipeline error: {exc}')
        return 2
    for stage,nodes in pipeline.describe().items():
        print(f'{stage}:')
        for node in nodes:
            flags=' [locked]' if node['locked'] else ''
            print(f"  {node['name']:<30} {node['role']:<12} {node['summary']}{flags}")
            if not node['source'].startswith('scout_mobile.'):print(f"  {'':<30} {'':<12} from {node['source']}")
    return 0

if __name__=='__main__':raise SystemExit(main())
