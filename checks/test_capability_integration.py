"""Host-only integration checks: no connected devices, proxy listeners, or dashboard writes."""
import argparse
import ast
import asyncio
import importlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from scout_mobile.agent import Agent,RunConfig
from scout_mobile.appium_device import AppiumAndroidDevice
from scout_mobile.device import AndroidDevice,DeviceError
from scout_mobile.execution_contract import validate_execution,export_case
from scout_mobile.execution_runtime import Protocol,ExecutionBlocked,ObservationIncomplete
from scout_mobile.lifecycle import Lifecycle
from scout_mobile.capabilities import negotiate_case
from scout_mobile.media_verification import verify_metadata
from scout_mobile.evidence import inventory,allowed
from test_execution_capabilities import PKG,screen,temporal,purchase_spec

class HostIntegration(unittest.TestCase):
    def test_existing_capture_session_uses_capture_options_without_replay_validation(self):
        from scout_mobile.sandbox import Session
        with tempfile.TemporaryDirectory() as folder:
            session=Session({'project':'Synthetic','name':'Capture','hosts':['example.test']},Path(folder),recording=True)
            self.assertTrue(session.recording);self.assertNotIn('schema_version',session.scenario)

    def test_shared_fixture_python_normalization(self):
        from scout_mobile.sandbox import validate
        fixtures=json.loads((Path(__file__).parent/'fixtures/capability-contracts.json').read_text())
        for fixture in fixtures:
            with self.subTest(fixture=fixture['name']):
                validator=validate_execution if fixture['kind']=='execution' else validate
                if fixture['valid']:self.assertEqual(validator(fixture['input']),fixture['normalized'])
                else:
                    with self.assertRaises(ValueError):validator(fixture['input'])

    def test_actual_baseline_cli_and_mcp_reject_new_export_before_device_inventory(self):
        root=Path(__file__).resolve().parents[1]
        old={'id':'synthetic','revision':1,'goal':'Synthetic','steps':'Observe','expected':'Synthetic','app_id':PKG}
        new=export_case({**old,'execution':purchase_spec()})
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'case.json'
            for module,entry in [('scout_mobile/__main__.py','main'),('scout_mobile/mcp_server.py','run_mobile_test')]:
                source=subprocess.check_output(['git','show','56a03b5:'+module],cwd=root,text=True)
                node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name==entry);node.decorator_list=[]
                tree=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),node],type_ignores=[])
                inventory_mock=Mock(side_effect=LookupError('synthetic inventory boundary'))
                scope={'argparse':argparse,'json':json,'Path':Path,'getenv':lambda key:None,'load_local_env':Mock(),'PRODUCT_NAME':'Scout','CASE_FIELDS':{'id','revision','goal','steps','expected'},'connected':inventory_mock,'_select_device':inventory_mock,'re':__import__('re')}
                exec(compile(ast.fix_missing_locations(tree),module,'exec'),scope)
                for definition in (new,old):
                    file.write_text(json.dumps(definition));inventory_mock.reset_mock()
                    with patch.object(sys,'argv',['scout','--case',str(file)]),patch('sys.stderr',__import__('io').StringIO()):
                        if definition is new:
                            with self.assertRaises(SystemExit if entry=='main' else ValueError):scope[entry]() if entry=='main' else scope[entry](str(file))
                            inventory_mock.assert_not_called()
                        else:
                            with self.assertRaisesRegex(LookupError,'synthetic inventory'):scope[entry]() if entry=='main' else scope[entry](str(file))
                            inventory_mock.assert_called_once()

    def test_native_drag_and_burst_are_single_device_sequences(self):
        adapter=AppiumAndroidDevice('synthetic');driver=Mock();adapter._call=lambda call:call(driver)
        adapter.drag_coordinates(10,20,30,40,300,400)
        sequence=driver.execute.call_args.args[1]['actions'][0]['actions']
        self.assertEqual(sequence[2],{'type':'pause','duration':400});self.assertEqual(sequence[3]['duration'],300)
        driver.reset_mock();result=adapter.tap_burst(screen(button='Safe option').elements[0],3,100)
        driver.execute.assert_called_once();actions=driver.execute.call_args.args[1]['actions'][0]['actions']
        self.assertEqual(sum(a['type']=='pointerDown' for a in actions),3)
        self.assertEqual(result['requested_offsets_ms'],[0,100,200]);self.assertFalse(result['delivery_timestamps_verified'])
        with self.assertRaises(DeviceError):adapter.tap_burst(screen().elements[0],100,1)

    def test_target_swipe_uses_observed_message_bounds(self):
        with tempfile.TemporaryDirectory() as folder:
            execution=validate_execution({'required_capabilities':['target_gestures'],'actions':[{'id':'swipe','operation':'SWIPE','package':PKG,'selector':{'text':'Message'}}]})
            agent=Agent(RunConfig(PKG,'synthetic',{'execution':execution},Path(folder),backend='appium'));agent.device=Mock();agent.device.observe.return_value=screen(button='Message',clickable=False);agent.device.foreground.return_value=PKG;agent.screenshot=Mock(return_value=None)
            agent.protocol.run();agent.device.swipe_coordinates.assert_called_once_with(360,140,80,140,300)

    def test_model_rechecks_external_authorization_after_foreground_changes(self):
        external='com.example.external'
        spec=validate_execution({'required_capabilities':['external_packages'],'external_flows':[{'package':external,'from_package':PKG,'entry_text':'External synthetic','return_text':'Synthetic shop','taps':[]}],'finish':'model'})
        with tempfile.TemporaryDirectory() as folder:
            agent=Agent(RunConfig(PKG,'synthetic',{'execution':spec,'goal':'Open safe option','steps':'Tap Continue','expected':'Ready'},Path(folder),backend='appium',max_steps=1))
            before=screen(button='Continue');destination=screen('External synthetic','Continue');device=Mock();device.installed.return_value=True;device.wait_for_content.return_value=before;device.observe.side_effect=[before,before,destination];device.foreground.side_effect=[PKG,PKG,PKG,external];device.recording_error=''
            agent.device=device;agent.screenshot=Mock(return_value=None);agent.capture_device_info=Mock(return_value={});agent.capture_app_logs=Mock(return_value='')
            choice={'operation':'TAP','target':before.elements[0].index,'confidence':1,'model':'synthetic','latency_ms':0,'jev':{}}
            with patch('scout_mobile.agent.choose',return_value=choice):result=agent.run()
            self.assertEqual(result['status'],'Blocked');device.tap.assert_not_called()

    def test_typed_then_model_actions_keep_unique_trace_and_screenshot_indices(self):
        spec=validate_execution({'required_capabilities':[],'actions':[{'id':'observe','operation':'OBSERVE','package':PKG}],'finish':'model'})
        with tempfile.TemporaryDirectory() as folder:
            agent=Agent(RunConfig(PKG,'synthetic',{'execution':spec,'goal':'Observe','steps':'Observe then finish'},Path(folder),backend='appium',expected_text='Synthetic shop'))
            device=Mock();device.installed.return_value=True;device.wait_for_content.return_value=screen();device.observe.return_value=screen();device.foreground.return_value=PKG;device.recording_error=''
            agent.device=device;agent.screenshot=Mock(return_value=None);agent.capture_device_info=Mock(return_value={});agent.capture_app_logs=Mock(return_value='')
            choice={'operation':'DONE','target':None,'confidence':1,'model':'synthetic','latency_ms':0,'jev':{}}
            with patch('scout_mobile.agent.choose',return_value=choice):result=agent.run()
            indices=[s['step'] for s in result['steps']];self.assertEqual(indices,[0,1,2,3]);self.assertEqual(result['status'],'Passed')

    def test_direct_agent_reports_cleanup_failure_after_generator_finishes(self):
        with tempfile.TemporaryDirectory() as folder:
            agent=Agent(RunConfig(PKG,'synthetic',{'execution':{'required_capabilities':[]},'goal':'Observe','steps':'Observe'},Path(folder),backend='appium',expected_text='Synthetic shop'))
            device=Mock();device.installed.return_value=True;device.wait_for_content.return_value=screen();device.observe.return_value=screen();device.foreground.return_value=PKG;device.recording_error=''
            agent.device=device;agent.screenshot=Mock(return_value=None);agent.capture_device_info=Mock(return_value={});agent.capture_app_logs=Mock(return_value='')
            def failed_restore():agent.lifecycle.failed=True;raise DeviceError('synthetic cleanup failure')
            agent.lifecycle.restore=failed_restore;result=agent.run()
            self.assertEqual(result['original_status'],'Passed');self.assertEqual(result['status'],'Blocked');self.assertTrue(result['execution']['cleanup_failed']);self.assertIsNone(agent.lease.handle)

    def test_cancelled_observation_persists_partial_unknown_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            agent=Agent(RunConfig(PKG,'synthetic',{'execution':{'required_capabilities':[]}},Path(folder),backend='appium',should_stop=lambda:True))
            with self.assertRaises(ObservationIncomplete):agent.protocol.temporals([temporal()],__import__('time').monotonic())
            result=json.loads((Path(folder)/'execution-evidence.json').read_text())['assertions'][0]
            self.assertEqual(result['verdict'],'not_observable');self.assertFalse(result['coverage_complete'])

    def test_post_deadline_forbidden_sample_does_not_invent_violation(self):
        from scout_mobile.temporal import TemporalState
        state=TemporalState(temporal('never_during'),0);state.feed(990,1010,True,True)
        self.assertEqual(state.verdict,'not_observable')

    def test_missing_native_backend_and_new_network_peer_block_before_device_use(self):
        from scout_mobile import dashboard_jobs
        fixture={'schema_version':2,'http':[]}
        with self.assertRaises(ValueError):negotiate_case({'sandbox':fixture},None,{'contract_versions':[1],'features':[]})
        with patch.object(dashboard_jobs,'connected') as devices:
            case={'id':str(uuid.uuid4()),'revision':1,'goal':'Observe','steps':'Observe','expected':'Visible','app_id':PKG,'platform':'Android','sandbox':fixture}
            with self.assertRaisesRegex(ValueError,'handshake'):dashboard_jobs.start({'case':case,'serial':'synthetic'},threading.Lock())
            devices.assert_not_called()

    def test_saved_session_preserves_case_grants_and_start_retry(self):
        from scout_mobile import library_sessions as module
        case={'id':str(uuid.uuid4()),'revision':2,'title':'Synthetic','goal':'Observe','steps':'Observe','expected':'Visible','app_id':PKG,'platform':'Android','execution':purchase_spec()}
        workspace=str(uuid.uuid4());client=Mock();client.url='http://localhost:5173';client.request.return_value={'cases':[case]}
        packet={'request_id':str(uuid.uuid4()),'dashboard_url':client.url,'workspace_id':workspace,'cases':[{'id':case['id'],'revision':2}],'serial':'synthetic','conditions_confirmed':True,'client_capabilities':{'contract_versions':[1,2],'features':['purchase_entry','external_packages']},'authorizations':{case['id']:{'purchase_entries':['entry']}}}
        with tempfile.TemporaryDirectory() as folder,patch.object(module,'STORE',Path(folder)),patch.object(module,'DashboardClient',return_value=client),patch.object(module,'connected',return_value=['synthetic']),patch.object(module.threading,'Thread') as thread:
            sessions=module.Sessions();lock=threading.Lock();first=sessions.start(packet,lock);second=sessions.start(packet,lock)
            self.assertEqual(first['session_id'],second['session_id']);thread.assert_called_once()
            saved=json.loads(next(Path(folder).glob('*.json')).read_text());self.assertEqual(saved['authorizations'],packet['authorizations'])
            lock.release()

    def test_matrix_variant_capabilities_are_checked_even_when_base_is_legacy(self):
        from scout_mobile import library_sessions as module
        case={'id':str(uuid.uuid4()),'revision':1,'title':'Synthetic','goal':'Observe','steps':'Observe','expected':'Visible','app_id':PKG,'platform':'Android'}
        variant={**case,'sandbox':{'schema_version':2,'http':[]}}
        client=Mock();client.url='http://localhost:5173';client.request.side_effect=[{'case':case},{'cases':[variant]}]
        packet={'request_id':str(uuid.uuid4()),'dashboard_url':client.url,'workspace_id':str(uuid.uuid4()),'matrix_id':str(uuid.uuid4()),'expected_matrix_revision':1,'expected_case_revision':1,'serial':'synthetic','conditions_confirmed':True,'start_mode':'relaunch','client_capabilities':{'contract_versions':[1],'features':[]}}
        with tempfile.TemporaryDirectory() as folder,patch.object(module,'STORE',Path(folder)),patch.object(module,'DashboardClient',return_value=client),patch.object(module,'connected',return_value=['synthetic']),patch.object(module.threading,'Thread') as thread:
            lock=threading.Lock()
            with self.assertRaisesRegex(ValueError,'handshake'):module.Sessions().start(packet,lock)
            self.assertFalse(lock.locked());thread.assert_not_called()

    def test_failed_lifecycle_restore_blocks_next_run_and_public_journal_is_excluded(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);output=root/'first';output.mkdir();a=SimpleNamespace(output=output,config=SimpleNamespace(serial='synthetic',package=PKG),device=Mock(),execution={'lifecycle':{'before':[]}},authorizations={})
            lifecycle=Lifecycle(a);lifecycle.state=[{'hook':{'id':'wifi','operation':'wifi','enabled':False},'original':True}];lifecycle.value=Mock(side_effect=DeviceError('offline'))
            with self.assertRaises(DeviceError):lifecycle.restore()
            self.assertEqual(json.loads(lifecycle.journal.read_text())['phase'],'failed');self.assertFalse(allowed(output,'.lifecycle.json'))
            next_output=root/'next';next_output.mkdir();a.output=next_output
            with self.assertRaises(ExecutionBlocked):Lifecycle(a).prepare()

    def test_credential_cleanup_restores_absent_empty_populated_and_shell_sensitive_values(self):
        for original in ({},{'autofill_service':''},{'autofill_service':'provider/component','credential_service':"literal $() `text` ' quote ; content"}):
            with self.subTest(original=original):
                state=original.copy();device=AndroidDevice('synthetic')
                def command(*args,**kwargs):
                    if args[1:3]==('settings','list'):data=''.join(k+'='+v+'\n' for k,v in state.items())
                    elif args[1:3]==('settings','get'):data=state.get(args[4],'null')+'\n'
                    elif args[1:3]==('settings','put'):state[args[4]]=shlex.split(args[5])[0];data=''
                    elif args[1:3]==('settings','delete'):state.pop(args[4],None);data=''
                    else:raise AssertionError(args)
                    return subprocess.CompletedProcess(args,0,data.encode(),b'')
                device.command=command
                with device.suppress_credential_prompts():self.assertEqual(set(state.values()),{''})
                self.assertEqual(state,original)

    def test_frame_comparison_does_not_override_dimension_failure_or_missing_tool(self):
        from scout_mobile.execution_contract import Media
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder);(output/'synthetic.mp4').write_bytes(b'synthetic')
            rule=Media.model_validate({'id':'media','artifact':'synthetic.mp4','kind':'frame_change','width':100}).model_dump()
            probe=subprocess.CompletedProcess([],0,b'{"format":{"duration":"2"},"streams":[{"codec_type":"video","width":200,"height":100}]}',b'')
            frame1=subprocess.CompletedProcess([],0,b'\x00'*4096,b'');frame2=subprocess.CompletedProcess([],0,b'\xff'*4096,b'')
            with patch('scout_mobile.media_verification.shutil.which',return_value='/synthetic/tool'),patch('scout_mobile.media_verification.subprocess.run',side_effect=[probe,frame1,frame2]):self.assertEqual(verify_metadata(output,[rule])[0]['verdict'],'violated')
            with patch('scout_mobile.media_verification.shutil.which',side_effect=['/synthetic/tool',None]),patch('scout_mobile.media_verification.subprocess.run',return_value=probe):self.assertEqual(verify_metadata(output,[rule])[0]['verdict'],'not_observable')
            (output/'result.json').write_text(json.dumps({'execution':{'definition':{'media_assertions':[rule]}}}));self.assertIn('synthetic.mp4',[f.name for f in inventory(output)])
            (output/'private.mp4').write_bytes(b'not declared');self.assertFalse(allowed(output,'private.mp4'))

class AddonIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.scratch=tempfile.TemporaryDirectory();self.addCleanup(self.scratch.cleanup);self.root=Path(self.scratch.name)
        fixture={'schema_version':2,'id':'synthetic','name':'Synthetic','project':'Synthetic','hosts':['example.test'],'http':[{'id':'a','host':'example.test','path':'/data','match':[{'source':'query','key':'buddy','value':'a'}],'correlation':{'source':'query','key':'session'},'responses':[{'body':'a0','delay_ms':10},{'body':'a1'}]},{'id':'b','host':'example.test','path':'/data','match':[{'source':'query','key':'buddy','value':'b'}],'responses':[{'body':'b0'}]}]}
        path=self.root/'scenario.json';path.write_text(json.dumps(fixture))
        with patch.dict(os.environ,{'SCOUT_SANDBOX_SCENARIO':str(path),'SCOUT_SANDBOX_OUTPUT':str(self.root)}):
            self.module=importlib.import_module('scout_mobile.sandbox_addon');self.addon=self.module.SandboxAddon()
    def flow(self,path):
        from mitmproxy.http import Request
        return SimpleNamespace(request=Request.make('GET','https://example.test'+path),metadata={},response=None,websocket=SimpleNamespace(timestamp_end=None))
    async def test_concurrent_identity_matching_and_per_session_sequences(self):
        a1=self.flow('/data?buddy=a&session=one');b=self.flow('/data?buddy=b');a2=self.flow('/data?buddy=a&session=two')
        await asyncio.gather(self.addon.request(a1),self.addon.request(b),self.addon.request(a2))
        self.assertEqual([f.response.content for f in (a1,b,a2)],[b'a0',b'b0',b'a0'])
        repeat=self.flow('/data?buddy=a&session=one');await self.addon.request(repeat);self.assertEqual(repeat.response.content,b'a1')
        self.assertNotIn('session=one',(self.root/'.sandbox-events.jsonl').read_text())
        missing=self.flow('/data?buddy=a');await self.addon.request(missing);self.assertEqual(missing.response.status_code,502)
    async def test_late_push_uses_scoped_event_origin_and_cancels_pending_tasks(self):
        flow=self.flow('/ws');flow.metadata={'jev_ws_rule':{'id':'late','pushes':[{'after_ms':300000,'body':'synthetic','trigger_event':'reminder'}]},'scout_correlation':'session'}
        commands=Mock()
        with patch.object(self.module,'ctx',SimpleNamespace(master=SimpleNamespace(commands=commands))):
            self.addon.websocket_start(flow);await asyncio.sleep(0)
            self.addon.emit('reminder','other-session');await asyncio.sleep(0);commands.call.assert_not_called()
            self.addon.websocket_end(flow);await asyncio.sleep(0)
            self.assertFalse(self.addon.flow_tasks)
            events=(self.root/'.sandbox-events.jsonl').read_text();self.assertIn('error',events)
    async def test_event_relative_push_delay_is_absolute_not_accumulated(self):
        flow=self.flow('/ws');flow.metadata={'jev_ws_rule':{'id':'late','pushes':[{'after_ms':300000,'body':'synthetic','trigger_event':'reminder'},{'after_ms':310000,'body':'synthetic2','trigger_event':'reminder'}]},'scout_correlation':'session'}
        self.addon.emit('reminder','session');requested=[]
        async def fake_sleep(seconds):requested.append(seconds)
        with patch.object(self.module,'ctx',SimpleNamespace(master=SimpleNamespace(commands=Mock()))),patch.object(self.module.asyncio,'sleep',side_effect=fake_sleep):
            self.addon.websocket_start(flow);await asyncio.gather(*list(self.addon.tasks))
        self.assertEqual(len(requested),2);self.assertTrue(299<requested[0]<=300);self.assertTrue(309<requested[1]<=310)
