import unittest
from subprocess import CompletedProcess

from scout_mobile.device import AndroidDevice, DeviceError

STALE = '<hierarchy><node text="Stale screen" bounds="[0,0][10,10]" class="android.widget.TextView"/></hierarchy>'


class AndroidObserveTest(unittest.TestCase):
    def _device(self, dump_output: bytes):
        device = AndroidDevice('fake')
        device.size = lambda: (1080, 2340)
        files = {'/sdcard/window.xml': STALE}
        calls = []

        def command(*args, **_kwargs):
            calls.append(args)
            if args[1:3] == ('rm', '-f'):
                files.pop(args[3], None)
                return CompletedProcess(args, 0, b'', b'')
            if args[1:3] == ('uiautomator', 'dump'):
                return CompletedProcess(args, 0, dump_output, b'')
            if args[0] == 'exec-out':
                if args[2] not in files:
                    return CompletedProcess(args, 1, b'', b'No such file')
                return CompletedProcess(args, 0, files[args[2]].encode(), b'')
            return CompletedProcess(args, 0, b'', b'')

        device.command = command
        return device, calls

    def test_failed_dump_never_returns_the_previous_screen(self):
        device, calls = self._device(b'ERROR: could not get idle state.\n')
        with self.assertRaisesRegex(DeviceError, 'could not get idle state'):
            device.observe(retries=2)
        self.assertFalse(any(c[0] == 'exec-out' for c in calls))

    def test_transient_null_root_is_retried(self):
        device, calls = self._device(b'')
        outputs = iter([b'ERROR: null root node returned by UiTestAutomationBridge.\n', b'UI hierchary dumped to: /sdcard/window.xml\n'])
        original = device.command

        def command(*args, **kwargs):
            if args[1:3] == ('uiautomator', 'dump'):
                calls.append(args)
                out = next(outputs)
                if b'dumped' in out:
                    files_written.append(True)
                return CompletedProcess(args, 0, out, b'')
            if args[0] == 'exec-out' and files_written:
                return CompletedProcess(args, 0, STALE.encode(), b'')
            return original(*args, **kwargs)
        files_written = []
        device.command = command
        import scout_mobile.device as d
        sleep, d.time.sleep = d.time.sleep, (lambda _s: None)
        try:
            screen = device.observe(retries=1)
        finally:
            d.time.sleep = sleep
        self.assertIn('Stale screen', screen.text)

    def test_dump_file_is_removed_before_each_dump(self):
        device, calls = self._device(b'UI hierchary dumped to: /sdcard/window.xml\n')
        with self.assertRaises(DeviceError):
            device.observe(retries=1)  # the stub writes no new file, so the stale one must not be read
        self.assertEqual(calls[0][1:3], ('rm', '-f'))


if __name__ == '__main__':
    unittest.main()
