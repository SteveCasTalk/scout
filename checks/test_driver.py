"""Driver-mode contract checks with synthetic screens and a fake device; no connected device or model is used."""
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scout_mobile import driver
from scout_mobile.device import DeviceError, Element, Screen
from scout_mobile.skill_import import draft_path

PACKAGE = 'com.example.app'
PNG = b'\x89PNG\r\n\x1a\nfake'


def element(index, label, resource_id='', bounds=(0, 0, 100, 50), role='button', cls='android.widget.Button', value='', focused=False, password=False):
    operations = ('TYPE_TEXT',) if role == 'textbox' else ('TAP',)
    return Element(str(index), role, label, resource_id, cls, value, bounds, operations, role == 'textbox' or password, password, focused)


def screen(*elements, text=''):
    items = [element(i + 1, *spec[0], **spec[1]) for i, spec in enumerate(elements)]
    text = text or ' · '.join(e.label for e in items)
    digest = hashlib.sha256(json.dumps([text, [(e.label, e.bounds, e.value, e.focused) for e in items]]).encode()).hexdigest()[:16]
    return Screen('<hierarchy/>', items, text, digest, 1080, 2400)


def button(label, resource_id='', bounds=(0, 0, 100, 50)):
    return ((label, resource_id, bounds), {})


def field(label, resource_id='', bounds=(0, 200, 1000, 300), value='', focused=True, password=False):
    return ((label, resource_id, bounds), {'role': 'textbox', 'cls': 'android.widget.EditText', 'value': value, 'focused': focused, 'password': password})


class FakeDevice:
    backend = 'appium'
    platform = 'Android'
    session_start_ms = 0

    def __init__(self, first):
        self.current, self.queue, self.calls, self.package, self.fail = first, [], [], PACKAGE, None

    def _advance(self, name, *args):
        self.calls.append((name, *args))
        if self.fail:raise self.fail
        if self.queue:self.current = self.queue.pop(0)

    def observe(self, retries=2):
        self.observations = getattr(self, 'observations', 0) + 1
        return self.current
    def foreground(self):return self.package
    def installed(self, package):return package == PACKAGE
    def launch(self, package):self.calls.append(('launch', package))
    def wait_for_content(self, timeout=20):return self.current
    def wait_for_change(self, previous, timeout=4):return self.current
    def tap(self, target, screen=None):self._advance('tap', target)
    def type_text(self, target, value):self._advance('type_text', target, value)
    def clear_text(self, target):self._advance('clear_text', target);return 'appium'
    def swipe_coordinates(self, *args):self._advance('swipe', *args)
    def back(self):self._advance('back')
    def screenshot(self, path):Path(path).write_bytes(PNG)
    def command(self, *args, **kwargs):raise DeviceError('no adb in tests')
    def close(self):self.calls.append(('close',))


class DriverTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        for target in ('scout_mobile.driver.ROOT', 'scout_mobile.device_lease.ROOT'):
            patcher = patch(target, self.root);patcher.start();self.addCleanup(patcher.stop)
        env = patch.dict(os.environ, {'SCOUT_TEST_EMAIL': 'tester@example.com', 'SCOUT_TEST_PASSWORD': 'Secret-123'})
        env.start();self.addCleanup(env.stop)
        self.addCleanup(self.end_all)

    def end_all(self):
        for item in driver.sessions():driver.end(item['session_id'])

    def start(self, first, serial='fake-1', allow_consent=False, allowed_packages=None, **extra):
        fake = FakeDevice(first)
        original = driver.DriverSession.__init__

        def init(session, *args, **kwargs):
            original(session, *args, **kwargs)
            session.agent.device = session.device = fake
        with patch.object(driver.DriverSession, '__init__', init):
            reply = driver.start('Android', PACKAGE, serial, allow_consent=allow_consent, allowed_packages=allowed_packages, **extra)
        return reply, fake

    def ref(self, reply, label):
        snapshot = reply['data']['snapshot'] if 'snapshot' in reply['data'] else reply['data']
        return next(node['ref'] for node in snapshot['elements'] if node.get('label') == label)

    def test_start_returns_snapshot_qualified_refs_and_rejects_bare_refs(self):
        reply, fake = self.start(screen(button('Continue', 'app:id/continue')))
        self.assertTrue(reply['ok'])
        ref = self.ref(reply, 'Continue')
        self.assertRegex(ref, r'^@s[0-9a-f]{10}:e1$')
        self.assertIn(('launch', PACKAGE), fake.calls)
        bare = driver.call(reply['data']['session_id'], 'tap', 'tap', '@e1')
        self.assertFalse(bare['ok'])
        self.assertEqual(bare['error']['code'], 'INVALID_ARGS')
        self.assertEqual(bare['error']['disposition'], {'delivery': 'not_delivered', 'retry': 'safe'})

    def test_tap_on_unchanged_screen_dispatches_and_returns_new_snapshot(self):
        first = screen(button('Continue', 'app:id/continue'))
        reply, fake = self.start(first)
        fake.queue.append(screen(button('Done', 'app:id/done')))
        session = reply['data']['session_id']
        tapped = driver.call(session, 'tap', 'tap', self.ref(reply, 'Continue'))
        self.assertTrue(tapped['ok'], tapped)
        self.assertEqual(fake.calls[-1][0], 'tap')
        self.assertTrue(tapped['data']['page_changed'])
        self.assertEqual(self.ref(tapped, 'Done').split(':')[1], 'e1')
        self.assertNotEqual(tapped['data']['snapshot']['snapshot_id'], reply['data']['snapshot']['snapshot_id'])

    def test_moved_control_resolves_by_identity_never_by_bounds(self):
        reply, fake = self.start(screen(button('Banner'), button('Continue', 'app:id/continue', (0, 900, 100, 950))))
        ref = self.ref(reply, 'Continue')
        fake.current = screen(button('Continue', 'app:id/continue', (0, 300, 100, 350)))
        tapped = driver.call(reply['data']['session_id'], 'tap', 'tap', ref)
        self.assertTrue(tapped['ok'], tapped)
        self.assertEqual(fake.calls[-1][1].bounds, (0, 300, 100, 350))

    def test_missing_control_is_stale_and_nothing_is_tapped(self):
        reply, fake = self.start(screen(button('Continue', 'app:id/continue')))
        ref = self.ref(reply, 'Continue')
        fake.current = screen(button('Other', 'app:id/other'))
        refused = driver.call(reply['data']['session_id'], 'tap', 'tap', ref)
        self.assertEqual(refused['error']['code'], 'STALE_REF')
        self.assertEqual(refused['error']['details']['reason'], 'saved_ref_absent')
        self.assertIn('snapshot', refused)
        self.assertFalse(any(call[0] == 'tap' for call in fake.calls))

    def test_twins_resolve_only_on_an_identical_screen(self):
        twins = screen(button('Add', 'app:id/add', (0, 0, 100, 50)), button('Add', 'app:id/add', (0, 100, 100, 150)))
        reply, fake = self.start(twins)
        refs = [node['ref'] for node in reply['data']['snapshot']['elements']]
        self.assertEqual(reply['data']['snapshot']['elements'][1]['twins'], 2)
        fake.queue.append(screen(button('Add', 'app:id/add', (0, 0, 100, 50)), button('Add', 'app:id/add', (0, 100, 100, 150)), text='Added'))
        tapped = driver.call(reply['data']['session_id'], 'tap', 'tap', refs[1])
        self.assertTrue(tapped['ok'], tapped)
        self.assertEqual(fake.calls[-1][1].bounds, (0, 100, 100, 150))
        refused = driver.call(reply['data']['session_id'], 'tap', 'tap', refs[0])  # The screen changed since refs were taken.
        self.assertEqual(refused['error']['code'], 'AMBIGUOUS_TARGET')

    def test_locked_guards_refuse_consequential_and_consent_controls(self):
        reply, fake = self.start(screen(button('Buy now'), button('I agree'), text='Terms of Service · Buy now · I agree'))
        session = reply['data']['session_id']
        self.assertEqual(driver.call(session, 'tap', 'tap', self.ref(reply, 'Buy now'))['error']['code'], 'CONSEQUENTIAL_CONTROL')
        consent = driver.call(session, 'tap', 'tap', self.ref(reply, 'I agree'))
        self.assertEqual(consent['error']['code'], 'CONSENT_REQUIRED')
        self.assertEqual(consent['error']['disposition']['retry'], 'never')
        self.assertFalse(any(call[0] == 'tap' for call in fake.calls))
        driver.end(session)
        allowed, fake = self.start(screen(button('I agree'), text='Terms of Service · I agree'), allow_consent=True)
        self.assertTrue(driver.call(allowed['data']['session_id'], 'tap', 'tap', self.ref(allowed, 'I agree'))['ok'])

    def test_consent_variants_found_on_device_are_refused(self):
        # Twomi's terms screen (2026-11-27): "Agree & continue" was tapped because only "and" was recognized.
        terms = ('A few things to know · I have read and agree to the Terms of Use and Privacy Policy, and consent to the '
                 'processing of my personal data. · Agree & continue')
        reply, fake = self.start(screen(button('I have read and agree to the Terms of Use and Privacy Policy, and consent to the processing of my personal data.'),
                                        button('Agree & continue'), text=terms))
        session = reply['data']['session_id']
        for label in ('Agree & continue', 'I have read and agree to the Terms of Use and Privacy Policy, and consent to the processing of my personal data.'):
            refused = driver.call(session, 'tap', 'tap', self.ref(reply, label))
            self.assertEqual(refused['error']['code'], 'CONSENT_REQUIRED', label)
        self.assertFalse(any(call[0] == 'tap' for call in fake.calls))

    def test_actions_outside_the_target_app_are_refused(self):
        reply, fake = self.start(screen(button('Continue')))
        fake.package = 'com.android.settings'
        refused = driver.call(reply['data']['session_id'], 'tap', 'tap', self.ref(reply, 'Continue'))
        self.assertEqual(refused['error']['code'], 'APP_BOUNDARY')
        self.assertFalse(refused['snapshot']['in_app'])

    def test_lock_screen_over_the_app_is_outside_the_app(self):
        # Samsung lock screen (2026-11-27): Appium still reported the app as foreground, and its PIN field is a password
        # field, so credential=password would have typed the account password into the device lock screen.
        pin = ((('<credential field>', 'com.android.systemui:id/pinEntry', (0, 600, 1080, 760)),
                {'role': 'textbox', 'cls': 'android.widget.EditText', 'focused': True, 'password': True}))
        reply, fake = self.start(screen(pin, button('1', 'com.android.systemui:id/key1'), text='Enter PIN · 1'))
        self.assertFalse(reply['data']['snapshot']['in_app'])
        session = reply['data']['session_id']
        ref = reply['data']['snapshot']['elements'][0]['ref']
        refused = driver.call(session, 'type', 'type', ref, None, 'password')
        self.assertEqual(refused['error']['code'], 'APP_BOUNDARY')
        self.assertIn('System UI', refused['error']['message'])
        self.assertFalse(any(call[0] in {'tap', 'type_text'} for call in fake.calls))

    def test_back_is_the_one_action_allowed_outside_the_app(self):
        reply, fake = self.start(screen(button('Search')))
        session = reply['data']['session_id']
        fake.package = 'com.example.helper'
        fake.queue.append(screen(button('Search')))
        self.assertEqual(driver.call(session, 'tap', 'tap', self.ref(reply, 'Search'))['error']['code'], 'APP_BOUNDARY')
        back = driver.call(session, 'back', 'back')
        self.assertTrue(back['ok'], back)
        self.assertEqual(fake.calls[-1], ('back',))

    def test_bare_ref_is_rejected_before_the_device_is_touched(self):
        reply, fake = self.start(screen(button('Search')))
        before = getattr(fake, 'observations', 0)
        self.assertEqual(driver.call(reply['data']['session_id'], 'tap', 'tap', '@e1')['error']['code'], 'INVALID_ARGS')
        self.assertEqual(getattr(fake, 'observations', 0), before)

    def test_declared_helper_package_is_allowed_and_recorded_in_the_draft(self):
        reply, fake = self.start(screen(button('Search settings')), allowed_packages=['com.example.helper'])
        session = reply['data']['session_id']
        self.assertEqual(reply['data']['allowed_packages'], ['com.example.helper'])
        fake.queue.append(screen(field('Search', 'helper:id/query')))
        tapped = driver.call(session, 'tap', 'tap', self.ref(reply, 'Search settings'))
        fake.package = 'com.example.helper'
        snap = driver.call(session, 'snapshot', 'snapshot')
        self.assertTrue(snap['data']['in_app'])
        fake.queue.append(screen(field('Search', 'helper:id/query', value='wifi'), text='wifi'))
        self.assertTrue(driver.call(session, 'type', 'type', self.ref(snap, 'Search'), 'wifi', None)['ok'])
        draft = driver.end(session)['data']['typed_path']
        self.assertEqual([a['package'] for a in draft['execution']['actions']], [PACKAGE, 'com.example.helper'])
        self.assertTrue(any('external_flows' in line for line in draft['review']))

    def test_store_and_credential_packages_can_never_be_allowed(self):
        refused, _ = self.start(screen(button('Search')), allowed_packages=['com.android.vending'])
        self.assertEqual(refused['error']['code'], 'INVALID_ARGS')

    def test_credentials_come_only_from_the_local_provider(self):
        reply, fake = self.start(screen(field('Email', 'app:id/email'), field('Password', 'app:id/password', (0, 400, 1000, 500), password=True)))
        session = reply['data']['session_id']
        typed = driver.call(session, 'type', 'type', self.ref(reply, 'Email'), 'tester@example.com', None)
        self.assertEqual(typed['error']['code'], 'CREDENTIAL_FIELD')
        wrong_kind = driver.call(session, 'type', 'type', self.ref(reply, 'Email'), None, 'password')
        self.assertEqual(wrong_kind['error']['code'], 'CREDENTIAL_FIELD')
        ok = driver.call(session, 'type', 'type', self.ref(reply, 'Email'), None, 'email')
        self.assertTrue(ok['ok'], ok)
        self.assertEqual(fake.calls[-1], ('type_text', fake.calls[-1][1], 'tester@example.com'))
        ended = driver.end(session)['data']
        trace = (self.root / 'runner-output' / ended['run_id'] / 'trace.json').read_text()
        self.assertNotIn('tester@example.com', trace)
        self.assertNotIn('Secret-123', trace)
        self.assertTrue(any('credential' in line for line in ended['typed_path']['unsupported']))

    def test_typing_waits_for_a_field_that_slides_when_the_keyboard_opens(self):
        # Twomi's comment sheet (2026-11-27): focusing moved the field up while it was being located.
        unfocused = screen(field('Write a comment', bounds=(208, 2063, 872, 2198), focused=False))
        reply, fake = self.start(unfocused)
        moving = [screen(field('Write a comment', bounds=(208, 1500, 872, 1635))), screen(field('Write a comment', bounds=(208, 1190, 872, 1325)))]
        settled = screen(field('Write a comment', bounds=(208, 1190, 872, 1325)))
        frames = iter([unfocused] + moving + [settled] * 10)
        fake.observe = lambda retries=2: next(frames)
        typed = driver.call(reply['data']['session_id'], 'type', 'type', self.ref(reply, 'Write a comment'), 'hello', None)
        self.assertTrue(typed['ok'], typed)
        name, target, value = fake.calls[-1]
        self.assertEqual((name, target.bounds, value), ('type_text', (208, 1190, 872, 1325), 'hello'))

    def test_end_writes_exploration_result_releases_lease_and_drafts_typed_path(self):
        reply, fake = self.start(screen(button('Search', 'app:id/search'), field('Query', 'app:id/query', value='')))
        session = reply['data']['session_id']
        fake.queue.append(screen(button('Search', 'app:id/search'), field('Query', 'app:id/query', value='shoes'), text='Search · shoes'))
        self.assertTrue(driver.call(session, 'type', 'type', self.ref(reply, 'Query'), 'shoes', None)['ok'])
        snap = driver.call(session, 'snapshot', 'snapshot')
        fake.queue.append(screen(button('Results for shoes', 'app:id/results')))
        self.assertTrue(driver.call(session, 'tap', 'tap', self.ref(snap, 'Search'))['ok'])
        busy, _ = self.start(screen(button('Other')))
        self.assertEqual(busy['error']['code'], 'DEVICE_BUSY')
        ended = driver.end(session)
        self.assertTrue(ended['ok'])
        result = json.loads((self.root / 'runner-output' / ended['data']['run_id'] / 'result.json').read_text())
        self.assertEqual(result['status'], 'Inconclusive')
        self.assertEqual(result['reason_code'], 'exploration_only')
        actions = ended['data']['typed_path']['execution']['actions']
        self.assertEqual([(a['operation'], a['selector']) for a in actions], [('TYPE_TEXT', {'resource_id': 'app:id/query'}), ('TAP', {'resource_id': 'app:id/search'})])
        self.assertEqual(actions[0]['text'], 'shoes')
        again, _ = self.start(screen(button('Other')))
        self.assertTrue(again['ok'], 'The lease must be released when a session ends.')

    def test_device_failure_mid_action_is_reported_as_possibly_delivered(self):
        reply, fake = self.start(screen(button('Continue')))
        fake.fail = DeviceError('Appium command failed (WebDriverException); no ADB fallback was attempted.')
        failed = driver.call(reply['data']['session_id'], 'tap', 'tap', self.ref(reply, 'Continue'))
        self.assertEqual(failed['error']['code'], 'DEVICE_ERROR')
        self.assertEqual(failed['error']['disposition'], {'delivery': 'unknown', 'retry': 'unsafe'})

    def test_wait_returns_when_text_appears_and_times_out_with_snapshot(self):
        reply, fake = self.start(screen(button('Loading')))
        session = reply['data']['session_id']
        timed_out = driver.call(session, 'wait', 'wait', 'Welcome', None, 200, 50)
        self.assertEqual(timed_out['error']['code'], 'TIMEOUT')
        self.assertIn('snapshot', timed_out)
        fake.current = screen(button('Welcome back'))
        self.assertTrue(driver.call(session, 'wait', 'wait', 'welcome', None, 200, 50)['ok'])

    def test_project_and_ticket_file_the_session_for_dashboard_sync(self):
        reply, _ = self.start(screen(button('Continue')), project='Twomi', ticket_key='ca-5861')
        ended = driver.end(reply['data']['session_id'])['data']
        result = json.loads((self.root / 'runner-output' / ended['run_id'] / 'result.json').read_text())
        self.assertEqual((result['project'], result['ticket_key'], result['suite']), ('Twomi', 'CA-5861', 'Driver sessions'))
        self.assertTrue(result['case_id'].startswith('driver-'))  # The bridge lists driver- and prompt- runs for sync.

    def test_named_account_replaces_the_default_credentials(self):
        with patch.dict(os.environ, {'SCOUT_ACCOUNT_QA_OWNER_EMAIL': 'owner@example.com', 'SCOUT_ACCOUNT_QA_OWNER_PASSWORD': 'Owner-456'}):
            reply, fake = self.start(screen(field('Email', 'app:id/email')), account='qa_owner')
        self.assertEqual(reply['data']['account'], 'qa_owner')
        session = reply['data']['session_id']
        self.assertTrue(driver.call(session, 'type', 'type', self.ref(reply, 'Email'), None, 'email')['ok'])
        self.assertEqual(fake.calls[-1][2], 'owner@example.com')
        ended = driver.end(session)['data']
        evidence = ''.join(p.read_text() for p in (self.root / 'runner-output' / ended['run_id']).glob('*.json'))
        self.assertNotIn('owner@example.com', evidence)
        missing, _ = self.start(screen(button('Other')), account='nobody')
        self.assertEqual(missing['error']['code'], 'ACCOUNT_NOT_CONFIGURED')

    def test_account_from_the_prompt_is_used_for_this_session_only(self):
        reply, fake = self.start(screen(field('Email', 'app:id/email')), test_email='prompt.user@example.com', test_password='Prompt-789')
        self.assertTrue(reply['ok'], reply)
        self.assertEqual(reply['data']['account'], 'from prompt')
        self.assertNotIn('prompt.user@example.com', json.dumps(reply))
        session = reply['data']['session_id']
        self.assertTrue(driver.call(session, 'type', 'type', self.ref(reply, 'Email'), None, 'email')['ok'])
        self.assertEqual(fake.calls[-1][2], 'prompt.user@example.com')
        ended = driver.end(session)['data']
        evidence = ''.join(p.read_text() for p in (self.root / 'runner-output' / ended['run_id']).glob('*.json'))
        self.assertNotIn('prompt.user@example.com', evidence)
        self.assertNotIn('Prompt-789', evidence)

    def test_prefilled_email_field_is_recognized_for_the_credential(self):
        # Twomi after logout (2026-11-27): the email field kept the previous account's address, so its label was
        # '<editable field>' and credential=email was refused.
        prefilled = (('<editable field>', '', (0, 200, 1000, 300)), {'role': 'textbox', 'cls': 'android.widget.EditText',
                                                                     'value': 'previous.user@example.com', 'focused': True})
        reply, fake = self.start(screen(prefilled, text='Login or Register · Your email · Next'),
                                 test_email='prompt.user@example.com', test_password='Prompt-789')
        typed = driver.call(reply['data']['session_id'], 'type', 'type', reply['data']['snapshot']['elements'][0]['ref'], None, 'email')
        self.assertTrue(typed['ok'], typed)
        self.assertEqual(fake.calls[-1][2], 'prompt.user@example.com')

    def test_prompt_account_needs_both_values_and_excludes_a_named_account(self):
        half, _ = self.start(screen(button('Other')), test_email='prompt.user@example.com')
        self.assertEqual(half['error']['code'], 'INVALID_ARGS')
        self.assertNotIn('prompt.user@example.com', json.dumps(half))
        both, _ = self.start(screen(button('Other')), test_email='prompt.user@example.com', test_password='Prompt-789', account='qa_owner')
        self.assertEqual(both['error']['code'], 'INVALID_ARGS')

    def test_unknown_session_and_ended_session(self):
        self.assertEqual(driver.call('dmissing', 'snapshot', 'snapshot')['error']['code'], 'SESSION_NOT_FOUND')


