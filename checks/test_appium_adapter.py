"""Adapter contract checks; no connected device or model is used."""
import tempfile
import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from jev_mobile.appium_device import AppiumAndroidDevice
from jev_mobile.device import DeviceError
from jev_mobile.agent import Agent, RunConfig

XML = '<hierarchy><android.widget.Button text="Continue" class="android.widget.Button" resource-id="app:id/continue" bounds="[10,20][110,70]" enabled="true" clickable="true"/></hierarchy>'


class AppiumAdapterTests(unittest.TestCase):
    def test_appium_is_default_and_adb_is_an_explicit_override(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'JEV_ANDROID_DRIVER': ''}):
            default = Agent(RunConfig('app', 'fake', {}, Path(directory)))
            self.assertIsInstance(default.device, AppiumAndroidDevice)
            self.assertEqual(default.device.idle_timeout_ms, 1000)
            fallback = Agent(RunConfig('app', 'fake', {}, Path(directory), backend='adb'))
            self.assertEqual(fallback.backend, 'adb')

    def test_ready_appium_server_is_reused_without_starting_process(self):
        from jev_mobile.appium_runtime import ensure_appium
        with patch('jev_mobile.appium_runtime._ready', return_value=True), patch('jev_mobile.appium_runtime.subprocess.Popen') as start:
            ensure_appium('http://127.0.0.1:4723')
            start.assert_not_called()

    def test_unavailable_custom_endpoint_is_not_replaced(self):
        from jev_mobile.appium_runtime import ensure_appium
        with patch('jev_mobile.appium_runtime._ready', return_value=False), patch('jev_mobile.appium_runtime.subprocess.Popen') as start:
            with self.assertRaisesRegex(DeviceError, 'configured Appium server is unavailable'):
                ensure_appium('http://127.0.0.1:4999')
            start.assert_not_called()

    def device(self):
        device = AppiumAndroidDevice('fake')
        driver = Mock()
        driver.page_source = XML
        driver.get_window_size.return_value = {'width': 1080, 'height': 2340}
        device._driver = driver
        return device, driver

    def test_normalized_source_keeps_shared_observation_contract(self):
        device, driver = self.device()
        screen = device.observe()
        self.assertEqual(screen.elements[0].label, 'Continue')
        self.assertEqual(screen.elements[0].bounds, (10, 20, 110, 70))
        self.assertEqual(screen.elements[0].operations, ('TAP',))
        self.assertIn('<node ', screen.xml)
        self.assertIn('page_source_ms', device.last_observation_timings)

    def test_duplicate_target_is_rejected_without_tapping(self):
        device, driver = self.device()
        targets = [Mock(), Mock()]
        for target in targets:
            target.rect = {'x': 10, 'y': 20, 'width': 100, 'height': 50}
        driver.find_elements.return_value = targets
        with self.assertRaises(DeviceError):
            device.tap(device.observe().elements[0])
        for target in targets:
            target.click.assert_not_called()

    def test_command_errors_do_not_expose_provider_payloads(self):
        device, driver = self.device()
        driver.back.side_effect = RuntimeError('secret-password and private page source')
        with self.assertRaises(DeviceError) as error:
            device.back()
        self.assertNotIn('secret-password', str(error.exception))
        self.assertNotIn('private page source', str(error.exception))

    def test_session_is_closed_only_once(self):
        device, driver = self.device()
        device.close()
        device.close()
        driver.quit.assert_called_once()
        self.assertIsNone(device._driver)

    def test_only_local_servers_are_accepted(self):
        for url in ['https://example.com', 'http://user:password@localhost:4723', 'http://localhost:4723?secret=value']:
            with self.assertRaises(ValueError):
                AppiumAndroidDevice('fake', server_url=url)

    def test_runner_closes_session_after_a_blocked_run(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('jev_mobile.appium_device.AppiumAndroidDevice') as constructor:
                constructor.return_value.installed.return_value = False
                agent = Agent(RunConfig('app', 'fake', {}, Path(directory), backend='appium'))
                agent.capture_device_info = lambda: {'automation_backend': 'appium'}
                agent.capture_app_logs = lambda: ''
                result = agent.run()
                self.assertEqual(result['status'], 'Blocked')
                constructor.return_value.launch.assert_not_called()
                constructor.return_value.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
