"""Synthetic checks for reachable, exact verdicts. These do not claim Twomi device acceptance."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET

from scout_mobile.agent import Agent, RunConfig
from scout_mobile.checkpoints import control_state, evaluate, validate_checkpoints
from scout_mobile.device import AndroidDevice, DeviceError
from scout_mobile.execution_contract import validate_execution
from scout_mobile.execution_runtime import AccountMismatch, ExecutionBlocked, ObservationIncomplete, PathNotReached, PrerequisiteMissing, Protocol, SelectorMissing, locate
from scout_mobile.skill_import import check_against_run, draft_path, mark_explored, setup_needed
from scout_mobile.starting_conditions import validate_account_username, validate_starting_conditions

PKG = 'com.example.synthetic'
SAVE = '<node class="Button" text="" clickable="{clickable}" enabled="{enabled}" bounds="[20,100][420,180]"><node class="Text" text="Save" bounds="[30,110][400,170]"/></node>'
BOX = '<node class="android.widget.EditText" text="{value}" clickable="true" bounds="[20,300][420,500]"/>'


def parse(body):
    xml = f'<hierarchy>{body}</hierarchy>'
    device = AndroidDevice('synthetic')
    device.size = lambda: (500, 900)
    return device._parse(ET.fromstring(xml), xml)


def edit_screen(enabled='false', value='Old caption'):
    return parse(SAVE.format(clickable='true', enabled=enabled) + BOX.format(value=value))


class FakeDevice:
    """Replays screens; the last one stays on screen."""
    platform = 'Android'
    def __init__(self, *screens):
        self.screens, self.calls = list(screens), []
    def observe(self):
        return self.screens.pop(0) if len(self.screens) > 1 else self.screens[0]
    def foreground(self):
        return PKG
    def type_text(self, element, text):
        self.calls.append(('type', element.value, text))
    def clear_text(self, element):
        self.calls.append(('clear', element.value))
        return 'adb'
    def restart_app(self, package):
        self.calls.append(('restart', package))
    def press_enter(self):
        self.calls.append(('enter',))
    def tap(self, element, screen=None):
        self.calls.append(('tap', element.label))
    def screenshot(self, path):
        path.write_bytes(b'')


def run_actions(actions, *screens, role='', secrets=(), username='', run_username=''):
    capabilities = ['text_entry'] if any(a['operation'] in {'TYPE_TEXT', 'CLEAR_TEXT', 'SUBMIT'} for a in actions) else []
    with tempfile.TemporaryDirectory() as folder:
        case = {'starting_conditions': {'account_role': role, 'account_username': username}, 'execution': {'required_capabilities': capabilities, 'actions': [{'package': PKG, **a} for a in actions]}}
        with patch.dict('os.environ', {'SCOUT_ANDROID_DRIVER': 'adb'}):
            agent = Agent(RunConfig(PKG, 'synthetic', case, Path(folder), account_username=run_username))
        agent.device = FakeDevice(*screens)
        agent.secrets = list(secrets)
        agent.screenshot = lambda screen, index: None
        agent.assess_checkpoints = lambda screen, index: None
        agent.protocol.run()
        return agent


class ObservationTests(unittest.TestCase):
    def test_disabled_control_is_visible_in_public_observation(self):
        save = next(e for e in edit_screen().elements if e.label == 'Save')
        self.assertFalse(save.public()['enabled'])
        self.assertEqual(save.operations, ())

    def test_enabled_state_changes_the_screen_fingerprint(self):
        self.assertNotEqual(edit_screen('false').fingerprint, edit_screen('true').fingerprint)


class ControlStateTests(unittest.TestCase):
    def check(self, state='disabled', scope='final'):
        return {'id': 'save', 'expected': 'Save', 'scope': scope, 'required': True, 'method': 'control_state', 'state': state}

    def observe(self, enabled):
        return [{'step': 3, 'text': 'Save', 'elements': [e.public() for e in edit_screen(enabled).elements]}]

    def test_validation_requires_a_known_state_only_on_control_state(self):
        self.assertEqual(validate_checkpoints([self.check()])[0]['state'], 'disabled')
        with self.assertRaises(ValueError):
            validate_checkpoints([{**self.check(), 'state': 'on'}])
        with self.assertRaises(ValueError):
            validate_checkpoints([{**self.check(), 'method': 'text_present'}])
        without_state = {key: value for key, value in self.check().items() if key != 'state'}
        with self.assertRaises(ValueError):
            validate_checkpoints([without_state])
        self.assertNotIn('state', validate_checkpoints([{**without_state, 'method': 'text_present', 'state': None}])[0])

    def test_final_verdict_is_exact_and_needs_no_model(self):
        with patch.dict('os.environ', {'TYPESAFE_API_KEY': ''}):
            self.assertEqual(evaluate([self.check()], self.observe('false'), 'goal', True)[0]['verdict'], 'satisfied')
            self.assertEqual(evaluate([self.check()], self.observe('true'), 'goal', True)[0]['verdict'], 'violated')

    def test_missing_control_is_not_a_failure(self):
        result = evaluate([{**self.check(), 'expected': 'Publish'}], self.observe('false'), 'goal', True)[0]
        self.assertEqual(result['verdict'], 'not_observable')

    def test_during_run_can_still_be_reached_later(self):
        self.assertEqual(evaluate([self.check(scope='during_run')], self.observe('true'), 'goal', False)[0]['verdict'], 'not_reached')

    def test_duplicate_labels_and_uncheckable_controls_are_unknown(self):
        twice = [{'label': 'Save', 'enabled': True}, {'label': 'Save', 'enabled': False}]
        self.assertIsNone(control_state(twice, 'Save', 'enabled'))
        self.assertIsNone(control_state([{'label': 'Save', 'checkable': False}], 'Save', 'checked'))

    def test_exploration_must_have_seen_the_control(self):
        trace = [{'screen': {'text': 'x', 'elements': [{'label': 'Save'}]}}]
        check_against_run([self.check()], trace)
        with self.assertRaisesRegex(ValueError, 'Publish'):
            check_against_run([{**self.check(), 'expected': 'Publish'}], trace)


class SelectorTests(unittest.TestCase):
    def test_prefix_selects_one_control_and_ambiguity_blocks(self):
        one = parse('<node class="Button" text="Video by Dog, Blue, 0 views" clickable="true" bounds="[0,0][100,100]"/><node class="Button" text="Video by Dog, Red, 0 views" clickable="true" bounds="[0,200][100,300]"/>')
        self.assertEqual(locate(one, {'text_starts_with': 'Video by Dog, Blue'}, tap=True).bounds, (0, 0, 100, 100))
        with self.assertRaises(SelectorMissing):
            locate(one, {'text_starts_with': 'Video by Dog'}, tap=True)

    def test_class_alone_is_only_for_text_fields(self):
        action = {'id': 'a', 'operation': 'TAP', 'package': PKG, 'selector': {'class_name': 'android.widget.Button'}}
        with self.assertRaises(ValueError):
            validate_execution({'actions': [action]})
        validate_execution({'actions': [{**action, 'selector': {'class_name': 'android.widget.EditText'}}]})

    def test_disabled_control_cannot_be_tapped(self):
        with self.assertRaises(SelectorMissing):
            locate(edit_screen('false'), {'text': 'Save'}, tap=True)


class TypedTextTests(unittest.TestCase):
    FIELD = {'class_name': 'android.widget.EditText'}

    def test_contract_declares_text_entry_and_requires_text(self):
        typed = {'id': 'a', 'operation': 'TYPE_TEXT', 'package': PKG, 'selector': self.FIELD, 'text': 'Hello'}
        with self.assertRaisesRegex(ValueError, 'text_entry'):
            validate_execution({'actions': [typed]})
        with self.assertRaises(ValueError):
            validate_execution({'required_capabilities': ['text_entry'], 'actions': [{**typed, 'text': ' '}]})
        with self.assertRaises(ValueError):
            validate_execution({'actions': [{'id': 'a', 'operation': 'BACK', 'package': PKG, 'text': 'Hello'}]})

    def test_typing_uses_the_observed_field_value_and_records_the_text(self):
        agent = run_actions([{'id': 'a', 'operation': 'TYPE_TEXT', 'selector': self.FIELD, 'text': 'New'}], edit_screen(), edit_screen(value='New'))
        self.assertEqual(agent.device.calls, [('type', 'Old caption', 'New')])
        self.assertEqual(agent.history[-1]['text'], 'New')

    def test_text_must_be_held_exactly_including_trailing_spaces(self):
        action = {'id': 'a', 'operation': 'TYPE_TEXT', 'selector': self.FIELD, 'text': 'New  '}
        run_actions([action], edit_screen(), edit_screen(value='New  '))
        with self.assertRaises(ObservationIncomplete):
            run_actions([action], edit_screen(), edit_screen(value='New'))

    def test_clear_and_submit_dispatch(self):
        agent = run_actions([{'id': 'a', 'operation': 'CLEAR_TEXT', 'selector': self.FIELD}, {'id': 'b', 'operation': 'SUBMIT'}], edit_screen(), edit_screen(value=''))
        self.assertEqual(agent.device.calls, [('clear', 'Old caption'), ('enter',)])

    def test_submit_focuses_the_selected_field_first(self):
        agent = run_actions([{'id': 'a', 'operation': 'SUBMIT', 'selector': self.FIELD}], edit_screen())
        self.assertEqual([call[0] for call in agent.device.calls], ['tap', 'enter'])

    def test_a_failed_clear_is_not_an_app_result(self):
        with self.assertRaisesRegex(ObservationIncomplete, 'still holds'):
            run_actions([{'id': 'a', 'operation': 'CLEAR_TEXT', 'selector': self.FIELD}], edit_screen())

    def test_clear_records_its_transport(self):
        agent = run_actions([{'id': 'a', 'operation': 'CLEAR_TEXT', 'selector': self.FIELD}], edit_screen(), edit_screen(value=''))
        self.assertEqual(agent.history[-1]['transport'], 'adb')

    def test_credentials_are_refused(self):
        with self.assertRaisesRegex(ExecutionBlocked, 'credentials'):
            run_actions([{'id': 'a', 'operation': 'TYPE_TEXT', 'selector': self.FIELD, 'text': 'my hunter2 text'}], edit_screen(), secrets=['hunter2'])
        password = parse('<node class="android.widget.EditText" text="" password="true" clickable="true" bounds="[20,300][420,500]"/>')
        with self.assertRaisesRegex(ExecutionBlocked, 'credentials'):
            run_actions([{'id': 'a', 'operation': 'TYPE_TEXT', 'selector': self.FIELD, 'text': 'Hello'}], password)
        email = parse('<node class="android.widget.EditText" content-desc="Email" text="" clickable="true" bounds="[20,300][420,500]"/>')
        with self.assertRaisesRegex(ExecutionBlocked, 'credentials'):
            run_actions([{'id': 'a', 'operation': 'TYPE_TEXT', 'selector': self.FIELD, 'text': 'Hello'}], email)

    def test_typing_needs_an_observed_text_field(self):
        with self.assertRaises(SelectorMissing):
            run_actions([{'id': 'a', 'operation': 'TYPE_TEXT', 'selector': {'text': 'Nope'}, 'text': 'Hello'}], edit_screen())

    def test_plain_tap_on_a_text_field_stays_blocked(self):
        with self.assertRaisesRegex(ExecutionBlocked, 'arbitrary text'):
            run_actions([{'id': 'a', 'operation': 'TAP', 'selector': self.FIELD}], edit_screen())


class OptionalTapTests(unittest.TestCase):
    def test_absent_optional_control_is_skipped(self):
        agent = run_actions([{'id': 'a', 'operation': 'TAP', 'selector': {'text': 'Got it'}, 'optional': True, 'timeout_ms': 100}], edit_screen())
        self.assertEqual(agent.device.calls, [])
        self.assertTrue(agent.history[-1]['skipped'])

    def test_late_optional_control_is_tapped(self):
        sheet = parse('<node class="Button" text="Got it" clickable="true" bounds="[0,0][100,100]"/>')
        agent = run_actions([{'id': 'a', 'operation': 'TAP', 'selector': {'text': 'Got it'}, 'optional': True, 'timeout_ms': 3000}], edit_screen(), sheet)
        self.assertEqual(agent.device.calls, [('tap', 'Got it')])

    def test_only_taps_can_be_optional(self):
        with self.assertRaises(ValueError):
            validate_execution({'actions': [{'id': 'a', 'operation': 'BACK', 'package': PKG, 'optional': True}]})


class RequireTests(unittest.TestCase):
    def test_contract_needs_a_reason_and_one_target(self):
        base = {'id': 'a', 'operation': 'REQUIRE', 'package': PKG}
        for extra in ({'require_text': 'Drafts'}, {'reason': 'no draft'}, {'require_text': 'Drafts', 'require_account': True, 'reason': 'x'}):
            with self.assertRaises(ValueError):
                validate_execution({'actions': [{**base, **extra}]})
        with self.assertRaises(ValueError):
            validate_execution({'actions': [{'id': 'a', 'operation': 'BACK', 'package': PKG, 'reason': 'x'}]})

    def test_missing_data_blocks_and_names_it(self):
        with self.assertRaisesRegex(PrerequisiteMissing, 'no draft'):
            run_actions([{'id': 'a', 'operation': 'REQUIRE', 'require_text': 'Drafts', 'reason': 'no draft', 'timeout_ms': 100}], edit_screen())

    def test_present_data_continues(self):
        screen = parse('<node class="Text" text="Drafts" bounds="[0,0][100,100]"/>')
        agent = run_actions([{'id': 'a', 'operation': 'REQUIRE', 'require_text': 'Drafts', 'reason': 'no draft'}], screen)
        self.assertTrue(agent.history[-1]['met'])

    ACCOUNT = {'id': 'a', 'operation': 'REQUIRE', 'require_account': True, 'reason': 'owner must be signed in', 'timeout_ms': 100}
    DOG = '<node class="Text" text="@hilarious_dog" bounds="[0,0][100,100]"/>'

    def test_account_comes_from_the_test_case(self):
        agent = run_actions([self.ACCOUNT], parse(self.DOG), role='owner', username='hilarious_dog')
        self.assertEqual(agent.verified_account, {'role': 'owner', 'username': 'hilarious_dog', 'source': 'test case'})

    def test_run_input_overrides_the_test_case(self):
        agent = run_actions([self.ACCOUNT], parse(self.DOG), username='someone_else', run_username='hilarious_dog')
        self.assertEqual((agent.verified_account['username'], agent.verified_account['source']), ('hilarious_dog', 'run input'))

    def test_environment_is_not_an_account_source(self):
        with patch.dict('os.environ', {'SCOUT_ACCOUNT_OWNER_USERNAME': 'hilarious_dog'}):
            agent = run_actions([], parse(self.DOG), role='owner')
        self.assertEqual(agent.account_username, '')

    def test_wrong_account_blocks_and_never_verifies(self):
        with self.assertRaises(AccountMismatch):
            run_actions([self.ACCOUNT], parse('<node class="Text" text="@someone_else" bounds="[0,0][100,100]"/>'), username='hilarious_dog')

    def test_emails_and_spaces_are_refused(self):
        for value in ('user@example.com', 'two words'):
            with self.assertRaises(ValueError):
                validate_account_username(value)
            with self.assertRaises(ValueError):
                validate_starting_conditions({'account_username': value})
        self.assertEqual(validate_account_username(' @luna '), '@luna')

    def test_role_names_are_restricted(self):
        self.assertEqual(validate_starting_conditions({'account_role': 'fan-member'})['account_role'], 'fan-member')
        with self.assertRaises(ValueError):
            validate_starting_conditions({'account_role': 'user@example.com'})


class ReasonCodeTests(unittest.TestCase):
    def agent(self, verdicts=(), **stop):
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', {'SCOUT_ANDROID_DRIVER': 'adb'}):
            agent = Agent(RunConfig(PKG, 'synthetic', {}, Path(folder)))
        agent.checkpoint_verdicts = {str(index): {'required': True, **verdict} for index, verdict in enumerate(verdicts)}
        agent.stop_code = stop.get('code')
        return agent

    def test_every_outcome_has_a_reason(self):
        self.assertEqual(self.agent().reason_code('Passed', ''), 'verified')
        self.assertEqual(self.agent().reason_code('Failed', ''), 'assertion_violated')
        self.assertEqual(self.agent().reason_code('Execution error', ''), 'runner_error')
        self.assertEqual(self.agent().reason_code('Blocked', ''), 'execution_blocked')
        self.assertEqual(self.agent(code='prerequisite_missing').reason_code('Blocked', ''), 'prerequisite_missing')

    def test_inconclusive_says_which_kind(self):
        code = lambda *verdicts: self.agent(verdicts).reason_code('Inconclusive', '')
        self.assertEqual(code({'verdict': 'not_reached'}), 'path_not_reached')
        self.assertEqual(code({'verdict': 'not_observable', 'reason': 'Evidence is incomplete.'}), 'not_observable')
        self.assertEqual(code({'verdict': 'not_observable', 'reason': 'Classifier proposed violated, but no supporting observation was selected.'}), 'model_unsure')
        self.assertEqual(code(), 'evidence_incomplete')

    def test_wait_failure_carries_its_code(self):
        self.assertEqual(PathNotReached.code, 'path_not_reached')


class AccountGuardTests(unittest.TestCase):
    def run_guard(self, case, run_username='', secrets=()):
        from scout_mobile.engine.nodes.setup import CheckAccountRole
        from scout_mobile.engine.node import RunContext
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', {'SCOUT_ANDROID_DRIVER': 'adb'}):
            agent = Agent(RunConfig(PKG, 'synthetic', case, Path(folder), account_username=run_username))
            agent.device = None
            agent.secrets = list(secrets)
            agent.capture_device_info = lambda: {}
            agent.capture_app_logs = lambda: ''
            out = CheckAccountRole().run(RunContext(agent))
            return out.result if out else None

    REQUIRE = {'execution': {'actions': [{'id': 'a', 'operation': 'REQUIRE', 'package': PKG, 'require_account': True, 'reason': 'x'}]}}

    def test_needed_account_without_a_username_blocks_without_touching_the_device(self):
        for case in ({'starting_conditions': {'account_role': 'premium'}, **self.REQUIRE}, self.REQUIRE):
            result = self.run_guard(case)
            self.assertEqual((result['status'], result['reason_code']), ('Blocked', 'account_not_configured'))
            self.assertIn('starting the run', result['notes'])

    def test_run_input_satisfies_a_needed_account(self):
        self.assertIsNone(self.run_guard({'starting_conditions': {'account_role': 'premium'}, **self.REQUIRE}, 'luna'))

    def test_username_with_nothing_to_verify_it_blocks(self):
        self.assertEqual(self.run_guard({'starting_conditions': {'account_username': 'dog'}})['reason_code'], 'account_unverifiable')

    def test_username_cannot_be_a_credential(self):
        result = self.run_guard({'starting_conditions': {'account_username': 'dog'}, **self.REQUIRE}, secrets=['dog'])
        self.assertEqual(result['reason_code'], 'account_not_configured')

    def test_configured_case_and_no_account_continue(self):
        self.assertIsNone(self.run_guard({'starting_conditions': {'account_username': 'dog'}, **self.REQUIRE}))
        self.assertIsNone(self.run_guard({}))


class RestartAppTests(unittest.TestCase):
    def test_contract_declares_app_restart(self):
        action = {'id': 'a', 'operation': 'RESTART_APP', 'package': PKG}
        with self.assertRaisesRegex(ValueError, 'app_restart'):
            validate_execution({'actions': [action]})
        validate_execution({'required_capabilities': ['app_restart'], 'actions': [action]})

    def test_restart_dispatches_and_is_labelled(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', {'SCOUT_ANDROID_DRIVER': 'adb'}):
            case = {'execution': {'required_capabilities': ['app_restart'], 'actions': [{'id': 'a', 'operation': 'RESTART_APP', 'package': PKG}]}}
            agent = Agent(RunConfig(PKG, 'synthetic', case, Path(folder)))
            agent.device = FakeDevice(edit_screen())
            agent.screenshot = lambda screen, index: None
            agent.assess_checkpoints = lambda screen, index: None
            agent.protocol.run()
        self.assertEqual(agent.device.calls, [('restart', PKG)])
        self.assertEqual(agent.history[-1]['transport'], 'adb')

    def test_android_restart_force_stops_then_launches(self):
        device = AndroidDevice('synthetic')
        calls = []
        device.command = lambda *args, **kwargs: calls.append(args)
        device.launch = lambda package: calls.append(('launch', package))
        foreground = iter(['launcher', 'launcher', PKG])
        device.foreground = lambda: next(foreground)
        with patch('time.sleep'):
            device.restart_app(PKG)
        self.assertEqual(calls, [('shell', 'am', 'force-stop', PKG), ('launch', PKG)])
        self.assertEqual(list(foreground), [])

    def test_app_that_never_returns_is_an_error(self):
        device = AndroidDevice('synthetic')
        device.command = lambda *args, **kwargs: None
        device.launch = lambda package: None
        device.foreground = lambda: 'launcher'
        clock = iter(range(0, 1000, 30))
        with patch('time.sleep'), patch('time.monotonic', lambda: next(clock)):
            with self.assertRaises(DeviceError):
                device.restart_app(PKG)

    def test_cases_cannot_send_raw_commands(self):
        with self.assertRaises(ValueError):
            validate_execution({'actions': [{'id': 'a', 'operation': 'SHELL', 'package': PKG}]})


class AppiumTextEntryTests(unittest.TestCase):
    """The driver's clear can silently do nothing, which used to append new text to the old."""
    def device(self, clear_works=True):
        from scout_mobile.appium_device import AppiumAndroidDevice
        device = AppiumAndroidDevice('synthetic')
        state = {'value': 'Old caption', 'clears': 0}
        def clear(_):
            state['clears'] += 1
            if clear_works:
                state['value'] = ''
        def send(_, value):
            state['value'] += value
        target = type('Target', (), {'clear': clear, 'send_keys': send})()
        device.state = state
        device._element = lambda element: target
        device._call = lambda action: action(None)
        device.observe = lambda: parse(BOX.format(value=state['value']))
        device.tap = lambda element, screen=None: None
        device.command = lambda *args, **kwargs: None
        def keys(count):
            state['keys'] = True
            state['value'] = ''
        device._clear_focused_field = keys
        return device

    def field(self):
        return next(e for e in edit_screen().elements if e.role == 'textbox')

    def run_with_clock(self, action):
        clock = iter(range(0, 10000, 1))
        with patch('time.sleep'), patch('time.monotonic', lambda: next(clock)):
            return action()

    def test_text_replaces_the_old_value(self):
        device = self.device()
        self.run_with_clock(lambda: device.type_text(self.field(), 'Hello'))
        self.assertEqual(device.state['value'], 'Hello')
        self.assertEqual(device.last_text_entry, {'clear': 'appium'})

    def test_ignored_clear_falls_back_to_key_events_instead_of_appending(self):
        device = self.device(clear_works=False)
        self.run_with_clock(lambda: device.type_text(self.field(), 'Hello'))
        self.assertEqual(device.state['value'], 'Hello')
        self.assertEqual((device.state['clears'], device.last_text_entry), (2, {'clear': 'adb'}))

    def test_field_that_cannot_be_cleared_is_never_typed_into(self):
        device = self.device(clear_works=False)
        device._clear_focused_field = lambda count: None
        with self.assertRaisesRegex(DeviceError, 'kept its previous text'):
            self.run_with_clock(lambda: device.type_text(self.field(), 'Hello'))
        self.assertEqual(device.state['value'], 'Old caption')

    def test_failure_reports_lengths_but_not_the_text(self):
        device = self.device()
        target = device._element(None)
        type(target).send_keys = lambda _, value: device.state.update(value='Hel')
        with self.assertRaises(DeviceError) as raised:
            self.run_with_clock(lambda: device.type_text(self.field(), 'Hello'))
        self.assertNotIn('Hello', str(raised.exception))
        self.assertIn('[3]', str(raised.exception))