class SavedRunPromptAccountTests(unittest.TestCase):
    def test_bridge_keeps_the_prompt_account_out_of_files_and_signature_and_hands_it_to_the_job(self):
        import threading, uuid
        from unittest.mock import Mock
        from scout_mobile import library_sessions as module
        case = {'id': str(uuid.uuid4()), 'revision': 1, 'title': 'Login', 'goal': 'Log in', 'steps': 'Log in', 'expected': 'Home',
                'app_id': PACKAGE, 'platform': 'Android'}
        client = Mock(); client.url = 'http://localhost:5173'; client.request.return_value = {'cases': [case]}
        base = {'dashboard_url': client.url, 'workspace_id': str(uuid.uuid4()), 'cases': [{'id': case['id'], 'revision': 1}],
                'serial': 'synthetic', 'conditions_confirmed': True, 'client_capabilities': {'contract_versions': [1, 2], 'features': []}}
        request_id = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as folder, patch.object(module, 'STORE', Path(folder)), \
                patch.object(module, 'DashboardClient', return_value=client), patch.object(module, 'connected', return_value=['synthetic']), \
                patch.object(module.threading, 'Thread') as thread:
            sessions = module.Sessions(); lock = threading.Lock()
            first = sessions.start({**base, 'request_id': request_id, 'test_account': {'email': 'prompt.user@example.com', 'password': 'Prompt-789'}}, lock)
            # Credentials are not part of the request identity: the same start without them is the same session.
            again = sessions.start({**base, 'request_id': request_id}, lock)
            self.assertEqual(first['session_id'], again['session_id'])
            saved = next(Path(folder).glob('*.json')).read_text()
            self.assertNotIn('prompt.user@example.com', saved); self.assertNotIn('Prompt-789', saved)
            self.assertNotIn('prompt.user@example.com', json.dumps(first))
            self.assertEqual(first['account_source'], 'prompt')
            session = sessions.items[first['session_id']]
            started = []
            with patch.object(module.dashboard_jobs, 'start', side_effect=lambda payload, _lock: started.append(payload) or (_ for _ in ()).throw(ValueError('stop here'))):
                try:sessions.worker(session, [case], client, 'current', 40, False, lock)
                except Exception:pass
            self.assertEqual(started[0]['_account'], ('prompt.user@example.com', 'Prompt-789'))
            thread.assert_called_once()

    def test_dashboard_job_requests_cannot_inject_an_account(self):
        import threading, uuid
        from scout_mobile import dashboard_jobs
        case = {'id': str(uuid.uuid4()), 'revision': 1, 'goal': 'Log in', 'steps': 'Log in', 'expected': 'Home', 'app_id': PACKAGE, 'platform': 'Android'}
        # A JSON request can only produce a list, never the in-process tuple a saved-library session hands over.
        with patch.object(dashboard_jobs, 'connected', return_value=['synthetic']):
            with self.assertRaisesRegex(ValueError, 'Invalid run account'):
                dashboard_jobs.start({'case': case, 'serial': 'synthetic', 'conditions_confirmed': True, '_account': ['a@example.com', 'x']}, threading.Lock())


