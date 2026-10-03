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

def main()->int:
    parser=argparse.ArgumentParser(description=f'{PRODUCT_NAME} mobile test runner')
    parser.add_argument('run',nargs='?',default='run',choices=['run'])
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
    parser.add_argument('--allow-device-prompts',action='store_true',help='Leave Android autofill and credential providers enabled during the run; notification prompts remain suppressed')
    args=parser.parse_args()
    if args.case:
        case=json.loads(args.case.read_text(encoding='utf-8'))
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
    agent=Agent(RunConfig(package,serial,case,output,args.adb,args.max_steps,180,assertion,backend=args.driver,appium_url=args.appium_url))
    device=agent.device
    prompt_policy=nullcontext() if args.allow_device_prompts else device.suppress_credential_prompts()
    try:
        with device.screen_recording(output),prompt_policy,device.suppress_notification_prompt(package):
            result=agent.run()
        result=agent.finalize_evidence(result)
    finally:device.close()
    print(json.dumps({'status':result['status'],'notes':result['notes'],'result':str(output/'result.json'),'trace':str(output/'trace.json')},ensure_ascii=False))
    return 0 if result['status'] in ('Passed','Inconclusive') else 2

if __name__=='__main__':raise SystemExit(main())
