import unittest

from scout_mobile.device import Screen
from scout_mobile.execution_runtime import ExecutionBlocked, locate

BUTTON = ('<node class="android.widget.Button" clickable="true" text="" content-desc="" resource-id="{rid}" bounds="{b}">'
          '<node class="android.widget.TextView" clickable="false" text="Try again" content-desc="" resource-id="" bounds="{b}"/></node>')


def screen(*nodes):
    xml = '<hierarchy><node class="android.widget.FrameLayout" clickable="false" text="" content-desc="" resource-id="" bounds="[0,0][1080,2340]">' + ''.join(nodes) + '</node></hierarchy>'
    return Screen(xml, [], '', 'f', 1080, 2340)


class SelectorGroundingTest(unittest.TestCase):
    def test_text_inside_button_resolves_to_the_button(self):
        target = locate(screen(BUTTON.format(rid='retry', b='[400,700][680,760]')), {'text': 'Try again'}, tap=True)
        self.assertEqual(target.resource_id, 'retry')
        self.assertEqual(target.bounds, (400, 700, 680, 760))
        self.assertIn('TAP', target.operations)

    def test_two_buttons_with_the_same_text_stay_ambiguous(self):
        s = screen(BUTTON.format(rid='a', b='[0,700][300,760]'), BUTTON.format(rid='b', b='[400,700][700,760]'))
        with self.assertRaises(ExecutionBlocked):
            locate(s, {'text': 'Try again'}, tap=True)

    def test_text_without_clickable_container_is_not_tappable(self):
        s = screen('<node class="android.widget.TextView" clickable="false" text="Try again" content-desc="" resource-id="" bounds="[0,0][100,50]"/>')
        with self.assertRaises(ExecutionBlocked):
            locate(s, {'text': 'Try again'}, tap=True)

    def test_non_tap_selector_still_matches_the_text_node(self):
        target = locate(screen(BUTTON.format(rid='retry', b='[400,700][680,760]')), {'text': 'Try again'})
        self.assertEqual(target.class_name, 'android.widget.TextView')


if __name__ == '__main__':
    unittest.main()