class ConsentPatternTests(unittest.TestCase):
    def test_pipeline_rule_recognizes_ampersand_and_plus_joins(self):
        from scout_mobile.agent import Agent
        terms = 'Please accept the Terms of Use and Privacy Policy'
        for label in ('Agree & continue', 'Agree and continue', 'Agree + Continue', 'Accept & continue', 'Continue & accept'):
            self.assertTrue(Agent.consent_confirmation_required(label, terms), label)
        self.assertFalse(Agent.consent_confirmation_required('Agree & continue', 'Choose a video to watch'))


class TextInputClassTests(unittest.TestCase):
    def test_edit_text_subclasses_are_text_fields(self):
        import xml.etree.ElementTree as ET
        from scout_mobile.device import AndroidDevice
        xml = ('<hierarchy><node text="Search" resource-id="app:id/search_src_text" class="android.widget.AutoCompleteTextView" '
               'clickable="true" enabled="true" focused="true" bounds="[0,0][900,120]"/></hierarchy>')
        device = AndroidDevice('fake')
        device._screen_size, device._screen_size_read_at, device.screen_size_cache_seconds = (1080, 2400), float('inf'), float('inf')
        parsed = device._parse(ET.fromstring(xml), xml).elements[0]
        self.assertEqual((parsed.role, parsed.operations), ('textbox', ('TYPE_TEXT',)))


