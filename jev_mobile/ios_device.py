"""iOS observation and actions through Appium/XCUITest on a local Mac."""
from __future__ import annotations

import base64
from contextlib import contextmanager, nullcontext
import hashlib
import json
import os
import re
import math
from pathlib import Path
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET

from .appium_device import AppiumAndroidDevice
from .device import AndroidDevice, DeviceError, Element, Screen


def apple_json(*args: str) -> dict:
    with tempfile.TemporaryDirectory(prefix='jev-apple-') as directory:
        path = Path(directory) / 'response.json'
        try:
            result = subprocess.run(['xcrun', 'devicectl', *args, '--timeout', '15', '--json-output', str(path)], capture_output=True, timeout=20)
            if result.returncode:raise DeviceError('Apple device discovery failed. Check Xcode, pairing and Developer Mode.')
            return json.loads(path.read_text())['result']
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
            raise DeviceError('Apple device discovery is unavailable. Select a full Xcode installation on macOS.') from None


def discover_ios() -> list[dict]:
    devices = []
    errors = []
    try:
        for item in apple_json('list', 'devices').get('devices', []):
            hardware = item.get('hardwareProperties', {})
            connection = item.get('connectionProperties', {})
            properties = item.get('deviceProperties', {})
            if hardware.get('platform') != 'iOS' or connection.get('tunnelState') != 'connected':continue
            if connection.get('pairingState') != 'paired':continue
            udid = hardware.get('udid')
            if udid:devices.append({'serial': udid, 'model': hardware.get('marketingName', 'iPhone'), 'ios_version': properties.get('osVersionNumber', ''), 'simulator': False})
    except DeviceError as exc:errors.append(str(exc))
    try:
        result = subprocess.run(['xcrun', 'simctl', 'list', 'devices', 'booted', '--json'], capture_output=True, text=True, check=True, timeout=15)
        for runtime, entries in json.loads(result.stdout).get('devices', {}).items():
            if '.iOS-' not in runtime:continue
            for item in entries:
                if item.get('isAvailable') and item.get('state') == 'Booted':
                    devices.append({'serial': item['udid'], 'model': item['name'], 'ios_version': runtime.split('.iOS-')[-1].replace('-', '.'), 'simulator': True})
    except (OSError, ValueError, subprocess.SubprocessError):errors.append('Simulator discovery is unavailable.')
    if len(errors) == 2:raise DeviceError(' '.join(errors))
    return devices


