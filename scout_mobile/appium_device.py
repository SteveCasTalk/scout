"""Appium Android backend; ADB remains the diagnostics transport.

Sessions are lazy, preserve app data, and use native context only. No command
falls back silently to ADB when Appium fails. The shared parser normalizes
UiAutomator2 XML into the same observed controls as the existing runner.
"""
from __future__ import annotations
from .config import getenv

import time
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

from .device import AndroidDevice, DeviceError, Element, Screen, tap_point


class AppiumAndroidDevice(AndroidDevice):
    backend = 'appium'

    def __init__(self, serial: str, adb: str = 'adb', server_url: str = 'http://127.0.0.1:4723', idle_timeout_ms: int | None = None):
        super().__init__(serial, adb)
        url = urlparse(server_url)
        if url.scheme != 'http' or url.hostname not in {'localhost', '127.0.0.1', '::1'} or url.username or url.password or url.query or url.fragment:
            raise ValueError('The Appium trial requires a local HTTP server URL without credentials.')
        self.server_url = server_url.rstrip('/')
        configured = getenv('SCOUT_APPIUM_IDLE_TIMEOUT_MS', '')
        self.idle_timeout_ms = idle_timeout_ms if idle_timeout_ms is not None else int(configured) if configured else 1000
        if self.idle_timeout_ms is not None and (type(self.idle_timeout_ms) is not int or not 0 <= self.idle_timeout_ms <= 10000):
            raise ValueError('Appium idle timeout must be 0–10000 milliseconds.')
        self._driver = None
        self.session_start_ms = 0
        self._system_bars: list[tuple[int, int, int, int]] | None = None

    @property
    def driver(self):
        if self._driver is None:
            try:
                from appium import webdriver
                from appium.options.android import UiAutomator2Options
            except ImportError:
                raise DeviceError('Install the project dependencies: uv sync') from None
            from .appium_runtime import ensure_appium
            ensure_appium(self.server_url)
            options = UiAutomator2Options().load_capabilities({
                'platformName': 'Android', 'appium:automationName': 'UiAutomator2',
                'appium:udid': self.serial, 'appium:noReset': True,
                'appium:fullReset': False, 'appium:autoLaunch': False,
                'appium:newCommandTimeout': 1800,
                'appium:printPageSourceOnFindFailure': False,
            })
            if self.idle_timeout_ms is not None:
                options.set_capability('appium:settings[waitForIdleTimeout]', self.idle_timeout_ms)
            started = time.perf_counter()
            try:
                self._driver = webdriver.Remote(self.server_url, options=options)
                self._driver.implicitly_wait(0)
            except Exception as exc:
                self.close()
                # Driver messages can include page source or typed credentials.
                raise DeviceError(f'Appium session could not start ({type(exc).__name__}). Check the local server and UiAutomator2 doctor.') from None
            self.session_start_ms = round((time.perf_counter() - started) * 1000)
        return self._driver

    def _call(self, action):
        try:
            return action(self.driver)
        except DeviceError:
            raise
        except Exception as exc:
            raise DeviceError(f'Appium command failed ({type(exc).__name__}); no ADB fallback was attempted.') from None

    def close(self) -> None:
        driver, self._driver = self._driver, None
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass  # Preserve the original outcome; server also has an idle timeout.

    def launch(self, package: str) -> None:
        self._call(lambda driver: driver.activate_app(package))

    def foreground(self) -> str:
        return self._call(lambda driver: driver.current_package)

    def size(self) -> tuple[int, int]:
        started = time.perf_counter()
        if self._screen_size is None or time.monotonic() - self._screen_size_read_at >= self.screen_size_cache_seconds:
            size = self._call(lambda driver: driver.get_window_size())
            self._screen_size = (int(size['width']), int(size['height']))
            self._screen_size_read_at = time.monotonic()
        self.last_size_lookup_ms = round((time.perf_counter() - started) * 1000)
        return self._screen_size

    def observe(self, retries: int = 2) -> Screen:
        started = time.perf_counter()
        raw = self._call(lambda driver: driver.page_source)
        source_ms = round((time.perf_counter() - started) * 1000)
        try:
            root = ET.fromstring(raw)
            for node in root.iter():
                if node is not root:
                    node.set('class', node.get('class', node.tag))
                    node.tag = 'node'
            normalized = ET.tostring(root, encoding='unicode')
            screen = self._parse(root, normalized)
        except (ET.ParseError, TypeError, ValueError):
            raise DeviceError('Appium returned an invalid Android hierarchy.') from None
        self.last_observation_timings = {'page_source_ms': source_ms, 'screen_size_lookup_ms': self.last_size_lookup_ms, 'total_ms': round((time.perf_counter() - started) * 1000)}
        return screen

    def screenshot(self, path: Path) -> None:
        data = self._call(lambda driver: driver.get_screenshot_as_png())
        if not data.startswith(b'\x89PNG'):
            raise DeviceError('Appium screenshot was not a PNG.')
        path.write_bytes(data)

    def _element(self, element: Element):
        # Match a fresh native element by observed attributes and bounds. A
        # missing or duplicate match is an error rather than a guessed target.
        def literal(value):
            if "'" not in value:return "'" + value + "'"
            if '"' not in value:return '"' + value + '"'
            return 'concat(' + ', "\'", '.join("'" + part + "'" for part in value.split("'")) + ')'
        left, top, right, bottom = element.bounds
        bounds = f'[{left},{top}][{right},{bottom}]'
        predicates = [f'@class={literal(element.class_name)}', f'@bounds={literal(bounds)}']
        predicates.append("(@clickable='true' or @checkable='true' or @editable='true' or contains(@class,'EditText'))")
        if element.resource_id:predicates.append(f'@resource-id={literal(element.resource_id)}')
        # One snapshot lookup avoids stale candidates during multiple rect calls.
        matches = self._call(lambda driver: driver.find_elements('xpath', '//*[' + ' and '.join(predicates) + ']'))
        if len(matches) != 1:
            raise DeviceError('The observed Appium target is missing or ambiguous; re-observe before acting.')
        return matches[0]

    def system_bars(self) -> list[tuple[int, int, int, int]]:
        """Visible status/navigation bar rectangles; edge-to-edge apps draw content underneath them."""
        if self._system_bars is None:
            try:
                bars = self._call(lambda driver: driver.execute_script('mobile: getSystemBars')) or {}
                self._system_bars = [(int(bar['x']), int(bar['y']), int(bar['x']) + int(bar['width']), int(bar['y']) + int(bar['height']))
                                     for bar in (bars.get('statusBar'), bars.get('navigationBar'))
                                     if isinstance(bar, dict) and bar.get('visible') and int(bar.get('height', 0)) > 0]
            except (DeviceError, KeyError, TypeError, ValueError):
                self._system_bars = []
        return self._system_bars

    def tap(self, element: Element, screen: Screen | None = None) -> None:
        point = tap_point(element, screen, self.system_bars()) if screen is not None else element.center
        if point != element.center:
            # The centre is covered (floating bar, system navigation): tap the uncovered point instead of click().
            x, y = point
            self._pointer_sequence([{'type': 'pointerMove', 'duration': 0, 'x': x, 'y': y, 'origin': 'viewport'},
                                    {'type': 'pointerDown', 'button': 0}, {'type': 'pause', 'duration': 60}, {'type': 'pointerUp', 'button': 0}])
            return
        target = self._element(element)
        self._call(lambda _: target.click())

    def type_text(self, element: Element, value: str) -> None:
        if not value or len(value) > 200:
            raise DeviceError('Input text must be 1–200 characters.')
        target = self._element(element)
        if element.value:
            self._call(lambda _: target.clear())
        self._call(lambda _: target.send_keys(value))
        if not element.password:
            deadline = time.monotonic() + 5
            while True:
                screen = self.observe()
                if any(e.role == 'textbox' and e.value == value for e in screen.elements):
                    return
                if time.monotonic() >= deadline:
                    raise DeviceError('Appium text entry did not settle to the requested value.')
                time.sleep(.2)

    def swipe_coordinates(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> None:
        self._call(lambda driver: driver.swipe(x1, y1, x2, y2, duration_ms))

    def _pointer_sequence(self, actions: list[dict]) -> None:
        from selenium.webdriver.remote.command import Command
        self._call(lambda driver: driver.execute(Command.W3C_ACTIONS, {'actions': [{'type': 'pointer', 'id': 'scout-touch', 'parameters': {'pointerType': 'touch'}, 'actions': actions}]}))

    def drag_coordinates(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int, hold_ms: int) -> None:
        self._pointer_sequence([{'type':'pointerMove','duration':0,'x':x1,'y':y1,'origin':'viewport'}, {'type':'pointerDown','button':0}, {'type':'pause','duration':hold_ms}, {'type':'pointerMove','duration':duration_ms,'x':x2,'y':y2,'origin':'viewport'}, {'type':'pointerUp','button':0}])

    def tap_burst(self, element: Element, count: int, interval_ms: int) -> dict:
        # All taps are one native sequence; host/model turns cannot stretch the interval.
        if not 2 <= count <= 5 or not 50 <= interval_ms <= 1000:
            raise DeviceError('Invalid bounded tap burst.')
        x,y=element.center
        actions=[{'type':'pointerMove','duration':0,'x':x,'y':y,'origin':'viewport'}]
        for index in range(count):
            if index:actions.append({'type':'pause','duration':interval_ms})
            actions.extend([{'type':'pointerDown','button':0},{'type':'pointerUp','button':0}])
        start=time.monotonic_ns();self._pointer_sequence(actions);end=time.monotonic_ns()
        return {'count':count,'interval_ms':interval_ms,'requested_offsets_ms':[i*interval_ms for i in range(count)],'dispatch_duration_ms':round((end-start)/1_000_000),'timing_source':'native_requested_offsets','delivery_timestamps_verified':False}

    def back(self) -> None:
        self._call(lambda driver: driver.back())
