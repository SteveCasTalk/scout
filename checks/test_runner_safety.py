"""Safety checks for Jev selection and credential handling, using a real observed app state."""
import json
import os
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest.mock import Mock, patch
from scout_mobile.agent import Agent,RunConfig,GUARD_TEXT
from scout_mobile.device import AndroidDevice
from scout_mobile.model import ModelError,validate_choice,choose

STARTUP_XML='''<hierarchy><node class="android.widget.FrameLayout" bounds="[0,0][1344,2992]" clickable="false"><node text="This application is not supported on rooted devices or emulators." class="android.widget.TextView" bounds="[264,1375][1080,1481]" clickable="false"/><node text="OK" class="android.widget.Button" bounds="[264,1553][1080,1703]" clickable="true"/></node></hierarchy>'''

class RunnerSafetyTests(unittest.TestCase):
 def setUp(self):
  # This suite injects the legacy ADB transport; Appium has separate contracts.
  backend=patch.dict(os.environ,{'SCOUT_ANDROID_DRIVER':'adb'})
  backend.start();self.addCleanup(backend.stop)
 def test_device_prompt_settings_are_restored_after_failed_run(self):
  from subprocess import CompletedProcess
  device=AndroidDevice('fake')
  original={'autofill_service':'samsung/autofill','credential_service':'google: samsung','credential_service_primary':'samsung/primary'}
  current=original.copy()
  def command(*args,**_kwargs):
   if args[1:3]==('settings','list'):
    data=''.join(f'{key}={value}\n' for key,value in current.items())
   elif args[1:3]==('settings','get'):
    data=current.get(args[4],'null')+'\n'
   elif args[1:3]==('settings','put'):
    current[args[4]]='' if args[5]=="''" else args[5]
    data=''
   elif args[1:3]==('settings','delete'):
    current.pop(args[4],None)
    data=''
   else:raise AssertionError(args)
   return CompletedProcess(args,0,data.encode(),b'')
  device.command=command
  with self.assertRaisesRegex(RuntimeError,'test failed'):
   with device.suppress_credential_prompts():
    self.assertEqual(set(current.values()),{''})
    raise RuntimeError('test failed')
  self.assertEqual(current,original)

 def test_notification_permission_is_temporarily_granted_silenced_and_restored(self):
  from subprocess import CompletedProcess
  device=AndroidDevice('fake');permission='android.permission.POST_NOTIFICATIONS';package='com.example.app'
  state={'granted':False,'appop':'allow'}
  def command(*args,**_kwargs):
   if args[1:3]==('dumpsys','package'):
    data=f'{permission}: granted={str(state["granted"]).lower()}, flags=[]\n'
   elif args[1:4]==('cmd','appops','get'):
    data=f'Uid mode: POST_NOTIFICATION: {state["appop"]}\n'
   elif args[1:3]==('pm','grant'):
    state['granted']=True;data=''
   elif args[1:3]==('pm','revoke'):
    state['granted']=False;data=''
   elif args[1:4]==('cmd','appops','set'):
    state['appop']=args[6];data=''
   else:raise AssertionError(args)
   return CompletedProcess(args,0,data.encode(),b'')
  device.command=command
  with device.suppress_notification_prompt(package):
   self.assertTrue(state['granted'])
   self.assertEqual(state['appop'],'ignore')
  self.assertFalse(state['granted'])
  self.assertEqual(state['appop'],'allow')

 def test_actual_startup_alert_is_not_treated_as_authentication_failure(self):
  assert GUARD_TEXT in STARTUP_XML
  device=AndroidDevice('emulator-5554')
  device.size=lambda:(1344,2992)
  screen=device._parse(ET.fromstring(STARTUP_XML),STARTUP_XML)
  self.assertEqual([(e.label,e.center) for e in screen.elements],[('OK',(672,1628))])
  self.assertIn(GUARD_TEXT,screen.text)

 def test_disabled_save_button_is_not_exposed_as_an_action(self):
  xml='<hierarchy><node text="Your Birthday" class="android.widget.TextView" bounds="[10,10][200,60]"/><node text="Save" class="android.widget.Button" enabled="false" clickable="true" bounds="[10,100][200,150]"/></hierarchy>'
  device=AndroidDevice('fake');device.size=lambda:(1080,2340)
  screen=device._parse(ET.fromstring(xml),xml)
  save=next(element for element in screen.elements if element.label=='Save')
  self.assertEqual(save.operations,())

 def test_generic_date_gate_confirms_one_selected_value_then_submits_once(self):
  from scout_mobile.device import Element,Screen
  birthday=Element('1','button','Your Birthday','','Button','',(10,10,200,60),('TAP',),False)
  confirm=Element('2','button','Confirm','','Button','',(10,70,200,120),('TAP',),False)
  selected=Element('3','control','Saturday, January 1, 2000','','TextView','',(10,130,200,180),('TAP',),False,checked=True,checkable=True)
  save=Element('1','button','Save','','Button','',(10,100,200,150),('TAP',),False)
  before=Screen('',[birthday,save],'Your Birthday · By saving, I agree to Twomi Terms of Use and acknowledge the Privacy Policy · Save','before',1080,2340)
  picker=Screen('',[confirm,selected],'Select your birthday · Saturday, January 1, 2000 · Confirm','picker',1080,2340)
  form=Screen('',[save],'Your Birthday · 2000/01/01 · By saving, I agree to Twomi Terms of Use and acknowledge the Privacy Policy · Save','form',1080,2340)
  feed=Screen('',[],'Swipe up to select your companion','feed',1080,2340)
  agent=Agent(RunConfig('example.other.app','fake',{'goal':'Sign in'},Path(tempfile.mkdtemp()),allow_consent=True))
  agent.device=Mock();agent.device.wait_for_change.side_effect=[picker,form,feed]
  agent.screenshot=Mock(return_value='evidence.png')
  result=agent._base_date_gate_step(before)
  self.assertIs(result,feed)
  self.assertEqual(agent.device.tap.call_args_list,[unittest.mock.call(birthday),unittest.mock.call(confirm),unittest.mock.call(save)])
  self.assertEqual([item['base_step'] for item in agent.history],[
   'Date gate: open date picker',
   'Date gate: confirm preselected date 2000-01-01',
   'Date gate: submit confirmed date 2000-01-01',
  ])

 def test_generic_date_gate_runs_before_jev_decisions(self):
  from scout_mobile.device import Element,Screen
  birthday=Element('1','button','Your Birthday','','Button','',(10,10,200,60),('TAP',),False)
  confirm=Element('2','button','Confirm','','Button','',(10,70,200,120),('TAP',),False)
  selected=Element('3','control','Saturday, January 1, 2000','','TextView','',(10,130,200,180),('TAP',),False,checked=True,checkable=True)
  save=Element('1','button','Save','','Button','',(10,100,200,150),('TAP',),False)
  before=Screen('',[birthday,save],'Your Birthday · By saving, I agree to Twomi Terms of Use and acknowledge the Privacy Policy · Save','before',1080,2340)
  picker=Screen('',[confirm,selected],'Select your birthday · Saturday, January 1, 2000 · Confirm','picker',1080,2340)
  form=Screen('',[save],'Your Birthday · 2000/01/01 · By saving, I agree to Twomi Terms of Use and acknowledge the Privacy Policy · Save','form',1080,2340)
  feed=Screen('',[],'Twomi home feed ready','feed',1080,2340)
  fake=Mock();fake.wait_for_content.return_value=before;fake.observe.return_value=feed;fake.foreground.return_value='example.other.app';fake.installed.return_value=True
  fake.command.return_value=SimpleNamespace(stdout=b'versionName=1.0\n')
  fake.wait_for_change.side_effect=[picker,form,feed]
  fake.screenshot.side_effect=lambda path:Path(path).write_bytes(b'png')
  with tempfile.TemporaryDirectory() as directory,patch('scout_mobile.agent.AndroidDevice',return_value=fake),patch('scout_mobile.agent.choose',return_value={'operation':'DONE','target':None,'confidence':1,'model':'test','latency_ms':1,'jev':{}}) as chooser:
   result=Agent(RunConfig('example.other.app','fake',{'goal':'Reach the home feed'},Path(directory),expected_text='home feed ready',allow_consent=True)).run()
  self.assertEqual(result['status'],'Passed')
  self.assertEqual(chooser.call_count,1)
  self.assertEqual([entry['operation'] for entry in result['steps'][1:4]],['BASE_STEP_TAP']*3)

 def test_generic_date_gate_does_not_submit_without_consent_authorization(self):
  from scout_mobile.device import Element,Screen
  field=Element('1','button','Your Birthday','','Button','',(10,10,200,60),('TAP',),False)
  save=Element('2','button','Save','','Button','',(10,100,200,150),('TAP',),False)
  screen=Screen('',[field,save],'Your Birthday · By saving, I agree to Twomi Terms of Use and acknowledge the Privacy Policy · Save','before',1080,2340)
  agent=Agent(RunConfig('com.torilab.twomi.uat','fake',{'goal':'Sign in'},Path(tempfile.mkdtemp()),allow_consent=False))
  agent.device=Mock()
  self.assertIsNone(agent._base_date_gate_step(screen))
  agent.device.tap.assert_not_called()

 def test_generic_date_gate_never_changes_a_preselected_date(self):
  from scout_mobile.device import DeviceError,Element,Screen
  field=Element('1','button','Your Birthday','','Button','',(10,10,200,60),('TAP',),False)
  selected=Element('2','control','Friday, January 1, 2016','','TextView','',(10,70,200,120),('TAP',),False,checked=True,checkable=True)
  confirm=Element('3','button','Confirm','','Button','',(10,130,200,180),('TAP',),False)
  before=Screen('',[field],'Your Birthday · Save','before',1080,2340)
  picker=Screen('',[selected,confirm],'Select your birthday · Friday, January 1, 2016 · Confirm','picker',1080,2340)
  agent=Agent(RunConfig('com.torilab.twomi.uat','fake',{'goal':'Sign in'},Path(tempfile.mkdtemp()),allow_consent=True))
  agent.device=Mock();agent.device.wait_for_change.return_value=picker
  with self.assertRaisesRegex(DeviceError,'no date was saved'):
   agent._base_date_gate_step(before)
  self.assertEqual([call.args[0].label for call in agent.device.tap.call_args_list],['Your Birthday','Confirm'])

 def test_birthday_save_is_a_consent_action_when_screen_says_by_saving(self):
  self.assertTrue(Agent.consent_confirmation_required('Save','By saving, I agree to Twomi Terms of Use and acknowledge the Privacy Policy'))

 def test_notification_restore_without_existing_override_resets_only_notification_op(self):
  from subprocess import CompletedProcess
  device=AndroidDevice('fake')
  def command(*args,**kwargs):
   if args[1:3]==('dumpsys','package'):
    return CompletedProcess(args,0,b'android.permission.POST_NOTIFICATIONS: granted=true\n',b'')
   if args[1:4]==('cmd','appops','get'):
    return CompletedProcess(args,0,b'No operations.\n',b'')
   return CompletedProcess(args,0,b'',b'')
  device.command=Mock(side_effect=command)
  with device.suppress_notification_prompt('app'):pass
  device.command.assert_any_call('shell','cmd','appops','set','app','POST_NOTIFICATION','default',timeout=15)
  self.assertFalse(any('reset' in call.args for call in device.command.call_args_list))

 def test_tutorial_swipe_starts_inside_feed_not_bottom_controls(self):
  from scout_mobile.device import Screen
  xml='<hierarchy><node scrollable="true" enabled="true" bounds="[0,0][1080,1721]"/><node scrollable="true" bounds="[0,1900][1080,2200]"/></hierarchy>'
  screen=Screen(xml,[],'Swipe up to select your companion','tutorial',1080,2340)
  device=AndroidDevice('fake');device.command=Mock()
  gesture=device.swipe_scrollable_next_item(1080,2340,screen)
  self.assertEqual(gesture['viewport'],[0,0,1080,1721])
  self.assertEqual(gesture['source'],'accessibility_scrollable_bounds')
  self.assertEqual(gesture['start'],[540,1548])
  self.assertEqual(gesture['end'],[540,172])
  device.command.assert_called_once_with('shell','input','swipe','540','1548','540','172','300')

 def test_tutorial_swipe_without_bounds_avoids_bottom_navigation(self):
  device=AndroidDevice('fake');device.command=Mock()
  gesture=device.swipe_scrollable_next_item(1080,2340)
  self.assertEqual(gesture['source'],'fallback_content_region')
  self.assertLess(gesture['start'][1],2340*.70)
  self.assertGreater(gesture['start'][1]-gesture['end'][1],2340*.50)

 def test_tutorial_dismissal_resumes_case_and_records_gesture(self):
  from scout_mobile.device import Screen
  before=Screen('',[],'Swipe up to select your companion','tutorial',1080,2340)
  after=Screen('',[],'troy john','feed',1080,2340)
  fake=Mock();fake.wait_for_content.return_value=before;fake.observe.return_value=after
  fake.wait_for_change.return_value=after;fake.foreground.return_value='app';fake.installed.return_value=True
  fake.command.return_value=SimpleNamespace(stdout=b'versionName=1.0\n')
  fake.screenshot.side_effect=lambda path:Path(path).write_bytes(b'png')
  gesture={'start':[270,1548],'end':[270,172],'duration_ms':300}
  fake.swipe_scrollable_next_item.return_value=gesture
  decisions=[{'operation':op,'target':None,'confidence':1,'model':'test','latency_ms':1,'jev':{}} for op in ('SWIPE_UP','DONE')]
  with tempfile.TemporaryDirectory() as directory,patch('scout_mobile.agent.AndroidDevice',return_value=fake),patch('scout_mobile.agent.choose',side_effect=decisions):
   result=Agent(RunConfig('app','fake',{'goal':'Reach the next feed item','steps':'Complete tutorial'},Path(directory),expected_text='troy john')).run()
  self.assertEqual(result['status'],'Passed')
  self.assertEqual(result['steps'][1]['gesture'],gesture)
  fake.swipe_scrollable_next_item.assert_called_once()
  fake.tap.assert_not_called()

 def test_startup_waits_for_splash_to_expose_accessible_content(self):
  from scout_mobile.device import Screen
  device=AndroidDevice('fake')
  blank=Screen('<hierarchy/>',[],'','blank',1080,1920)
  ready=Screen('<hierarchy/>',[],'Welcome','ready',1080,1920)
  device.observe=Mock(side_effect=[blank,ready,ready])
  with patch('scout_mobile.device.time.sleep'):
   self.assertIs(device.wait_for_content(.5),ready)

 def test_startup_discards_stale_profile_hierarchy_until_new_screen_is_stable(self):
  from scout_mobile.device import Screen
  device=AndroidDevice('fake')
  stale=Screen('<hierarchy/>',[],'Edit · Username','stale-profile',1080,2340)
  welcome=Screen('<hierarchy/>',[],'Welcome to Twomi · Continue','welcome',1080,2340)
  device.observe=Mock(side_effect=[stale,welcome,welcome])
  with patch('scout_mobile.device.time.sleep'):
   self.assertIs(device.wait_for_content(.5),welcome)

 def test_model_choice_cannot_name_unobserved_target(self):
  answer={'choice':'2','confidence':.9,'probabilities':{'1':.1,'2':.9}}
  with self.assertRaises(ModelError):validate_choice(answer,{'1'})

 def test_credentials_are_redacted_from_model_view_and_output(self):
  old_email=os.environ.get('SCOUT_TEST_EMAIL');old_password=os.environ.get('SCOUT_TEST_PASSWORD')
  os.environ['SCOUT_TEST_EMAIL']='private@example.test';os.environ['SCOUT_TEST_PASSWORD']='DisposablePass123'
  try:
   device=AndroidDevice('fake');device.size=lambda:(1080,1920)
   xml='<hierarchy><node class="android.widget.EditText" resource-id="app:id/email" text="private@example.test" bounds="[1,1][400,90]" clickable="true" editable="true"/></hierarchy>'
   screen=device._parse(ET.fromstring(xml),xml)
   import tempfile
   with tempfile.TemporaryDirectory() as directory:
    agent=Agent(RunConfig('app','fake',{'title':'test'},Path(directory)))
    public=json.dumps(agent.public_screen(screen))
    self.assertNotIn('private@example.test',public)
    self.assertIsNone(agent.screenshot(screen,0))
  finally:
   if old_email is None:os.environ.pop('SCOUT_TEST_EMAIL',None)
   else:os.environ['SCOUT_TEST_EMAIL']=old_email
   if old_password is None:os.environ.pop('SCOUT_TEST_PASSWORD',None)
   else:os.environ['SCOUT_TEST_PASSWORD']=old_password

 def test_post_login_evidence_only_captures_a_screen_without_inputs_or_email(self):
  import tempfile
  device=AndroidDevice('fake');device.size=lambda:(1080,1920)
  with tempfile.TemporaryDirectory() as directory:
   agent=Agent(RunConfig('app','fake',{'title':'test'},Path(directory)))
   agent.credential_used=True
   agent.device.screenshot=lambda path:path.write_bytes(b'png')
   login_xml='<hierarchy><node class="android.widget.EditText" text="" bounds="[1,1][400,90]" clickable="true"/></hierarchy>'
   account_xml='<hierarchy><node class="android.widget.TextView" text="someone@example.test" bounds="[1,1][400,90]"/></hierarchy>'
   home_xml='<hierarchy><node class="android.widget.TextView" text="LOUNGE" bounds="[1,1][400,90]"/></hierarchy>'
   for xml in (login_xml,account_xml):
    self.assertIsNone(agent.screenshot(device._parse(ET.fromstring(xml),xml),1))
   self.assertEqual(agent.screenshot(device._parse(ET.fromstring(home_xml),home_xml),2),'002.png')

 def test_jev_is_not_offered_wait_or_a_filled_text_field_on_stable_screen(self):
  device=AndroidDevice('fake');device.size=lambda:(1080,1920)
  xml='<hierarchy><node class="android.widget.EditText" text="filled" bounds="[1,1][400,90]" clickable="true"/><node class="android.widget.Button" text="Continue" bounds="[1,100][400,180]" clickable="true"/></hierarchy>'
  screen=device._parse(ET.fromstring(xml),xml)
  captured=[]
  def fake_post(_url,_key,body):
   captured.append(body)
   keys=list(body['questions']['operation']['criteria'])
   return {'answers':{'operation':{'choice':'DONE','confidence':1,'probabilities':{key:int(key=='DONE') for key in keys}}},'model':'test'}
  with patch.dict(os.environ,{'TYPESAFE_API_KEY':'test'}),patch('scout_mobile.model.post_json',side_effect=fake_post):
   choice=choose(screen.elements,screen.text,'Verify this screen',[])
  self.assertEqual(choice['operation'],'DONE')
  self.assertNotIn('WAIT',captured[0]['questions']['operation']['criteria'])
  self.assertNotIn('TYPE_TEXT',captured[0]['questions']['operation']['criteria'])
  self.assertNotIn('BLOCKED',captured[0]['questions']['operation']['criteria'])

 def test_companion_tutorial_forces_a_swipe_before_any_feed_tap(self):
  device=AndroidDevice('fake');device.size=lambda:(1080,2340)
  xml='''<hierarchy><node text="Swipe up to select your companion" class="android.widget.TextView" bounds="[1,100][500,200]"/><node text="Genre preferences" class="android.widget.Button" clickable="true" bounds="[10,1800][400,1880]"/></hierarchy>'''
  screen=device._parse(ET.fromstring(xml),xml)
  captured=[]
  def fake_post(_url,_key,body):
   captured.append(body)
   keys=list(body['questions']['operation']['criteria'])
   return {'answers':{'operation':{'choice':'SWIPE_UP','confidence':1,'probabilities':{key:int(key=='SWIPE_UP') for key in keys}}},'model':'test'}
  with patch.dict(os.environ,{'TYPESAFE_API_KEY':'test'}),patch('scout_mobile.model.post_json',side_effect=fake_post):
   choice=choose(screen.elements,screen.text,'Open Profile',[])
  self.assertEqual(choice['operation'],'SWIPE_UP')
  self.assertEqual(set(captured[0]['questions']['operation']['criteria']),{'SWIPE_UP'})
  self.assertIn('relevant content area',captured[0]['questions']['operation']['criteria']['SWIPE_UP'])
  self.assertNotIn('tap_target',captured[0]['questions'])

 def test_persistent_companion_tutorial_stops_after_one_swipe(self):
  device=AndroidDevice('fake');device.size=lambda:(1080,2340)
  xml='''<hierarchy><node text="Swipe up to select your companion" class="android.widget.TextView" bounds="[1,100][500,200]"/><node text="Genre preferences" class="android.widget.Button" clickable="true" bounds="[10,1800][400,1880]"/></hierarchy>'''
  screen=device._parse(ET.fromstring(xml),xml)
  fake=Mock();fake.observe.return_value=screen;fake.wait_for_content.return_value=screen;fake.foreground.return_value='app';fake.installed.return_value=True
  fake.command.return_value=SimpleNamespace(stdout=b'versionName=1.0\n')
  fake.screenshot.side_effect=lambda path:Path(path).write_bytes(b'png')
  fake.wait_for_change.return_value=screen
  fake.swipe_scrollable_next_item.return_value={'start':[270,1548],'end':[270,172],'duration_ms':300}
  answer={'operation':'SWIPE_UP','target':None,'confidence':1,'model':'test','latency_ms':1,'jev':{}}
  with tempfile.TemporaryDirectory() as directory,patch('scout_mobile.agent.AndroidDevice',return_value=fake),patch('scout_mobile.agent.choose',return_value=answer):
   result=Agent(RunConfig('app','fake',{'goal':'Open Profile'},Path(directory))).run()
  self.assertEqual(result['status'],'Inconclusive')
  self.assertIn('did not advance the screen',result['notes'])
  fake.swipe_scrollable_next_item.assert_called_once_with(1080,2340,screen)
  fake.tap.assert_not_called()

 def test_jev_can_wait_once_after_submit_leaves_transient_empty_tree(self):
  captured=[]
  def fake_post(_url,_key,body):
   captured.append(body)
   keys=list(body['questions']['operation']['criteria'])
   return {'answers':{'operation':{'choice':'WAIT','confidence':1,'probabilities':{key:int(key=='WAIT') for key in keys}}},'model':'test'}
  history=[{'step':4,'operation':'TAP','page_changed':True}]
  with patch.dict(os.environ,{'TYPESAFE_API_KEY':'test'}),patch('scout_mobile.model.post_json',side_effect=fake_post):
   choice=choose([], '', 'Wait for the login response after Next', history)
  self.assertEqual(choice['operation'],'WAIT')
  self.assertIn('WAIT',captured[0]['questions']['operation']['criteria'])

 def test_consent_action_is_blocked_before_device_tap(self):
  xml='''<hierarchy><node class="android.view.View" bounds="[0,0][1080,1920]"><node text="User Agreement and Consent" class="android.widget.TextView" bounds="[1,1][500,80]"/><node text="By checking I Agree, you agree to the Privacy Policy and Terms of Use and consent to personal data processing." class="android.widget.TextView" bounds="[1,90][900,300]"/><node text="I Agree" class="android.widget.CheckBox" checkable="true" checked="false" clickable="true" bounds="[100,400][500,500]"/></node></hierarchy>'''
  device=AndroidDevice('fake');device.size=lambda:(1080,1920)
  screen=device._parse(ET.fromstring(xml),xml)
  fake=Mock();fake.observe.return_value=screen;fake.wait_for_content.return_value=screen;fake.foreground.return_value='app';fake.installed.return_value=True
  fake.command.return_value=SimpleNamespace(stdout=b'versionName=1.0\n')
  fake.screenshot.side_effect=lambda path:Path(path).write_bytes(b'png')
  answer={'operation':'TAP','target':'1','confidence':.99,'model':'test','latency_ms':1,'jev':{}}
  with tempfile.TemporaryDirectory() as directory,patch('scout_mobile.agent.AndroidDevice',return_value=fake),patch('scout_mobile.agent.choose',return_value=answer):
   result=Agent(RunConfig('app','fake',{'goal':'Continue onboarding','steps':'Tap I Agree','expected':'Home'},Path(directory))).run()
  self.assertEqual(result['status'],'Inconclusive')
  self.assertIn('Explicit user confirmation',result['notes'])
  fake.tap.assert_not_called()
  self.assertEqual(result['steps'][-1]['blocked_by_safety'],'explicit user confirmation required for a legal or consent action')
  self.assertTrue(Agent.consent_confirmation_required('Start','User Agreement and Consent: accept the Terms of Use.'))

 def test_explicit_consent_authorization_is_scoped_to_the_run(self):
  consent_xml='''<hierarchy><node class="android.view.View" bounds="[0,0][1080,1920]"><node text="User Agreement and Consent" class="android.widget.TextView" bounds="[1,1][500,80]"/><node text="Terms of Use and Privacy Policy consent" class="android.widget.TextView" bounds="[1,90][900,300]"/><node text="I Agree" class="android.widget.CheckBox" checkable="true" checked="true" clickable="true" bounds="[100,400][500,500]"/></node></hierarchy>'''
  next_xml='<hierarchy><node text="Sign in" class="android.widget.TextView" bounds="[1,1][400,90]"/></hierarchy>'
  device=AndroidDevice('fake');device.size=lambda:(1080,1920)
  consent=device._parse(ET.fromstring(consent_xml),consent_xml)
  next_screen=device._parse(ET.fromstring(next_xml),next_xml)
  fake=Mock();fake.observe.side_effect=[consent,consent,next_screen];fake.wait_for_content.side_effect=lambda *_:fake.observe();fake.wait_for_change.return_value=next_screen
  fake.foreground.return_value='app';fake.installed.return_value=True
  fake.command.return_value=SimpleNamespace(stdout=b'versionName=1.0\n')
  fake.screenshot.side_effect=lambda path:Path(path).write_bytes(b'png')
  tap={'operation':'TAP','target':'1','confidence':.99,'model':'test','latency_ms':1,'jev':{}}
  done={'operation':'DONE','target':None,'confidence':.99,'model':'test','latency_ms':1,'jev':{}}
  with tempfile.TemporaryDirectory() as directory,patch('scout_mobile.agent.AndroidDevice',return_value=fake),patch('scout_mobile.agent.choose',side_effect=[tap,done]):
   result=Agent(RunConfig('app','fake',{'goal':'Continue the authorized UAT flow','steps':'Tap Start','expected':'Sign in'},Path(directory),expected_text='Sign in',allow_consent=True)).run()
  self.assertEqual(result['status'],'Passed')
  fake.tap.assert_called_once()

 def test_same_tap_is_not_repeated_after_no_screen_change(self):
  xml='<hierarchy><node text="Welcome" class="android.widget.TextView" bounds="[1,1][400,90]"/><node text="Continue" class="android.widget.Button" clickable="true" bounds="[1,100][400,180]"/></hierarchy>'
  device=AndroidDevice('fake');device.size=lambda:(1080,1920)
  screen=device._parse(ET.fromstring(xml),xml)
  fake=Mock();fake.observe.return_value=screen;fake.wait_for_content.return_value=screen;fake.wait_for_change.return_value=screen;fake.foreground.return_value='app';fake.installed.return_value=True
  fake.command.return_value=SimpleNamespace(stdout=b'versionName=1.0\n')
  fake.screenshot.side_effect=lambda path:Path(path).write_bytes(b'png')
  answer={'operation':'TAP','target':'1','confidence':.99,'model':'test','latency_ms':1,'jev':{}}
  with tempfile.TemporaryDirectory() as directory,patch('scout_mobile.agent.AndroidDevice',return_value=fake),patch('scout_mobile.agent.choose',side_effect=[answer,answer]):
   result=Agent(RunConfig('app','fake',{'goal':'Continue onboarding','steps':'Tap Continue','expected':'Sign in'},Path(directory),max_steps=4)).run()
  self.assertEqual(result['status'],'Inconclusive')
  self.assertIn('repeating TAP',result['notes'])
  self.assertEqual(fake.tap.call_count,1)

 def test_checkable_state_is_included_in_screen_fingerprint(self):
  def parse(checked):
   xml=f'<hierarchy><node text="I Agree" class="android.widget.CheckBox" checkable="true" checked="{str(checked).lower()}" clickable="true" bounds="[1,1][400,90]"/></hierarchy>'
   device=AndroidDevice('fake');device.size=lambda:(1080,1920)
   return device._parse(ET.fromstring(xml),xml)
  unchecked,checked=parse(False),parse(True)
  self.assertNotEqual(unchecked.fingerprint,checked.fingerprint)
  self.assertNotEqual(unchecked.elements[0].signature,checked.elements[0].signature)
  self.assertTrue(checked.elements[0].public()['checked'])

 def test_unlabeled_clickable_container_uses_visible_text_inside_its_bounds(self):
  xml='''<hierarchy><node class="android.view.View" clickable="true" bounds="[40,800][1040,1000]"/><node text="Your Birthday" class="android.widget.TextView" bounds="[100,850][500,930]"/></hierarchy>'''
  device=AndroidDevice('fake');device.size=lambda:(1080,1920)
  screen=device._parse(ET.fromstring(xml),xml)
  self.assertEqual(len(screen.elements),1)
  self.assertEqual(screen.elements[0].label,'Your Birthday')

 def test_editable_fields_offer_type_text_and_track_focus(self):
  def parse(focused):
   xml=f'<hierarchy><node text="Enter your email" class="android.widget.EditText" editable="true" focused="{str(focused).lower()}" bounds="[1,1][400,90]"/></hierarchy>'
   device=AndroidDevice('fake');device.size=lambda:(1080,1920)
   return device._parse(ET.fromstring(xml),xml)
  empty,focused=parse(False),parse(True)
  self.assertEqual(empty.elements[0].operations,('TYPE_TEXT',))
  self.assertNotEqual(empty.fingerprint,focused.fingerprint)
  self.assertTrue(focused.elements[0].public()['focused'])

 def test_mcp_run_yields_for_non_sensitive_text_and_resumes_without_recording_the_value(self):
  from scout_mobile.device import Element,Screen
  before=Screen('<hierarchy/>',[Element('1','textbox','Search','app:id/search','EditText','',(0,0,300,80),('TYPE_TEXT',),True)],'Search','before',1080,1920)
  focused=Screen('<hierarchy/>',[Element('1','textbox','Search','app:id/search','EditText','',(0,0,300,80),('TYPE_TEXT',),True,False,True)],'Search','focused',1080,1920)
  after=Screen('<hierarchy/>',[],'Results loaded','results',1080,1920)
  fake=Mock();fake.wait_for_content.return_value=before;fake.observe.side_effect=[before,focused,focused,after];fake.wait_for_change.return_value=after;fake.foreground.return_value='app';fake.installed.return_value=True
  fake.command.return_value=SimpleNamespace(stdout=b'versionName=1.0\n')
  typed=[];fake.type_text.side_effect=lambda _field,value:typed.append(value)
  decisions=[{'operation':'TYPE_TEXT','target':'1','confidence':.99,'model':'test','latency_ms':1,'jev':{}},{'operation':'DONE','target':None,'confidence':.99,'model':'test','latency_ms':1,'jev':{}}]
  with tempfile.TemporaryDirectory() as directory,patch('scout_mobile.agent.AndroidDevice',return_value=fake),patch('scout_mobile.agent.choose',side_effect=decisions):
   agent=Agent(RunConfig('app','fake',{'goal':'Search for Jisoo','steps':'Enter Jisoo in the search field'},Path(directory),expected_text='Results loaded',mcp_host_text=True))
   pending=agent.run()
   self.assertEqual(pending['status'],'awaiting_input')
   self.assertEqual(pending['text_request']['field']['label'],'Search')
   self.assertIn('Jisoo',pending['text_request']['steps'])
   result=agent.resume_text('Jisoo')
   trace=json.loads((Path(directory)/'trace.json').read_text())
  self.assertEqual(result['status'],'Passed')
  self.assertEqual(typed,['Jisoo'])
  self.assertEqual(trace[1]['text_source'],'MCP host LLM')
  self.assertNotIn('text',trace[1])

 def test_mcp_host_text_is_never_requested_for_one_time_codes(self):
  from scout_mobile.device import Element,Screen
  screen=Screen('<hierarchy/>',[Element('1','textbox','Verification code','app:id/otp','EditText','',(0,0,300,80),('TYPE_TEXT',),True,False,True)],'Verification code','otp',1080,1920)
  fake=Mock();fake.wait_for_content.return_value=screen;fake.observe.return_value=screen;fake.foreground.return_value='app';fake.installed.return_value=True
  fake.command.return_value=SimpleNamespace(stdout=b'versionName=1.0\n')
  decision={'operation':'TYPE_TEXT','target':'1','confidence':.99,'model':'test','latency_ms':1,'jev':{}}
  with tempfile.TemporaryDirectory() as directory,patch('scout_mobile.agent.AndroidDevice',return_value=fake),patch('scout_mobile.agent.choose',return_value=decision):
   result=Agent(RunConfig('app','fake',{'goal':'Complete the verification','steps':'Enter code'},Path(directory),mcp_host_text=True)).run()
  self.assertEqual(result['status'],'Execution error')
  self.assertIn('verification code',result['notes'])

 def test_focused_sensitive_field_does_not_capture_keyboard_suggestions(self):
  device=AndroidDevice('fake');device.size=lambda:(1080,1920)
  xml='<hierarchy><node text="Enter your email" class="android.widget.EditText" editable="true" focused="true" bounds="[1,1][400,90]"/></hierarchy>'
  screen=device._parse(ET.fromstring(xml),xml)
  with tempfile.TemporaryDirectory() as directory:
   agent=Agent(RunConfig('app','fake',{'title':'test'},Path(directory)))
   agent.device.screenshot=lambda path:path.write_bytes(b'png')
   self.assertIsNone(agent.screenshot(screen,1))

 def test_empty_transition_after_credential_entry_is_not_screenshot(self):
  device=AndroidDevice('fake');device.size=lambda:(1080,1920)
  xml='<hierarchy/>'
  screen=device._parse(ET.fromstring(xml),xml)
  with tempfile.TemporaryDirectory() as directory:
   agent=Agent(RunConfig('app','fake',{'title':'test'},Path(directory)))
   agent.credential_used=True
   agent.device.screenshot=lambda path:path.write_bytes(b'png')
   self.assertIsNone(agent.screenshot(screen,1))

 def test_focused_text_field_matches_after_keyboard_resizes_its_bounds(self):
  before_xml='''<hierarchy><node class="android.widget.EditText" password="true" bounds="[1,100][500,200]"/><node class="android.widget.EditText" password="true" bounds="[1,300][500,400]"/></hierarchy>'''
  after_xml='''<hierarchy><node class="android.widget.EditText" password="true" focused="false" bounds="[1,100][500,200]"/><node class="android.widget.EditText" password="true" focused="true" bounds="[1,220][500,320]"/></hierarchy>'''
  device=AndroidDevice('fake');device.size=lambda:(1080,1920)
  before=device._parse(ET.fromstring(before_xml),before_xml)
  after=device._parse(ET.fromstring(after_xml),after_xml)
  self.assertIs(Agent.focused_text_field(after,before.elements[1]),after.elements[1])

 def test_generic_accessibility_child_does_not_hide_nearby_field_heading(self):
  xml='''<hierarchy><node text="Your Birthday" class="android.widget.TextView" bounds="[275,346][806,460]"/><node text="We use your birthday to personalize your experience. Your information is always kept private." class="android.widget.TextView" bounds="[209,511][872,682]"/><node class="android.view.View" clickable="true" bounds="[56,954][1024,1123]"><node content-desc="background" class="android.widget.ImageView" bounds="[0,0][1080,2205]"/></node></hierarchy>'''
  device=AndroidDevice('fake');device.size=lambda:(1080,2340)
  screen=device._parse(ET.fromstring(xml),xml)
  self.assertEqual(len(screen.elements),1)
  self.assertEqual(screen.elements[0].label,'Your Birthday')

 def test_no_project_specific_profile_coordinate_is_injected(self):
  xml='''<hierarchy><node text="Swipe up to select your companion" class="android.widget.TextView" bounds="[1,100][500,200]"/><node text="Genre preferences" class="android.widget.TextView" bounds="[10,1800][400,1880]" clickable="true"/></hierarchy>'''
  device=AndroidDevice('fake');device.size=lambda:(1080,2340)
  screen=device._parse(ET.fromstring(xml),xml)
  self.assertFalse(any(e.label=='Profile' for e in screen.elements))

 def test_navigation_cycle_detector_recognizes_repeated_two_and_three_screen_loops(self):
  self.assertIsNone(Agent.screen_cycle(['edit','profile','edit','profile']))
  self.assertEqual(Agent.screen_cycle(['feed','profile','menu','profile','menu','profile','menu']),2)
  self.assertIsNone(Agent.screen_cycle(['feed','search','results','feed','search','results']))
  self.assertEqual(Agent.screen_cycle(['feed','search','results']*3),3)
  self.assertIsNone(Agent.screen_cycle(['feed','profile','menu','search']))

 def test_runner_stops_on_repeated_navigation_cycle_before_another_model_call(self):
  from scout_mobile.device import Element,Screen
  target=Element('1','button','More options','','Button','',(0,0,20,20),('TAP',),False)
  screens=[Screen('',[target],label,label,1080,1920) for label in ('feed','profile','menu')]
  fake=Mock();fake.wait_for_content.return_value=screens[0];fake.observe.return_value=screens[0]
  fake.wait_for_change.side_effect=[screens[1],screens[2],screens[1],screens[2],screens[1],screens[2]]
  fake.foreground.return_value='app';fake.installed.return_value=True
  fake.command.return_value=SimpleNamespace(stdout=b'versionName=1.0\n')
  fake.screenshot.side_effect=lambda path:Path(path).write_bytes(b'png')
  decision={'operation':'TAP','target':'1','confidence':.9,'model':'test','latency_ms':1,'jev':{}}
  with tempfile.TemporaryDirectory() as directory,patch('scout_mobile.agent.AndroidDevice',return_value=fake),patch('scout_mobile.agent.choose',return_value=decision) as chooser:
   result=Agent(RunConfig('app','fake',{'goal':'Open More options'},Path(directory),max_steps=20)).run()
  self.assertEqual(result['status'],'Inconclusive')
  self.assertIn('2-screen navigation cycle',result['notes'])
  self.assertEqual(chooser.call_count,5)

 def test_runner_allows_a_requested_return_to_an_earlier_screen(self):
  from scout_mobile.device import Element,Screen
  back=Element('1','button','Back','','Button','',(0,0,20,20),('TAP',),False)
  edit=Element('1','button','Edit','','Button','',(0,0,20,20),('TAP',),False)
  before=Screen('',[back],'Username · Back','edit',1080,1920)
  profile=Screen('',[edit],'Profile · Username · Edit','profile',1080,1920)
  returned=Screen('',[back],'Prompt · Name · Username','edit',1080,1920)
  fake=Mock();fake.wait_for_content.return_value=before;fake.observe.return_value=returned
  fake.wait_for_change.side_effect=[profile,returned]
  fake.foreground.return_value='app';fake.installed.return_value=True
  fake.command.return_value=SimpleNamespace(stdout=b'versionName=1.0\n')
  fake.screenshot.side_effect=lambda path:Path(path).write_bytes(b'png')
  decisions=[
   {'operation':'BACK','target':None,'confidence':.9,'model':'test','latency_ms':1,'jev':{}},
   {'operation':'TAP','target':'1','confidence':.9,'model':'test','latency_ms':1,'jev':{}},
   {'operation':'DONE','target':None,'confidence':.9,'model':'test','latency_ms':1,'jev':{}},
  ]
  with tempfile.TemporaryDirectory() as directory,patch('scout_mobile.agent.AndroidDevice',return_value=fake),patch('scout_mobile.agent.choose',side_effect=decisions) as chooser:
   result=Agent(RunConfig('app','fake',{'goal':'Return to the edit prompt through Profile'},Path(directory),expected_text='Username')).run()
  self.assertEqual(result['status'],'Passed')
  self.assertEqual(chooser.call_count,3)

 def test_read_only_visible_assertion_skips_model_round_trip(self):
  from scout_mobile.device import Screen
  before=Screen('',[],'Username visible on profile','profile',1080,1920)
  fake=Mock();fake.wait_for_content.return_value=before;fake.foreground.return_value='app';fake.installed.return_value=True
  fake.command.return_value=SimpleNamespace(stdout=b'versionName=1.0\n')
  fake.screenshot.side_effect=lambda path:Path(path).write_bytes(b'png')
  with tempfile.TemporaryDirectory() as directory,patch('scout_mobile.agent.AndroidDevice',return_value=fake),patch('scout_mobile.agent.choose') as chooser:
   result=Agent(RunConfig('app','fake',{'goal':'Verify the profile username is visible','steps':''},Path(directory),expected_text='Username visible')).run()
  self.assertEqual(result['status'],'Passed')
  chooser.assert_not_called()
  self.assertTrue(any(entry.get('timings_ms',{}).get('verification_only') for entry in result['steps']))
  json.dumps(result)

 def test_mcp_allows_step_free_read_only_verification_only_with_exact_assertion(self):
  from scout_mobile.validation import validate_prompt_steps
  validate_prompt_steps('Verify the username is visible','', 'Username')
  with self.assertRaisesRegex(ValueError,'read-only verification goal'):
   validate_prompt_steps('Search for a username','', 'Username')
  with self.assertRaisesRegex(ValueError,'read-only verification goal'):
   validate_prompt_steps('Verify the username is visible','', '')

 def test_screen_size_is_cached_briefly_and_refreshed_after_ttl(self):
  from subprocess import CompletedProcess
  device=AndroidDevice('fake')
  device.command=Mock(return_value=CompletedProcess([],0,b'Physical size: 1080x2340\n',b''))
  with patch('scout_mobile.device.time.monotonic',side_effect=[0.0,.5,3.0,3.0]):
   self.assertEqual(device.size(),(1080,2340))
   self.assertEqual(device.size(),(1080,2340))
   self.assertEqual(device.size(),(1080,2340))
  self.assertEqual(device.command.call_count,2)

if __name__=='__main__':unittest.main()