class HintOnlyFieldTests(unittest.TestCase):
    def test_a_field_showing_only_its_hint_is_typed_without_clearing(self):
        from unittest.mock import Mock
        from scout_mobile.appium_device import AppiumAndroidDevice
        filled = ('<hierarchy><node text="{}" resource-id="app:id/q" class="android.widget.AutoCompleteTextView" clickable="true" '
                  'enabled="true" focused="true" bounds="[0,0][900,120]"/></hierarchy>')
        device = AppiumAndroidDevice('fake')
        driver_mock = Mock()
        driver_mock.get_window_size.return_value = {'width': 1080, 'height': 2400}
        state = {'text': 'Search'}
        driver_mock.page_source = filled.format('Search')
        target = Mock()
        target.get_attribute.side_effect = lambda name: 'Search' if name == 'hint' else state['text']

        def send_keys(value):
            state['text'] = value
            driver_mock.page_source = filled.format(value)
        target.send_keys.side_effect = send_keys
        driver_mock.find_elements.return_value = [target]
        device._driver = driver_mock
        empty = device.observe().elements[0]
        self.assertEqual(empty.value, 'Search')  # Page source reports the hint as text.
        self.assertEqual(device.clear_text(empty), 'hint only')
        device.type_text(empty, 'wifi')
        target.clear.assert_not_called()
        target.send_keys.assert_called_once_with('wifi')
        self.assertEqual(device.last_text_entry, {'clear': 'hint only'})
        self.assertFalse(device._shows_hint(device.observe().elements[0]))  # Real text is never mistaken for a hint.


