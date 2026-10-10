"""Adapter contract checks; no connected device or model is used."""
import tempfile
import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scout_mobile.appium_device import AppiumAndroidDevice
from scout_mobile.device import AndroidDevice
from scout_mobile.device import DeviceError, Element, Screen, tap_point
from scout_mobile.agent import Agent, RunConfig

XML = '<hierarchy><android.widget.Button text="Continue" class="android.widget.Button" resource-id="app:id/continue" bounds="[10,20][110,70]" enabled="true" clickable="true"/></hierarchy>'


class AppiumAdapterTests(unittest.TestCase):
    def test_appium_is_default_and_adb_is_an_explicit_override(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'SCOUT_ANDROID_DRIVER': ''}):
            default = Agent(RunConfig('app', 'fake', {}, Path(directory)))
            self.assertIsInstance(default.device, AppiumAndroidDevice)
            self.assertEqual(default.device.idle_timeout_ms, 1000)
            fallback = Agent(RunConfig('app', 'fake', {}, Path(directory), backend='adb'))
            self.assertEqual(fallback.backend, 'adb')

    def test_ready_appium_server_is_reused_without_starting_process(self):
        from scout_mobile.appium_runtime import ensure_appium
        with patch('scout_mobile.appium_runtime._ready', return_value=True), patch('scout_mobile.appium_runtime.subprocess.Popen') as start:
            ensure_appium('http://127.0.0.1:4723')
            start.assert_not_called()

    def test_unavailable_custom_endpoint_is_not_replaced(self):
        from scout_mobile.appium_runtime import ensure_appium
        with patch('scout_mobile.appium_runtime._ready', return_value=False), patch('scout_mobile.appium_runtime.subprocess.Popen') as start:
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

    @staticmethod
    def _element(label, bounds, rid=''):
        return Element('1', 'button', label, rid, 'android.view.View', '', bounds, ('TAP',), False)

    def test_tap_point_avoids_a_floating_bar_drawn_over_the_target(self):
        # Synthetic layout modelled on the Twomi hub: a carousel card whose lower part sits under the bottom bar.
        card = self._element('Open Sayaka', (40, 1800, 520, 2300), 'buddy_card_VA_F04')
        create = self._element('Create', (440, 2040, 640, 2200))
        screen = Screen('', [card, create], 'hub', 'hub', 1080, 2340)
        x, y = tap_point(card, screen)
        self.assertTrue(40 <= x < 520 and 1800 <= y < 2300)
        self.assertFalse(440 <= x < 640 and 2040 <= y < 2200)

    def test_tap_point_avoids_the_whole_bar_a_covering_control_sits_in(self):
        # Geometry from the Twomi hub on a Samsung S22: tab items 2007–2143 on a pill that also takes touches.
        card = self._element('Open Sayaka', (302, 1860, 779, 2340), 'buddy_card_VA_F04')
        tabs = [self._element(name, bounds) for name, bounds in (('Home', (62, 2007, 254, 2143)), ('Create', (445, 2007, 636, 2143)),
                                                                   ('Notification', (636, 2007, 827, 2143)), ('Account', (827, 2007, 1018, 2143)))]
        x, y = tap_point(card, Screen('', [card, *tabs], 'hub', 'hub', 1080, 2340), [(0, 2214, 1080, 2340)])
        self.assertTrue(1860 <= y < 2007 - 16, (x, y))

    def test_tap_point_avoids_the_system_navigation_bar(self):
        card = self._element('Explore Aya', (40, 2100, 1040, 2400))  # centre y=2250 is under the bar
        self.assertGreaterEqual(card.center[1], 2214)
        x, y = tap_point(card, Screen('', [card], 'hub', 'hub', 1080, 2340), [(0, 2214, 1080, 2340)])
        self.assertTrue(2100 <= y < 2214)

    def test_tap_point_keeps_the_centre_when_nothing_covers_it(self):
        button = self._element('Continue', (10, 20, 110, 70))
        later = self._element('Elsewhere', (500, 500, 600, 600))
        self.assertEqual(tap_point(button, Screen('', [button, later], 's', 's', 1080, 2340)), button.center)

    def test_tap_point_ignores_a_later_node_that_contains_the_target(self):
        button = self._element('Call Aya', (400, 2000, 560, 2160))
        scrim = self._element('Close', (0, 0, 1080, 2340))
        self.assertEqual(tap_point(button, Screen('', [button, scrim], 's', 's', 1080, 2340)), button.center)

    def test_fully_covered_target_is_not_tapped(self):
        card = self._element('Open Eri', (40, 2100, 300, 2200))
        home = self._element('Home', (0, 2080, 180, 2240))
        create = self._element('Create', (170, 2080, 400, 2240))
        with self.assertRaisesRegex(DeviceError, 'covered'):
            tap_point(card, Screen('', [card, home, create], 's', 's', 1080, 2340))

    def test_appium_taps_the_uncovered_point_instead_of_clicking_a_covered_centre(self):
        device, driver = self.device()
        driver.execute_script.return_value = {'navigationBar': {'visible': True, 'x': 0, 'y': 2214, 'width': 1080, 'height': 126}}
        card = self._element('Explore Aya', (40, 2100, 1040, 2400))  # centre y=2250 is under the bar
        device.tap(card, Screen('', [card], 'hub', 'hub', 1080, 2340))
        driver.find_elements.assert_not_called()
        actions = driver.execute.call_args[0][1]['actions'][0]['actions']
        self.assertLess(actions[0]['y'], 2214)
        self.assertEqual([action['type'] for action in actions], ['pointerMove', 'pointerDown', 'pause', 'pointerUp'])

    def test_appium_still_clicks_an_uncovered_element(self):
        device, driver = self.device()
        driver.execute_script.return_value = {}
        target = Mock(); target.rect = {'x': 10, 'y': 20, 'width': 100, 'height': 50}
        driver.find_elements.return_value = [target]
        element = device.observe().elements[0]
        device.tap(element, device.observe())
        target.click.assert_called_once()

    def test_adb_background_presses_home_waits_and_relaunches(self):
        device = AndroidDevice('fake')
        with patch.object(device, 'command') as command, patch.object(device, 'launch') as launch, patch('scout_mobile.device.time.sleep') as sleep:
            device.background_app('app', 2500)
        command.assert_called_once_with('shell', 'input', 'keyevent', '3')
        sleep.assert_called_once_with(2.5)
        launch.assert_called_once_with('app')

    def test_appium_background_uses_the_driver_and_returns_to_the_app(self):
        device, driver = self.device()
        driver.current_package = 'app'
        device.background_app('app', 4000)
        driver.background_app.assert_called_once_with(4.0)

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
            with patch('scout_mobile.appium_device.AppiumAndroidDevice') as constructor:
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
