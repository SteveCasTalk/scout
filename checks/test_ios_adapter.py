"""iOS adapter regression checks using synthetic hierarchies, no live device."""
import base64
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from xml.sax.saxutils import quoteattr

from scout_mobile.ios_device import AppiumIOSDevice
from scout_mobile.device import DeviceError
from scout_mobile.agent import Agent, RunConfig
from scout_mobile.model import choose


def node(kind, label='', **extra):
    attrs = {'type': 'XCUIElementType'+kind, 'label': label, 'name': label, 'x': '10', 'y': '100', 'width': '200', 'height': '40', 'visible': 'true', 'enabled': 'true', **extra}
    return '<XCUIElementType'+kind+' '+' '.join(f'{k}={quoteattr(str(v))}' for k,v in attrs.items())+'/>'


def device(*nodes):
    d = AppiumIOSDevice('fixture', 'com.example.app', 'http://127.0.0.1:4723')
    d._driver = Mock()
    d.driver.page_source = '<AppiumAUT>'+''.join(nodes)+'</AppiumAUT>'
    d.driver.get_window_size.return_value = {'width': 390, 'height': 844}
    return d


class IOSAdapterTests(unittest.TestCase):
    def test_keyboard_is_not_evidence_of_every_field_being_focused(self):
        d=device(node('TextField','Email',focused='true'),node('SecureTextField','Password',y=160,focused='false'),node('Keyboard','Keyboard',y=400))
        screen=d.observe()
        self.assertEqual([e.focused for e in screen.elements],[True,False])
        self.assertFalse(d.capture_safe(screen))

    def test_missing_focus_stays_unknown_and_native_input_targets_exact_element(self):
        d=device(node('TextField','Email',value='Email'))
        field=d.observe().elements[0]
        self.assertFalse(field.focused)
        target=Mock()
        target.get_attribute.return_value='person@example.test'
        d.driver.find_elements.return_value=[target]
        d.type_text(field,'person@example.test')
        target.clear.assert_called_once()
        target.send_keys.assert_called_once_with('person@example.test')
        target.click.assert_not_called()

    def test_text_verification_does_not_accept_another_field(self):
        d=device(node('TextField','Email'))
        target=Mock()
        target.get_attribute.return_value='wrong'
        d.driver.find_elements.return_value=[target]
        with self.assertRaises(DeviceError):d.type_text(d.observe().elements[0],'expected')

    def test_supported_controls_and_explicit_accessible_custom_elements(self):
        d=device(node('PickerWheel','Month'),node('Slider','Volume',y=150),node('Other','Custom action',y=200,accessible='true'),node('Other','Container',y=250,accessible='false'),node('StaticText','Link',y=300,accessible='true'))
        screen=d.observe()
        self.assertEqual([e.role for e in screen.elements],['picker','slider','button','button'])
        self.assertEqual(screen.elements[0].operations,('SET_VALUE',))
        self.assertNotIn('Container',[e.label for e in screen.elements])

    def test_picker_sets_and_verifies_exact_value_without_clearing(self):
        d=device(node('PickerWheel','Month',value='January'))
        target=Mock()
        target.get_attribute.return_value='March'
        d.driver.find_elements.return_value=[target]
        d.set_value(d.observe().elements[0],'March')
        target.send_keys.assert_called_once_with('March')
        target.clear.assert_not_called()

    def test_slider_rejects_invalid_or_nonfinite_values_before_action(self):
        d=device(node('Slider','Volume',value='50%'))
        field=d.observe().elements[0]
        for value in ('-1','1.1','nan','inf','50%'):
            with self.subTest(value=value), self.assertRaises(DeviceError):d.set_value(field,value)
        d.driver.find_elements.assert_not_called()

    def test_slider_verifies_normalized_position(self):
        d=device(node('Slider','Volume',value='10%'))
        target=Mock()
        target.get_attribute.return_value='50%'
        d.driver.find_elements.return_value=[target]
        d.set_value(d.observe().elements[0],'0.5')
        target.send_keys.assert_called_once_with('0.5')

    def test_alert_hides_underlying_app_controls(self):
        alert='<XCUIElementTypeAlert type="XCUIElementTypeAlert" visible="true">'+node('Button','Allow')+'</XCUIElementTypeAlert>'
        d=device(node('Button','Underlying purchase'),alert)
        screen=d.observe()
        self.assertEqual([e.label for e in screen.elements],['Allow'])
        self.assertTrue(d.permits_foreground('com.apple.springboard',screen))
        self.assertFalse(d.permits_foreground('com.apple.mobilesafari',screen))
        self.assertFalse(device(node('Button','Home')).permits_foreground('com.apple.springboard',device(node('Button','Home')).observe()))

    def test_ios_selector_exposes_value_action_but_not_system_back(self):
        d=device(node('PickerWheel','Month',value='January'))
        captured=[]
        def respond(url,key,body):
            captured.append(body)
            return {'answers': {name: {'choice': ('SET_VALUE' if name=='operation' else next(iter(q['criteria']))), 'confidence':1, 'probabilities':{k:int(k==('SET_VALUE' if name=='operation' else next(iter(q['criteria'])))) for k in q['criteria']}} for name,q in body['questions'].items()}}
        with patch.dict('os.environ',{'TYPESAFE_API_KEY':'fixture'}),patch('scout_mobile.model.post_json',side_effect=respond):
            self.assertEqual(choose(d.observe().elements,'Month','Select March',[],platform='iOS')['operation'],'SET_VALUE')
        self.assertNotIn('BACK',captured[0]['questions']['operation']['criteria'])
        self.assertEqual(captured[0]['state']['page']['url'],'ios://device')

    def test_ios_does_not_run_android_birthday_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            agent=Agent(RunConfig('com.example.app','fixture',{'platform':'iOS'},Path(directory)))
            screen=device(node('Button','Birthday Save')).observe()
            self.assertIsNone(agent._base_date_gate_step(screen))
            self.assertFalse(agent.date_gate_attempted)

    def test_recording_stops_before_requested_session_close(self):
        d=device(node('Button','Home'))
        driver=d.driver
        driver.stop_recording_screen.return_value=base64.b64encode(b'fixture-video').decode()
        with tempfile.TemporaryDirectory() as directory:
            with d.screen_recording(Path(directory)):
                d.close()
                driver.quit.assert_not_called()
            driver.stop_recording_screen.assert_called_once()
            driver.quit.assert_called_once()
            self.assertEqual(len(list(Path(directory).glob('*.mp4'))),1)

    def test_syslog_only_returns_target_pid(self):
        d=device(node('Button','Home'))
        d.driver.execute_script.return_value={'bundleId':'com.example.app','pid':123}
        d.driver.get_log.return_value=[{'message':'App[123]: expected\nOther[1234]: private\nOther: unrelated'}]
        self.assertEqual(d.app_logs(),'App[123]: expected')

