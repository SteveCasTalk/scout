import unittest

from scout_mobile.execution_contract import check_support, supported

PKG = 'com.example.app'


class AdbCapabilitiesTest(unittest.TestCase):
    def test_adb_supports_targeted_swipe(self):
        self.assertIn('target_gestures', supported('Android', 'adb'))
        case = {'execution': {'required_capabilities': ['target_gestures'], 'actions': [
            {'id': 'swipe', 'operation': 'SWIPE', 'package': PKG, 'selector': {'resource_id': 'list'}, 'direction': 'up'}]}}
        self.assertIsNotNone(check_support(case, 'Android', 'adb'))

    def test_adb_rejects_drag_with_hold(self):
        case = {'execution': {'required_capabilities': ['target_gestures'], 'actions': [
            {'id': 'drag', 'operation': 'DRAG', 'package': PKG, 'selector': {'text': 'Item'}, 'destination': {'text': 'Bin'}}]}}
        with self.assertRaisesRegex(ValueError, 'requires the Appium adapter'):
            check_support(case, 'Android', 'adb')
        self.assertIsNotNone(check_support(case, 'Android', 'appium'))

    def test_tap_burst_stays_appium_only(self):
        self.assertNotIn('tap_burst', supported('Android', 'adb'))


if __name__ == '__main__':
    unittest.main()
