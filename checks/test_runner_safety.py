"""Safety checks for Jev selection and credential handling, using a real observed app state."""
import json
import os
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch
from jev_mobile.agent import Agent,RunConfig,GUARD_TEXT
from jev_mobile.device import AndroidDevice
from jev_mobile.model import ModelError,validate_choice,choose

STARTUP_XML='''<hierarchy><node class="android.widget.FrameLayout" bounds="[0,0][1344,2992]" clickable="false"><node text="This application is not supported on rooted devices or emulators." class="android.widget.TextView" bounds="[264,1375][1080,1481]" clickable="false"/><node text="OK" class="android.widget.Button" bounds="[264,1553][1080,1703]" clickable="true"/></node></hierarchy>'''

class RunnerSafetyTests(unittest.TestCase):
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

 def test_actual_startup_alert_is_not_treated_as_authentication_failure(self):
  assert GUARD_TEXT in STARTUP_XML
  device=AndroidDevice('emulator-5554')
  device.size=lambda:(1344,2992)
  screen=device._parse(ET.fromstring(STARTUP_XML),STARTUP_XML)
  self.assertEqual([(e.label,e.center) for e in screen.elements],[('OK',(672,1628))])
  self.assertIn(GUARD_TEXT,screen.text)

 def test_model_choice_cannot_name_unobserved_target(self):
  answer={'choice':'2','confidence':.9,'probabilities':{'1':.1,'2':.9}}
  with self.assertRaises(ModelError):validate_choice(answer,{'1'})

 def test_credentials_are_redacted_from_model_view_and_output(self):
  old_email=os.environ.get('JEV_TEST_EMAIL');old_password=os.environ.get('JEV_TEST_PASSWORD')
  os.environ['JEV_TEST_EMAIL']='private@example.test';os.environ['JEV_TEST_PASSWORD']='DisposablePass123'
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
   if old_email is None:os.environ.pop('JEV_TEST_EMAIL',None)
   else:os.environ['JEV_TEST_EMAIL']=old_email
   if old_password is None:os.environ.pop('JEV_TEST_PASSWORD',None)
   else:os.environ['JEV_TEST_PASSWORD']=old_password

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
  with patch.dict(os.environ,{'TYPESAFE_API_KEY':'test'}),patch('jev_mobile.model.post_json',side_effect=fake_post):
   choice=choose(screen.elements,screen.text,'Verify this screen',[])
  self.assertEqual(choice['operation'],'DONE')
  self.assertNotIn('WAIT',captured[0]['questions']['operation']['criteria'])
  self.assertNotIn('TYPE_TEXT',captured[0]['questions']['operation']['criteria'])
  self.assertNotIn('BLOCKED',captured[0]['questions']['operation']['criteria'])

if __name__=='__main__':unittest.main()