class AppiumIOSDevice(AppiumAndroidDevice):
    """Share transport and polling primitives, with no Android command fallback."""
    backend = 'appium'
    platform = 'iOS'
    _call = AppiumAndroidDevice._call
    size = AppiumAndroidDevice.size
    screenshot = AppiumAndroidDevice.screenshot
    launch = AppiumAndroidDevice.launch
    tap = AppiumAndroidDevice.tap
    swipe_coordinates = AppiumAndroidDevice.swipe_coordinates
    swipe = AndroidDevice.swipe
    wait_for_change = AndroidDevice.wait_for_change
    wait_for_content = AndroidDevice.wait_for_content

    def __init__(self, serial: str, bundle_id: str, server_url: str):
        AppiumAndroidDevice.__init__(self, serial, server_url=server_url, idle_timeout_ms=0)
        self.bundle_id = bundle_id
        self._recording = False
        self._close_requested = False
        self.recording_error = ''
        self._log_lines = []
        self._app_pid = None

    @property
    def driver(self):
        if self._driver is None:
            from appium import webdriver
            from appium.options.ios import XCUITestOptions
            from .appium_runtime import ensure_appium
            ensure_appium(self.server_url)
            caps = {'platformName': 'iOS', 'appium:automationName': 'XCUITest', 'appium:udid': self.serial,
                    'appium:bundleId': self.bundle_id, 'appium:noReset': True, 'appium:fullReset': False,
                    'appium:autoLaunch': False, 'appium:newCommandTimeout': 1800,
                    'appium:printPageSourceOnFindFailure': False, 'appium:showXcodeLog': False}
            for env, cap in [('JEV_IOS_TEAM_ID', 'xcodeOrgId'), ('JEV_IOS_SIGNING_ID', 'xcodeSigningId'), ('JEV_IOS_WDA_BUNDLE_ID', 'updatedWDABundleId')]:
                if os.getenv(env):caps['appium:' + cap] = os.environ[env]
            if os.getenv('JEV_IOS_USE_PREINSTALLED_WDA') == 'true':caps['appium:usePreinstalledWDA'] = True
            started = time.perf_counter()
            try:
                self._driver = webdriver.Remote(self.server_url, options=XCUITestOptions().load_capabilities(caps))
                self._driver.implicitly_wait(0)
            except Exception as exc:
                self.close()
                raise DeviceError(f'XCUITest session could not start ({type(exc).__name__}). Check the XCUITest driver, device trust, Developer Mode and WebDriverAgent signing.') from None
            self.session_start_ms = round((time.perf_counter() - started) * 1000)
        return self._driver

    def close(self):
        if self._recording:
            self._close_requested = True
        else:
            AppiumAndroidDevice.close(self)
            self._close_requested = False

    def command(self, *args, **kwargs):
        raise DeviceError('ADB commands are not supported on iOS.')

    def installed(self, package):
        return self._call(lambda driver: driver.is_app_installed(package))

    def terminate(self, package):
        self._call(lambda driver: driver.terminate_app(package))

    def foreground(self):
        info = self._call(lambda driver: driver.execute_script('mobile: activeAppInfo'))
        if info.get('bundleId') == self.bundle_id:
            pid = info.get('pid')
            if isinstance(pid, int) and pid > 0:
                if self._app_pid != pid:self._log_lines = []
                self._app_pid = pid
        return info.get('bundleId', '')

    @staticmethod
    def has_alert(screen):
        return any(n.get('type', n.tag) == 'XCUIElementTypeAlert' and n.get('visible') != 'false' for n in ET.fromstring(screen.xml).iter())

    @staticmethod
    def limitation_reason(screen):
        if any(n.get('type', n.tag) == 'XCUIElementTypeWebView' and n.get('visible') != 'false' for n in ET.fromstring(screen.xml).iter()):
            return 'This WebView could not be operated through native accessibility. DOM context automation is not configured; expose native accessibility or use a dedicated WebView case.'
        return ''

    def permits_foreground(self, foreground, screen):
        return foreground == self.bundle_id or (foreground == 'com.apple.springboard' and self.has_alert(screen))

    @staticmethod
    def capture_safe(screen):
        return not any(n.get('type', n.tag) == 'XCUIElementTypeKeyboard' and n.get('visible') != 'false' for n in ET.fromstring(screen.xml).iter())

    def app_logs(self, max_chars=20000):
        # Appium's syslog is device-wide. Export only messages containing this
        # app's observed PID; never return an unfiltered device log.
        try:
            foreground = self.foreground()
            if foreground != self.bundle_id:
                return '\n'.join(self._log_lines)[-max_chars:] or 'iOS app logs unavailable while another app is foreground.'
            if not self._app_pid:return 'iOS app logs unavailable: the target app PID is not known.'
            marker = re.compile(r'\[' + str(self._app_pid) + r'(?::[^\]]+)?\]')
            records = self._call(lambda driver: driver.get_log('syslog'))
            for record in records:
                for line in str(record.get('message', '')).splitlines():
                    if marker.search(line):self._log_lines.append(line)
            self._log_lines = self._log_lines[-300:]
            return '\n'.join(self._log_lines)[-max_chars:] or 'No app-scoped iOS syslog entries were available.'
        except DeviceError:return 'App-scoped iOS syslog is unavailable on this device/session.'

    def type_text(self, element, value):
        if not value or len(value) > 200:raise DeviceError('Input text must be 1–200 characters.')
        target = self._element(element)
        # Native send_keys focuses this exact element. Do not infer focus from
        # keyboard visibility or select the nearest field after a layout shift.
        if element.value:self._call(lambda _: target.clear())
        self._call(lambda _: target.send_keys(value))
        if not element.password:
            actual = self._call(lambda _: target.get_attribute('value'))
            if actual != value:raise DeviceError('iOS text entry did not match the requested value.')

    def set_value(self, element, value):
        if not isinstance(value, str) or not value.strip() or len(value) > 200:
            raise DeviceError('Provide an explicit picker value or slider position.')
        if element.role not in {'picker', 'slider'}:raise DeviceError('SET_VALUE requires an observed picker or slider.')
        if element.role == 'slider':
            try:position = float(value)
            except ValueError:raise DeviceError('Slider position must be a number from 0 to 1.') from None
            if not math.isfinite(position) or not 0 <= position <= 1:raise DeviceError('Slider position must be from 0 to 1.')
            value = str(position)
        target = self._element(element)
        self._call(lambda _: target.send_keys(value))
        actual = str(self._call(lambda _: target.get_attribute('value')) or '')
        if element.role == 'picker':
            matches = actual == value
        else:
            try:
                normalized = float(actual.rstrip('%')) / (100 if actual.endswith('%') else 1)
                matches = abs(normalized - position) <= .01
            except ValueError:matches = False
        if not matches:raise DeviceError('The control did not report the requested value; review its visible state.')

    def running(self, package):
        return self._call(lambda driver: driver.query_app_state(package)) in (3, 4)

    def suppress_credential_prompts(self):return nullcontext()
    def suppress_notification_prompt(self, package):return nullcontext()

    def hide_keyboard(self):
        if self._call(lambda driver: driver.is_keyboard_shown()):
            # Some custom keyboards cannot be dismissed. Keep their observed UI
            # rather than turning a keyboard-dismiss failure into navigation.
            try:self._call(lambda driver: driver.hide_keyboard())
            except DeviceError:pass

    def back(self):
        screen = self.observe()
        targets = [e for e in screen.elements if e.role == 'button' and e.label.casefold() in {'back', '戻る', 'trở lại'}]
        if len(targets) != 1:raise DeviceError('iOS has no system Back action. Select an observed navigation control explicitly.')
        self.tap(targets[0])

    def swipe_scrollable_next_item(self, width, height, screen=None):
        self.swipe('up', width, height)
        return {'source': 'ios_viewport', 'direction': 'up'}

    def observe(self, retries=2):
        started = time.perf_counter()
        raw = self._call(lambda driver: driver.page_source)
        try:screen = self._parse(ET.fromstring(raw), raw)
        except (ET.ParseError, ValueError, TypeError):raise DeviceError('XCUITest returned an invalid iOS hierarchy.') from None
        self.last_observation_timings = {'total_ms': round((time.perf_counter() - started) * 1000)}
        return screen

    def _parse(self, root, raw):
        width, height = self.size()  # XCUITest coordinates are points, not screenshot pixels.
        elements, texts = [], []
        alerts = [n for n in root.iter() if n.get('type', n.tag) == 'XCUIElementTypeAlert' and n.get('visible') != 'false']
        if len(alerts) == 1:root = alerts[0]  # Never tap app controls behind an alert.
        fields = {'XCUIElementTypeTextField', 'XCUIElementTypeSecureTextField', 'XCUIElementTypeTextView', 'XCUIElementTypeSearchField'}
        controls = fields | {'XCUIElementTypeButton', 'XCUIElementTypeLink', 'XCUIElementTypeSwitch', 'XCUIElementTypeCell', 'XCUIElementTypeKey', 'XCUIElementTypePickerWheel', 'XCUIElementTypeSlider', 'XCUIElementTypeSegmentedControl', 'XCUIElementTypeCheckBox', 'XCUIElementTypeRadioButton'}
        for node in root.iter():
            kind = node.get('type', node.tag)
            if node.get('visible') == 'false':continue
            editable = kind in fields
            password = kind == 'XCUIElementTypeSecureTextField'
            label = node.get('label', '') or node.get('name', '')
            value = node.get('value', '')
            # Editable values never enter public screen text; credential screens
            # are additionally withheld by the Agent's evidence guard.
            if not editable:
                for text in (label, value):
                    if text and text not in texts:texts.append(text)
            accessible_custom = kind in {'XCUIElementTypeOther', 'XCUIElementTypeStaticText', 'XCUIElementTypeImage'} and node.get('accessible') == 'true' and bool(label)
            if (kind not in controls and not accessible_custom) or node.get('enabled') == 'false':continue
            x, y, w, h = (float(node.get(key, '0')) for key in ('x', 'y', 'width', 'height'))
            if w <= 0 or h <= 0 or x >= width or y >= height or x+w <= 0 or y+h <= 0:continue
            identifier = node.get('name', '')
            if editable and value:
                if label == value and not re.fullmatch(r'(?:enter (?:your )?)?(?:e-?mail(?: address)?|username|user name|password|search|message|comment)', label, re.I):label = '<editable field>'
                if identifier == value:identifier = ''
            if password:label = '<credential field>'
            checkable = kind in {'XCUIElementTypeSwitch', 'XCUIElementTypeCheckBox', 'XCUIElementTypeRadioButton'}
            role = 'textbox' if editable else 'picker' if kind == 'XCUIElementTypePickerWheel' else 'slider' if kind == 'XCUIElementTypeSlider' else 'button'
            operations = ('TYPE_TEXT',) if editable else ('SET_VALUE',) if role in {'picker', 'slider'} else ('TAP',)
            elements.append(Element(str(len(elements)+1), role, label or kind.removeprefix('XCUIElementType'), identifier, kind,
                                    value, (x, y, x+w, y+h), operations, editable, password,
                                    node.get('focused') == 'true', value == '1' if checkable else False, checkable))
            if len(elements) >= 100:break
        fingerprint = hashlib.sha256(json.dumps([texts, [(e.signature, e.value) for e in elements]], ensure_ascii=False).encode()).hexdigest()[:20]
        return Screen(raw, elements, '\n'.join(texts), fingerprint, width, height)

    def _element(self, element):
        def literal(value):
            if "'" not in value:return "'" + value + "'"
            if '"' not in value:return '"' + value + '"'
            return 'concat(' + ', "\'", '.join("'" + part + "'" for part in value.split("'")) + ')'
        x, y, right, bottom = element.bounds
        parts = [f'@type={literal(element.class_name)}', f'@x={x}', f'@y={y}', f'@width={right-x}', f'@height={bottom-y}', "@enabled='true'", "@visible='true'"]
        if element.resource_id:parts.append('@name=' + literal(element.resource_id))
        matches = self._call(lambda driver: driver.find_elements('xpath', '//*[' + ' and '.join(parts) + ']'))
        if len(matches) != 1:raise DeviceError('The observed iOS control is missing or ambiguous; re-observe before acting.')
        return matches[0]

    def metadata(self):
        info = {'manufacturer': 'Apple', 'package': self.bundle_id, 'automation_backend': 'appium', 'session_start_ms': str(self.session_start_ms)}
        for item in discover_ios():
            if item['serial'] == self.serial:
                info.update(model=item['model'], ios_version=item['ios_version'])
                try:
                    if item['simulator']:
                        result = subprocess.run(['xcrun', 'simctl', 'listapps', self.serial], capture_output=True, check=True, timeout=10)
                        import plistlib
                        # simctl can emit an OpenStep plist; normalize before parsing.
                        converted = subprocess.run(['plutil', '-convert', 'xml1', '-o', '-', '-'], input=result.stdout, capture_output=True, check=True, timeout=5)
                        apps = plistlib.loads(converted.stdout)
                        version = apps.get(self.bundle_id, {}).get('CFBundleShortVersionString')
                        if version:info['app_version'] = str(version)
                    else:
                        apps = apple_json('device', 'info', 'apps', '--device', self.serial).get('apps', [])
                        app = next((a for a in apps if a.get('bundleIdentifier') == self.bundle_id), {})
                        if app.get('version'):info['app_version'] = str(app['version'])
                except (DeviceError, OSError, ValueError, subprocess.SubprocessError):pass
        try:info['screen_size'] = ' × '.join(map(str, self.size())) + ' points'
        except DeviceError:pass
        return info

    @contextmanager
    def screen_recording(self, output):
        output.mkdir(parents=True, exist_ok=True)
        path = output / f'screen-recording-{time.time_ns()}.mp4'
        self.recording_error = ''
        try:
            self._call(lambda driver: driver.start_recording_screen(timeLimit='600', videoType='h264'))
            self._recording = True
        except DeviceError:
            self.recording_error = 'iOS screen recording could not start. Check ffmpeg and XCUITest recording support.'
        try:yield
        finally:
            if self._recording:
                try:
                    encoded = self._call(lambda driver: driver.stop_recording_screen())
                    data = base64.b64decode(encoded, validate=True)
                    if not data:raise ValueError('empty recording')
                    path.write_bytes(data)
                except (DeviceError, ValueError, OSError):
                    self.recording_error = 'iOS screen recording could not be saved.'
                finally:self._recording = False
            if self.recording_error:
                (output / 'recording-error.txt').write_text(self.recording_error + '\n')
            if self._close_requested:self.close()