class DraftPathTests(unittest.TestCase):
    def test_targeted_swipe_and_clear_become_typed_actions_and_failures_are_left_out(self):
        trace = [
            {'step': 0, 'operation': 'OBSERVE', 'screen': {'text': 'Home'}},
            {'step': 1, 'operation': 'SWIPE', 'label': 'Gallery', 'resource_id': 'app:id/pager', 'direction': 'left', 'screen': {'text': 'Home · Slide 2'}},
            {'step': 2, 'operation': 'CLEAR_TEXT', 'label': 'Query', 'resource_id': 'app:id/query', 'screen': {'text': 'Home'}},
            {'step': 3, 'operation': 'TAP', 'label': 'Save', 'resource_id': 'app:id/save', 'error': 'Appium command failed', 'screen': {'text': 'Home'}},
            {'step': 4, 'operation': 'SWIPE_UP', 'screen': {'text': 'Home'}},
        ]
        draft = draft_path(trace, PACKAGE)
        actions = draft['execution']['actions']
        self.assertEqual([a['operation'] for a in actions], ['SWIPE', 'CLEAR_TEXT'])
        self.assertEqual(actions[0]['direction'], 'left')
        self.assertEqual(draft['execution']['required_capabilities'], ['target_gestures', 'text_entry'])
        self.assertTrue(any('failed' in line for line in draft['review']))
        self.assertTrue(any('SWIPE_UP' in line for line in draft['unsupported']))


if __name__ == '__main__':
    unittest.main()