class IOSRunnerTests(unittest.TestCase):
    def agent(self, directory, screen, **config):
        agent=Agent(RunConfig('com.example.app','fixture',{'platform':'iOS','goal':'Login','steps':'Enter email','expected':'Ready'},Path(directory),expected_text='Ready',test_email='person@example.test',**config))
        d=Mock(spec=AppiumIOSDevice)
        d.installed.return_value=True
        d.foreground.return_value='com.example.app'
        d.permits_foreground.return_value=True
        d.has_alert.return_value=False
        d.capture_safe.return_value=True
        d.wait_for_content.return_value=screen
        d.observe.return_value=screen
        d.wait_for_change.return_value=screen
        d.metadata.return_value={}
        d.app_logs.return_value=''
        agent.device=d
        return agent,d

    @staticmethod
    def decision(operation,target=None):
        return {'operation':operation,'target':target,'confidence':1,'model':'fixture','latency_ms':0,'jev':{}}

    def test_input_does_not_require_or_guess_focused_field(self):
        screen=device(node('TextField','Email'),node('StaticText','Ready')).observe()
        with tempfile.TemporaryDirectory() as directory:
            agent,d=self.agent(directory,screen)
            with patch('scout_mobile.agent.choose',side_effect=[self.decision('TYPE_TEXT','1'),self.decision('DONE')]):
                result=agent.run()
            self.assertEqual(result['status'],'Passed')
            d.type_text.assert_called_once_with(screen.elements[0],'person@example.test')
            d.tap.assert_not_called()

    def test_unapproved_alert_blocks_before_click(self):
        screen=device(node('Button','Allow')).observe()
        with tempfile.TemporaryDirectory() as directory:
            agent,d=self.agent(directory,screen)
            d.has_alert.return_value=True
            with patch('scout_mobile.agent.choose',return_value=self.decision('TAP','1')):
                result=agent.run()
            self.assertEqual(result['status'],'Blocked')
            d.tap.assert_not_called()

    def test_authorized_alert_can_be_clicked(self):
        screen=device(node('Button','Allow'),node('StaticText','Ready')).observe()
        with tempfile.TemporaryDirectory() as directory:
            agent,d=self.agent(directory,screen,allow_consent=True)
            d.has_alert.return_value=True
            with patch('scout_mobile.agent.choose',side_effect=[self.decision('TAP','1'),self.decision('DONE')]):
                result=agent.run()
            self.assertEqual(result['status'],'Passed')
            d.tap.assert_called_once_with(screen.elements[0])

    def test_external_app_boundary_is_blocked_not_reported_as_app_failure(self):
        screen=device(node('Button','Continue')).observe()
        with tempfile.TemporaryDirectory() as directory:
            agent,d=self.agent(directory,screen)
            d.foreground.return_value='com.apple.mobilesafari'
            d.permits_foreground.return_value=False
            with patch('scout_mobile.agent.choose') as selector:
                result=agent.run()
            self.assertEqual(result['status'],'Blocked')
            selector.assert_not_called()
