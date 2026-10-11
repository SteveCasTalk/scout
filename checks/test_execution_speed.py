"""Settle-wait and deferred-screenshot behaviour. Synthetic devices only; not on-device timing."""
import os
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from scout_mobile.agent import Agent, RunConfig
from scout_mobile.device import AndroidDevice, DeviceError, Element, Screen

BUTTON=Element('1','button','Next','','Button','',(10,10,200,60),('TAP',),False)
FIRST=Screen('',[BUTTON],'Welcome · Next','first',1080,2340)
SECOND=Screen('',[],'All set','second',1080,2340)
TAP={'operation':'TAP','target':'1','confidence':1,'model':'test','latency_ms':1,'jev':{}}
DONE={'operation':'DONE','target':None,'confidence':1,'model':'test','latency_ms':1,'jev':{}}


class SettleWaitTests(unittest.TestCase):
    def test_no_extra_observation_after_the_deadline(self):
        device=AndroidDevice('fake')
        clock=[0.0]
        def observe(retries=2):
            clock[0]+=2.4  # one slow ADB dump
            device.last_observation_timings={'total_ms':2400}
            return FIRST
        device.observe=observe
        with patch('scout_mobile.device.time.monotonic',side_effect=lambda:clock[0]),patch('scout_mobile.device.time.sleep'):
            screen=device.wait_for_change(FIRST,4)
        self.assertIs(screen,FIRST)
        # Polls at 0 and 2.4 s; the poll ending at 4.8 s is the answer, with no read after it.
        self.assertEqual(device.last_wait_timings['polls'],2)

    def test_returns_as_soon_as_the_screen_changes(self):
        device=AndroidDevice('fake')
        device.observe=Mock(side_effect=[FIRST,SECOND]);device.last_observation_timings={'total_ms':5}
        with patch('scout_mobile.device.time.sleep'):
            self.assertIs(device.wait_for_change(FIRST,4),SECOND)
        self.assertEqual(device.observe.call_count,2)

    def test_swipes_use_a_shorter_unchanged_budget_than_taps(self):
        from scout_mobile.engine.nodes.act import SETTLE_SECONDS
        self.assertLess(SETTLE_SECONDS['SWIPE_UP'],SETTLE_SECONDS['TAP'])
        self.assertEqual(SETTLE_SECONDS['TAP'],4)


class DeferredScreenshotTests(unittest.TestCase):
    def setUp(self):
        backend=patch.dict(os.environ,{'SCOUT_ANDROID_DRIVER':'adb'})
        backend.start();self.addCleanup(backend.stop)

    def fake(self):
        fake=Mock();fake.installed.return_value=True;fake.wait_for_content.return_value=FIRST
        fake.foreground.return_value='example.app';fake.observe.side_effect=[FIRST,SECOND]
        fake.wait_for_change.return_value=SECOND
        fake.command.return_value=SimpleNamespace(stdout=b'')
        return fake

    def run_agent(self,fake,directory,decisions):
        with patch('scout_mobile.agent.AndroidDevice',return_value=fake),patch('scout_mobile.agent.choose',side_effect=decisions):
            return Agent(RunConfig('example.app','fake',{'goal':'Reach the end'},Path(directory),expected_text='All set')).run()

    def test_step_screenshot_overlaps_the_next_decision_and_finishes_before_the_next_action(self):
        fake=self.fake();events=[]
        second_decision=threading.Event()
        def screenshot(path):
            if Path(path).name=='001.png.part':
                self.assertTrue(second_decision.wait(2),'capture did not overlap the next decision')
                events.append('capture 001')
            Path(path).write_bytes(b'png')
        fake.screenshot.side_effect=screenshot
        fake.swipe.side_effect=lambda *_:events.append('swipe')
        swipe={'operation':'SWIPE_UP','target':None,'confidence':1,'model':'test','latency_ms':1,'jev':{}}
        plan=[dict(TAP),swipe,dict(DONE)]
        def decide(*_args,**_kwargs):
            events.append('decide')
            if events.count('decide')==2:second_decision.set()
            return plan[events.count('decide')-1]
        with tempfile.TemporaryDirectory() as directory:
            with patch('scout_mobile.agent.AndroidDevice',return_value=fake),patch('scout_mobile.agent.choose',side_effect=decide):
                result=Agent(RunConfig('example.app','fake',{'goal':'Reach the end'},Path(directory),expected_text='All set')).run()
            names=sorted(path.name for path in Path(directory).iterdir())
        self.assertEqual(result['status'],'Passed')
        step=next(entry for entry in result['steps'] if entry.get('operation')=='TAP')
        self.assertEqual(step['screenshot'],'001.png')
        self.assertTrue(step['timings_ms']['screenshot_deferred'])
        self.assertIn('001.png',names)
        self.assertFalse([name for name in names if name.endswith('.part')])
        # decide #2 runs while 001 is capturing; the swipe waits for the capture.
        self.assertEqual(events[:4],['decide','decide','capture 001','swipe'])

    def test_failed_background_capture_is_reported(self):
        fake=self.fake()
        def screenshot(path):
            if Path(path).name.startswith('001'):raise DeviceError('screencap failed')
            Path(path).write_bytes(b'png')
        fake.screenshot.side_effect=screenshot
        with tempfile.TemporaryDirectory() as directory:
            result=self.run_agent(fake,directory,[dict(TAP),dict(DONE)])
        self.assertEqual(result['status'],'Passed')
        self.assertIn('screenshot capture failed for 001.png',result['notes'])

    def test_failed_capture_stops_before_the_next_action(self):
        fake=self.fake();fake.observe.side_effect=[FIRST,SECOND,SECOND]
        def screenshot(path):
            if Path(path).name.startswith('001'):raise DeviceError('screencap failed')
            Path(path).write_bytes(b'png')
        fake.screenshot.side_effect=screenshot
        second_tap={'operation':'SWIPE_UP','target':None,'confidence':1,'model':'test','latency_ms':1,'jev':{}}
        with tempfile.TemporaryDirectory() as directory:
            result=self.run_agent(fake,directory,[dict(TAP),second_tap])
        self.assertEqual(result['status'],'Execution error')
        self.assertIn('Screenshot 001.png could not be captured',result['notes'])
        fake.swipe.assert_not_called()

    def test_capture_stays_synchronous_after_credentials_are_used(self):
        with tempfile.TemporaryDirectory() as directory:
            fake=self.fake();fake.screenshot.side_effect=lambda path:Path(path).write_bytes(b'png')
            with patch('scout_mobile.agent.AndroidDevice',return_value=fake):
                agent=Agent(RunConfig('example.app','fake',{'goal':'x'},Path(directory)))
            agent.credential_used=True
            self.assertEqual(agent.screenshot_deferred(SECOND,4),'004.png')
            self.assertEqual(agent._pending_screenshots,[])
            self.assertTrue((Path(directory)/'004.png').is_file())


if __name__=='__main__':unittest.main()
