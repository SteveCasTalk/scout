"""Synthetic contract/safety checks. These do not claim Twomi device acceptance."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET
from scout_mobile.agent import Agent,RunConfig
from scout_mobile.device import AndroidDevice, DeviceError, Screen
from scout_mobile.execution_contract import validate_execution,validate_authorizations,decode_export,export_case
from scout_mobile.execution_runtime import Boundary,Protocol,locate,ExecutionBlocked
from scout_mobile.temporal import TemporalState
from scout_mobile.network_contract import matches,assert_structure
from scout_mobile.sandbox import validate as sandbox_validate
from scout_mobile.capabilities import negotiate
from scout_mobile.lifecycle import Lifecycle
from scout_mobile.media_verification import verify_metadata

PKG='com.example.synthetic';STORE='com.android.vending'

def screen(text='Synthetic shop',button='Subscribe',clickable=True):
    xml=f'<hierarchy><node text="{text}" class="Text" bounds="[0,0][500,60]"/><node text="{button}" resource-id="app:id/cta" class="Button" clickable="{str(clickable).lower()}" bounds="[20,100][420,180]"/></hierarchy>'
    d=AndroidDevice('synthetic');d.size=lambda:(500,900)
    return d._parse(ET.fromstring(xml),xml)

def purchase_spec():
    return validate_execution({'required_capabilities':['purchase_entry','external_packages'],'purchase_entries':[{'id':'entry','selector':{'resource_id':'app:id/cta'},'screen_text':'Synthetic shop','destination_package':STORE,'destination_text':'Synthetic checkout'}],'external_flows':[{'package':STORE,'from_package':PKG,'entry_text':'Synthetic checkout','return_text':'Synthetic shop','require_return':False,'checkout':True}],'actions':[{'id':'open','operation':'PURCHASE_ENTRY','package':PKG,'entry_id':'entry'}]})

def temporal(mode='within',**kwargs):
    spec=validate_execution({'required_capabilities':['temporal_ui'],'actions':[{'id':'trigger','operation':'OBSERVE','package':PKG}],'temporal_assertions':[{'id':'timer','after_action':'trigger','mode':mode,'text':'Ready','context_text':'Synthetic','window_ms':1000,**kwargs}]})
    return spec['temporal_assertions'][0]

class ContractTests(unittest.TestCase):
    def test_legacy_export_stays_flat_and_new_export_rejects_old_loader(self):
        old={'id':'case','revision':1,'goal':'Observe','steps':'Observe','expected':'Visible'}
        self.assertIs(export_case(old),old)
        new={**old,'execution':purchase_spec()};export=export_case(new)
        self.assertEqual(decode_export(export),new)
        self.assertFalse(all(k in export for k in ('id','revision','goal','steps','expected')))
    def test_unknown_and_omitted_requirements_are_rejected(self):
        with self.assertRaises(ValueError):validate_execution({'actions':[{'id':'gesture','operation':'SWIPE','package':PKG,'selector':{'text':'Message'}}]})
        with tempfile.TemporaryDirectory() as folder,patch.dict('os.environ',{'SCOUT_ANDROID_DRIVER':'adb'}):
            with self.assertRaisesRegex(ValueError,'Unsupported'):Agent(RunConfig(PKG,'synthetic',{'execution':{'required_capabilities':['unknown']}},Path(folder)))
    def test_grants_cannot_widen_case_and_consent_is_separate(self):
        with self.assertRaises(ValueError):validate_authorizations({'purchase_entries':['other']},purchase_spec())
        with self.assertRaises(ValueError):validate_authorizations({'clear_data':True},purchase_spec())
        self.assertEqual(validate_authorizations(None,purchase_spec())['purchase_entries'],[])
    def test_handshake_cannot_drop_capability(self):
        with self.assertRaises(ValueError):negotiate(purchase_spec(),{'contract_versions':[1],'features':[]})
    def test_no_model_or_additional_taps_after_purchase_entry(self):
        spec=purchase_spec();spec['finish']='model'
        with self.assertRaises(ValueError):validate_execution(spec)
        spec=purchase_spec();spec['actions'].append({'id':'confirm','operation':'TAP','package':STORE,'selector':{'text':'Confirm'}})
        with self.assertRaises(ValueError):validate_execution(spec)
    def test_nonclickable_gesture_nodes_are_grounded_but_not_tappable(self):
        s=screen(button='Message',clickable=False)
        self.assertEqual(locate(s,{'text':'Message'}).bounds,(20,100,420,180))
        with self.assertRaises(ExecutionBlocked):locate(s,{'text':'Message'},tap=True)
    def test_ambiguous_or_disabled_nodes_stop(self):
        s=screen();s.xml=s.xml.replace('</hierarchy>','<node text="Subscribe" resource-id="app:id/cta" class="Button" clickable="true" bounds="[20,200][420,280]"/></hierarchy>')
        with self.assertRaises(ExecutionBlocked):locate(s,{'resource_id':'app:id/cta'},tap=True)
        s=screen();s.xml=s.xml.replace('clickable="true"','clickable="true" enabled="false"')
        with self.assertRaises(ExecutionBlocked):locate(s,{'resource_id':'app:id/cta'},tap=True)

class ProtocolTests(unittest.TestCase):
    def make_agent(self,folder,grants=None):
        a=Agent(RunConfig(PKG,'synthetic',{'id':'synthetic','revision':1,'execution':purchase_spec()},Path(folder),backend='appium',authorizations=grants))
        a.device=Mock();a.screenshot=Mock(return_value=None)
        a.boundary=Boundary(a);a.protocol=Protocol(a)
        return a
    def test_purchase_taps_once_and_stops_before_confirmation(self):
        with tempfile.TemporaryDirectory() as folder:
            a=self.make_agent(folder,{'purchase_entries':['entry']});before=screen();checkout=screen('Synthetic checkout','Confirm')
            a.device.observe.side_effect=[before,checkout];a.device.foreground.side_effect=[PKG,STORE]
            a.protocol.run();a.device.tap.assert_called_once()
            self.assertEqual(a.protocol.consumed,{'entry'})
            with self.assertRaises(ExecutionBlocked):a.boundary.authorize('TAP',checkout.elements[0])
            evidence=json.loads((Path(folder)/'execution-evidence.json').read_text())
            self.assertEqual(evidence['events'][0]['event'],'purchase_entry_consumed')
    def test_consent_does_not_authorize_purchase_and_failure_does_not_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            a=self.make_agent(folder);a.config.allow_consent=True;a.device.observe.return_value=screen();a.device.foreground.return_value=PKG
            with self.assertRaises(ExecutionBlocked):a.protocol.run()
            a.device.tap.assert_not_called()
        with tempfile.TemporaryDirectory() as folder:
            a=self.make_agent(folder,{'purchase_entries':['entry']});a.device.observe.return_value=screen();a.device.foreground.return_value=PKG;a.device.tap.side_effect=DeviceError('lost response')
            with self.assertRaises(DeviceError):a.protocol.run()
            with self.assertRaises(ExecutionBlocked):a.protocol.run()
            a.device.tap.assert_called_once()
    def test_unknown_destination_and_wrong_return_are_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            a=self.make_agent(folder)
            with self.assertRaises(ExecutionBlocked):a.boundary.check('com.example.unexpected',screen())
            a.boundary.check(STORE,screen('Synthetic checkout'))
            with self.assertRaises(ExecutionBlocked):a.boundary.check(PKG,screen('Wrong screen'))
            with self.assertRaises(ExecutionBlocked):a.boundary.check('',screen())
    def test_safe_return_is_allowed_and_verified(self):
        with tempfile.TemporaryDirectory() as folder:
            a=self.make_agent(folder);a.boundary.flows[STORE]['allow_back']=True
            a.boundary.check(STORE,screen('Synthetic checkout'));a.boundary.authorize('BACK')
            a.boundary.check(PKG,screen());self.assertTrue(a.boundary.return_verified)

class TemporalTests(unittest.TestCase):
    def test_within_uses_observation_completion_timestamp(self):
        s=TemporalState(temporal(),100);s.feed(900,1050,True,True);self.assertEqual(s.verdict,'satisfied')
        s=TemporalState(temporal(),100);s.feed(1050,1150,True,True);self.assertEqual(s.verdict,'not_observable')
    def test_absence_never_passes_from_samples_but_violation_is_observable(self):
        s=TemporalState(temporal('never_during'),0);s.feed(0,20,True,False);s.feed(990,1010,True,False);self.assertEqual(s.verdict,'not_observable')
        s=TemporalState(temporal('never_during'),0);s.feed(10,20,True,True);self.assertEqual(s.verdict,'violated')
    def test_stability_requires_context_gap_budget_and_multiple_samples(self):
        s=TemporalState(temporal('stable_for'),0);s.feed(0,100,True,True);s.feed(950,1000,True,True);self.assertEqual(s.verdict,'satisfied')
        s=TemporalState(temporal('stable_for',max_gap_ms=100),0);s.feed(0,1000,True,True);self.assertEqual(s.verdict,'not_observable')
        s=TemporalState(temporal('stable_for'),0);s.feed(0,100,False,False);s.feed(950,1000,True,True);self.assertEqual(s.verdict,'not_observable')
    def test_continuous_requirement_cannot_use_sampled_success(self):
        s=TemporalState(temporal(evidence='continuous_events'),0);s.feed(0,20,True,True);self.assertEqual(s.verdict,'not_observable')
    def test_ordered_tied_events_do_not_establish_order(self):
        s=TemporalState(temporal('ordered',ordered_texts=['First','Second']),0);s.feed(0,20,True,False,hits=[0,1]);s.feed(950,1000,True,False);self.assertEqual(s.verdict,'not_observable')
        s=TemporalState(temporal('ordered',ordered_texts=['First','Second']),0);s.feed(0,20,True,False,hits=[1]);self.assertEqual(s.verdict,'violated')

class NetworkTests(unittest.TestCase):
    def request(self,path='/synthetic?buddy=b',body=b'{}'):
        return SimpleNamespace(path=path,host='example.test',method='GET',headers={},raw_content=body)
    def fixture(self,version=2):
        return {'schema_version':version,'id':'synthetic','name':'Synthetic contract','project':'Synthetic','hosts':['example.test'],'http':[{'id':'b','host':'example.test','path':'/synthetic','responses':[{}],**({'match':[{'source':'query','key':'buddy','value':'b'}]} if version==2 else {})}]}
    def test_contract_match_distinguishes_query_identity_and_duplicate_query(self):
        rule=sandbox_validate(self.fixture())['http'][0]
        self.assertIsNotNone(matches(rule,self.request()))
        self.assertIsNone(matches(rule,self.request('/synthetic?buddy=a')))
        self.assertIsNone(matches(rule,self.request('/synthetic?buddy=b&buddy=a')))
    def test_templates_are_bounded_segments_and_json_booleans_not_numbers(self):
        f=self.fixture();f['http'][0].update(path='/synthetic/{buddy}',path_template=True,match=[{'source':'json','key':'/enabled','value':True}]);rule=sandbox_validate(f)['http'][0]
        self.assertIsNone(matches(rule,self.request('/synthetic/b',b'{"enabled":1}')))
        self.assertIsNotNone(matches(rule,self.request('/synthetic/b',b'{"enabled":true}')))
        self.assertIsNone(matches(rule,self.request('/synthetic/b/extra',b'{"enabled":true}')))
    def test_structural_failures_never_serialize_observed_private_values(self):
        f=self.fixture();f['http'][0]['assertions']=[{'id':'report','source':'json','key':'/messages','kind':'count','expected':10},{'id':'unique','source':'json','key':'/id','kind':'duplicate'}]
        rule=sandbox_validate(f)['http'][0];view=matches(rule,self.request(body=b'{"messages":["PRIVATE CONVERSATION"],"id":"PRIVATE ID"}'));history={}
        first=assert_structure(rule,view,history);second=assert_structure(rule,view,history)
        self.assertEqual(first[0]['verdict'],'violated');self.assertEqual(second[1]['verdict'],'violated')
        self.assertNotIn('PRIVATE',json.dumps(first+second))
    def test_secrets_rejected_and_v1_push_limit_preserved(self):
        f=self.fixture();f['http'][0]['match']=[{'source':'header','key':'Authorization','value':'secret'}]
        with self.assertRaises(ValueError):sandbox_validate(f)
        f=self.fixture(1);f['websocket']=[{'id':'ws','host':'example.test','path':'/ws','pushes':[{'after_ms':300000}]}]
        with self.assertRaises(ValueError):sandbox_validate(f)
        f['schema_version']=2;self.assertEqual(sandbox_validate(f)['websocket'][0]['pushes'][0]['after_ms'],300000)

class CleanupAndMediaTests(unittest.TestCase):
    def test_cleanup_journal_precedes_mutation_and_restore_is_verified(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'run';output.mkdir();device=Mock();agent=SimpleNamespace(output=output,config=SimpleNamespace(serial='synthetic',package=PKG),device=device,authorizations={'clear_data':False},execution={'lifecycle':{'before':[{'id':'wifi','operation':'wifi','enabled':False}]}})
            manager=Lifecycle(agent);state={'wifi':True}
            manager.value=lambda hook:state['wifi']
            def apply(hook,enabled):
                self.assertEqual(json.loads(manager.journal.read_text())['phase'],'pending');state['wifi']=enabled
            manager.apply=apply;manager.prepare();manager.restore()
            self.assertTrue(state['wifi']);self.assertEqual(json.loads(manager.journal.read_text())['phase'],'restored')
    def test_incomplete_previous_cleanup_blocks_new_preparation(self):
        with tempfile.TemporaryDirectory() as folder:
            previous=Path(folder)/'old';previous.mkdir();(previous/'.lifecycle.json').write_text(json.dumps({'device':'synthetic','phase':'failed'}));output=Path(folder)/'new';output.mkdir()
            manager=Lifecycle(SimpleNamespace(output=output,config=SimpleNamespace(serial='synthetic'),execution={'lifecycle':{'before':[]}}))
            with self.assertRaises(ExecutionBlocked):manager.prepare()
    def test_missing_media_verifier_or_artifact_is_inconclusive(self):
        with tempfile.TemporaryDirectory() as folder:
            rule=validate_execution({'required_capabilities':['media_metadata'],'media_assertions':[{'id':'video','artifact':'export.mp4'}]})['media_assertions'][0]
            self.assertEqual(verify_metadata(Path(folder),[rule])[0]['verdict'],'not_observable')
            (Path(folder)/'export.mp4').write_bytes(b'synthetic')
            with patch('scout_mobile.media_verification.shutil.which',return_value=None):self.assertEqual(verify_metadata(Path(folder),[rule])[0]['verdict'],'not_observable')

if __name__=='__main__':unittest.main()
