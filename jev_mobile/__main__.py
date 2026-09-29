"""Run an indexed-action Android test and save a reviewable evidence bundle."""
from __future__ import annotations
import argparse
from datetime import datetime
import json
import os
from contextlib import nullcontext
from pathlib import Path
from .agent import Agent,RunConfig
from .config import ROOT,load_local_env
from .device import AndroidDevice

def main()->int:
    parser=argparse.ArgumentParser(description='Jev-style Android test runner')
    parser.add_argument('run',nargs='?',default='run',choices=['run'])
    parser.add_argument('--case',type=Path,help='Exported dashboard test-case JSON')
    parser.add_argument('--goal',help='Goal for a one-off test; use --case for repeatable runs')
    parser.add_argument('--steps',default='')
    parser.add_argument('--expected',default='')
    parser.add_argument('--expected-text',default='',help='Exact visible text required for a Passed result')
    parser.add_argument('--package',default='com.wallet.walkthedog.uat')
    parser.add_argument('--serial',help='Required when multiple devices are attached')
    parser.add_argument('--adb',default=os.getenv('ADB_PATH') or 'adb')
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
    devices=AndroidDevice.connected(args.adb)
    if args.serial and args.serial not in devices:parser.error(f'Device {args.serial} is not connected and authorized.')
    if not args.serial and len(devices)!=1:parser.error(f'Expected one connected device; found {len(devices)}. Select --serial explicitly.')
    serial=args.serial or devices[0]
    if not 1<=args.max_steps<=100:parser.error('--max-steps must be 1–100.')
    output=args.output or ROOT/'runner-output'/datetime.now().strftime('%Y%m%d-%H%M%S')
    output=output.resolve()
    assertion=args.expected_text or case.get('assertion_text','')
    device=AndroidDevice(serial,args.adb)
    prompt_policy=nullcontext() if args.allow_device_prompts else device.suppress_credential_prompts()
    with prompt_policy,device.suppress_notification_prompt(args.package):
        result=Agent(RunConfig(args.package,serial,case,output,args.adb,args.max_steps,180,assertion)).run()
    print(json.dumps({'status':result['status'],'notes':result['notes'],'result':str(output/'result.json'),'trace':str(output/'trace.json')},ensure_ascii=False))
    return 0 if result['status'] in ('Passed','Inconclusive') else 2

if __name__=='__main__':raise SystemExit(main())