class WaitForControlTests(unittest.TestCase):
    SAVE = {'id': 'a', 'operation': 'TAP', 'selector': {'text': 'Later'}, 'appear_ms': 3000}

    def test_control_that_returns_after_a_toast_is_tapped(self):
        later = parse('<node class="Button" text="Later" clickable="true" bounds="[0,0][100,100]"/>')
        agent = run_actions([self.SAVE], edit_screen(), later)
        self.assertEqual(agent.device.calls, [('tap', 'Later')])

    def test_control_that_never_returns_still_blocks(self):
        with self.assertRaises(SelectorMissing):
            run_actions([{**self.SAVE, 'appear_ms': 100}], edit_screen())

    def test_appear_needs_a_selector(self):
        with self.assertRaises(ValueError):
            validate_execution({'actions': [{'id': 'a', 'operation': 'BACK', 'package': PKG, 'appear_ms': 100}]})


class RequireAbsentTests(unittest.TestCase):
    ACTION = {'id': 'a', 'operation': 'REQUIRE', 'require_absent': 'Like, 0 likes', 'reason': 'this video has no likes', 'timeout_ms': 100}

    def test_present_text_blocks(self):
        screen = parse('<node class="Button" content-desc="Like, 0 likes" clickable="true" bounds="[0,0][100,100]"/>')
        with self.assertRaisesRegex(PrerequisiteMissing, 'no likes'):
            run_actions([self.ACTION], screen)

    def test_absent_text_continues(self):
        screen = parse('<node class="Button" content-desc="Like, 3 likes" clickable="true" bounds="[0,0][100,100]"/>')
        self.assertTrue(run_actions([self.ACTION], screen).history[-1]['met'])

    def test_an_empty_screen_cannot_establish_absence(self):
        with self.assertRaises(PrerequisiteMissing):
            run_actions([self.ACTION], parse(''))


class DraftPathTests(unittest.TestCase):
    TRACE = [
        {'step': 0, 'operation': 'OBSERVE', 'screen': {'text': 'Home · Feed'}},
        {'step': 1, 'operation': 'TAP', 'label': 'Account', 'resource_id': '', 'page_changed': True, 'screen': {'text': 'Home · hilarious_dog · 3'}},
        {'step': 2, 'operation': 'TAP', 'label': 'Video by Dog, Blue, 0 views', 'resource_id': '', 'page_changed': True, 'screen': {'text': 'Followers'}},
        {'step': 3, 'operation': 'TAP', 'label': 'Sound off', 'resource_id': '', 'page_changed': False, 'screen': {'text': 'Followers'}},
        {'step': 4, 'operation': 'TAP', 'label': 'Open', 'resource_id': 'app:id/open', 'page_changed': True, 'screen': {'text': 'Editor · Save'}},
        {'step': 5, 'operation': 'TYPE_TEXT', 'label': 'Search', 'resource_id': '', 'page_changed': True, 'screen': {'text': 'Editor · hello · Save'}},
        {'step': 6, 'operation': 'DONE'},
        {'step': 7, 'operation': 'VERIFY_CHECKPOINTS'},
    ]

    def draft(self, texts=('hello',)):
        return draft_path(self.TRACE, PKG, list(texts))

    def test_draft_is_a_valid_execution(self):
        self.assertEqual(validate_execution(self.draft()['execution'])['required_capabilities'], ['text_entry'])

    def test_steps_use_observed_selectors_and_waits(self):
        actions = {item['id']: item for item in self.draft()['execution']['actions']}
        self.assertEqual(actions['step_1']['selector'], {'text': 'Account'})
        self.assertEqual(actions['step_1']['wait_text'], 'hilarious_dog')
        self.assertEqual(actions['step_2']['selector'], {'text_starts_with': 'Video by Dog, Blue'})
        self.assertEqual(actions['step_4']['selector'], {'resource_id': 'app:id/open'})
        self.assertEqual(actions['step_5']['selector'], {'class_name': 'android.widget.EditText'})
        self.assertEqual(actions['step_5']['text'], 'hello')
        self.assertEqual(actions['step_1']['appear_ms'], 8000)

    def test_no_change_taps_are_left_out_and_reported(self):
        draft = self.draft()
        self.assertNotIn('step_3', [item['id'] for item in draft['execution']['actions']])
        self.assertTrue(any('Sound off' in note for note in draft['review']))

    def test_what_it_cannot_express_is_reported_not_guessed(self):
        self.assertTrue(any('not recorded' in note for note in self.draft(())['unsupported']))
        swipe = draft_path([{'step': 1, 'operation': 'SWIPE_UP', 'screen': {'text': 'x'}}], PKG)
        self.assertEqual(swipe['execution']['actions'], [])
        self.assertTrue(swipe['unsupported'])


class SetupFlagTests(unittest.TestCase):
    def saved(self, preconditions='Signed in; has a draft'):
        return {'preconditions': f'{preconditions}\n\n[generate-test-cases] ID: TC-1-01; Steps: from spec, confirm with exploration; Source: 0123456789abcdef'}

    def test_named_setup_is_flagged(self):
        self.assertEqual(setup_needed(self.saved()['preconditions']), 'Signed in; has a draft')
        self.assertEqual(setup_needed(self.saved('Video list is open')['preconditions']), '')

    def test_explored_case_must_enforce_named_setup(self):
        with self.assertRaisesRegex(ValueError, 'nothing enforces'):
            mark_explored(self.saved(), 'run-1')
        mark_explored(self.saved(), 'run-1', starting_conditions={'account_username': 'owner'})
        mark_explored(self.saved(), 'run-1', execution={'actions': [{'operation': 'REQUIRE'}]})
        mark_explored(self.saved('Video list is open'), 'run-1')


if __name__ == '__main__':
    unittest.main()
