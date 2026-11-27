"""Driver mode: the MCP host agent drives the device one action at a time; Scout runs no model.

The outer agent observes with `snapshot`, acts on a snapshot-qualified ref such as `@s1a2b3c4d:e3`, and reads the
returned snapshot. Scout keeps the hands and the safety: every action holds the device lease, re-observes before it
touches the device, resolves its ref strictly (fail closed, never guessed) and passes the same locked guards as the
run pipeline (app boundary, consent, consequential controls, credentials, iOS alerts, swipe instructions, repeats).

Ref resolution never uses bounds as identity:
  1. `@<snapshot>:eN` must parse and name a snapshot of this session (INVALID_ARGS / SNAPSHOT_NOT_FOUND / STALE_REF).
  2. When the fresh screen is identical to the snapshot (same fingerprint), the ref is the element at the same index.
  3. Otherwise a ref resolves only if it was unique at capture (AMBIGUOUS_TARGET) and exactly one fresh element has
     the same role, class, resource ID and label (STALE_REF when none, AMBIGUOUS_TARGET when several). Values,
     checked state and bounds are never identity.

Each session writes a normal run folder (`runner-output/<run_id>`): per-action screenshots, `trace.json`, and on
`end` a `result.json` with status Inconclusive (reason code `exploration_only`), plus a typed-path draft to review.
"""
from __future__ import annotations
import atexit
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock, RLock
from typing import Any

from .agent import Agent, RunConfig
from .config import ROOT
from .device import DeviceError, Element, Screen, TargetCovered
from .execution_runtime import ExecutionBlocked, check_text_entry
from .model import is_credential_field
from .safety import (CONSENT_GATE, CONSENT_WORD, CREDENTIAL_MANAGER, GUARD_TEXT, PRIVATE_CODE_FIELD, RISKY, SWIPE_INSTRUCTION,
                     known_credential_prompt)
from .skill_import import draft_path

SCHEMA_VERSION = 1
REF = re.compile(r'^@(s[0-9a-f]{10}):e([1-9]\d{0,3})$')
PACKAGE = re.compile(r'^[A-Za-z0-9_.-]{3,240}$')
SETTLE_SECONDS = {'TAP': 4.0, 'TYPE_TEXT': 4.0, 'CLEAR_TEXT': 2.0, 'BACK': 4.0, 'SWIPE': 1.5}
MAX_SNAPSHOTS = 16
FOCUS_SETTLE_SECONDS = 2.5
MAX_ACTIONS = 200
IDLE_SECONDS = 15 * 60
TEXT_LIMIT = 4000
# Billing and credential surfaces stay outside every session, whatever the host declares.
NEVER_ALLOWED = frozenset({'com.android.vending', CREDENTIAL_MANAGER, 'com.google.android.gms'})
DENY_LABEL = re.compile(r"(?:don[’']t allow|do not allow|deny|cancel|not now|later|許可しない|キャンセル)", re.I)


class DriverError(Exception):
    """A structured refusal or failure. `delivery` says whether input may have reached the device."""

    def __init__(self, code: str, message: str, suggestion: str = '', delivery: str = 'not_delivered',
                 retry: str = 'safe', details: dict[str, Any] | None = None, snapshot: dict[str, Any] | None = None):
        super().__init__(message)
        self.code, self.message, self.suggestion = code, message, suggestion
        self.delivery, self.retry, self.details, self.snapshot = delivery, retry, details or {}, snapshot

    def envelope(self, command: str) -> dict[str, Any]:
        error = {'code': self.code, 'message': self.message, 'suggestion': self.suggestion,
                 'disposition': {'delivery': self.delivery, 'retry': self.retry}}
        if self.details:error['details'] = self.details
        reply = {'version': SCHEMA_VERSION, 'ok': False, 'command': command, 'error': error}
        if self.snapshot is not None:reply['snapshot'] = self.snapshot
        return reply


def ok(command: str, data: dict[str, Any]) -> dict[str, Any]:
    return {'version': SCHEMA_VERSION, 'ok': True, 'command': command, 'data': data}


def identity(element: Element) -> tuple[str, str, str, str]:
    """What a ref means across observations. A text field's label can come from its value, so a field with a
    resource ID is identified without it."""
    label = '' if element.role == 'textbox' and element.resource_id else element.label
    return element.role, element.class_name, element.resource_id, label


@dataclass
class Snapshot:
    id: str
    screen: Screen
    foreground: str
    taken_ms: int
    # Index of each element among the elements sharing its identity, and how many share it.
    twins: dict[str, tuple[int, int]] = field(default_factory=dict)

    def element(self, number: int) -> Element | None:
        return self.screen.elements[number - 1] if 1 <= number <= len(self.screen.elements) else None


class DriverSession:
    def __init__(self, platform: str, package: str, serial: str, adb: str = 'adb', title: str = '',
                 allow_consent: bool = False, appium_url: str = '', allowed_packages: list[str] | None = None,
                 project: str = 'General', ticket_key: str = ''):
        if platform not in {'Android', 'iOS'}:raise DriverError('INVALID_ARGS', 'Platform must be Android or iOS.', retry='never')
        if not PACKAGE.fullmatch(package or ''):raise DriverError('INVALID_ARGS', 'package must be a valid app package or bundle ID.', retry='never')
        extra = list(dict.fromkeys(item.strip() for item in (allowed_packages or [])))
        if len(extra) > 5 or any(not PACKAGE.fullmatch(item) or item == package for item in extra):
            raise DriverError('INVALID_ARGS', 'allowed_packages takes up to 5 other valid package or bundle IDs.', retry='never')
        if any(item in NEVER_ALLOWED for item in extra):
            raise DriverError('INVALID_ARGS', 'Store checkout and credential managers can never be allowed packages.', retry='never')
        self.allowed_packages = extra
        project, ticket_key = (project or 'General').strip(), (ticket_key or '').strip().upper()
        if not 1 <= len(project) <= 100 or len(ticket_key) > 40:
            raise DriverError('INVALID_ARGS', 'project must be 1–100 characters and ticket_key at most 40.', retry='never')
        self.id = 'd' + secrets.token_hex(6)
        self.platform, self.package, self.serial = platform, package, serial
        output = ROOT / 'runner-output' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        case = {'id': 'driver-' + self.id, 'revision': 1, 'project': project, 'ticket_key': ticket_key, 'platform': platform, 'package': package,
                'app_id': package, 'title': (title or 'Driver-mode exploration').strip()[:160], 'suite': 'Driver sessions',
                'goal': 'Host-driven exploration; actions were chosen by the MCP host agent, not by Scout.',
                'preconditions': ('Allowed packages for this session: ' + ', '.join(extra)) if extra else ''}
        self.agent = Agent(RunConfig(package=package, serial=serial, test_case=case, output=output, adb=adb,
                                     platform=platform, allow_consent=allow_consent, mcp_host_text=True, appium_url=appium_url))
        self.device = self.agent.device
        self.snapshots: dict[str, Snapshot] = {}
        self.typed_texts: list[str] = []
        self.actions = 0
        self.last_used = time.monotonic()
        self.lock = RLock()
        self.ended: dict[str, Any] | None = None
        self.leased = False

    # ----- lifecycle -------------------------------------------------------------------------------------------

    @property
    def run_id(self) -> str:
        return self.agent.output.name

    def start(self, launch: bool = True) -> dict[str, Any]:
        try:
            self.agent.lease.acquire()
        except ExecutionBlocked as exc:
            raise DriverError('DEVICE_BUSY', str(exc), 'Wait for the other Scout run or session on this device to finish, or end it.') from None
        self.leased = True
        try:
            if not self.device.installed(self.package):
                raise DriverError('APP_NOT_INSTALLED', f'{self.package} is not installed on {self.serial}.', retry='never')
            if launch:
                self.device.launch(self.package)
                screen = self.device.wait_for_content(20)
            else:
                screen = self.device.observe()
            foreground = self.device.foreground()
            self._record({'operation': 'OBSERVE', 'note': 'session start' + (' after launch' if launch else '')}, screen, screen)
            return self._snapshot_data(self._take(screen, foreground))
        except BaseException:
            self.close('Session start failed.')
            raise

    def close(self, reason: str) -> dict[str, Any]:
        """Write the result, release the device and lease. Safe to call twice."""
        if self.ended is not None:return self.ended
        result: dict[str, Any] = {}
        try:
            self.agent.stop_code = 'exploration_only'
            note = f'Driver-mode exploration session: {self.actions} host-chosen action(s). {reason} This is exploration evidence, not a test verdict.'
            try:result = self.agent.write_result('Inconclusive', note, None)
            except (DeviceError, OSError, ValueError) as exc:result = {'status': 'Execution error', 'notes': f'Result could not be written: {exc}'}
        finally:
            self.agent.close_evidence()
            try:self.device.close()
            except Exception:pass
            if self.leased:self.agent.lease.release();self.leased = False
        typed = None
        if self.platform == 'Android':
            typed = self.typed_path()
        self.ended = {'session_id': self.id, 'run_id': self.run_id, 'status': result.get('status'), 'reason_code': result.get('reason_code'),
                      'actions': self.actions, 'steps': len(self.agent.history), 'typed_path': typed}
        return self.ended

    def typed_path(self) -> dict[str, Any]:
        draft = draft_path(self.agent.history, self.package, list(self.typed_texts))
        for entry in self.agent.history:
            if entry.get('operation') == 'TYPE_CREDENTIAL':
                draft['unsupported'].append(f"Step {entry['step']}: typed the local {entry.get('credential')} credential. Typed paths cannot type credentials; start the case signed in and add a REQUIRE step with require_account.")
            if entry.get('foreground') and entry['foreground'] != self.package and entry.get('operation') not in {None, 'OBSERVE'}:
                draft['review'].append(f"Step {entry['step']}: acted in {entry['foreground']}; declare it under external_flows before this path can run.")
            if entry.get('twins', 1) > 1:
                draft['review'].append(f"Step {entry['step']}: {entry.get('label')!r} had {entry['twins']} identical controls on screen; its selector is ambiguous until you narrow it.")
        return draft

    # ----- observation -----------------------------------------------------------------------------------------

    def _take(self, screen: Screen, foreground: str) -> Snapshot:
        snapshot = Snapshot('s' + secrets.token_hex(5), screen, foreground, self.agent.elapsed_ms())
        groups: dict[tuple, list[str]] = {}
        for element in screen.elements:groups.setdefault(identity(element), []).append(element.index)
        for members in groups.values():
            for position, index in enumerate(members):snapshot.twins[index] = (position, len(members))
        self.snapshots[snapshot.id] = snapshot
        while len(self.snapshots) > MAX_SNAPSHOTS:self.snapshots.pop(next(iter(self.snapshots)))
        return snapshot

    def _snapshot_data(self, snapshot: Snapshot, include_bounds: bool = False) -> dict[str, Any]:
        public = self.agent.public_screen(snapshot.screen)
        elements = []
        for element, shown in zip(snapshot.screen.elements, public['elements']):
            node: dict[str, Any] = {'ref': f'@{snapshot.id}:e{element.index}', 'role': element.role}
            if shown['label']:node['label'] = shown['label']
            if element.resource_id:node['id'] = element.resource_id
            if shown['value']:node['value'] = shown['value']
            states = [name for name, on in (('focused', element.focused), ('checked', element.checkable and element.checked),
                                            ('unchecked', element.checkable and not element.checked), ('disabled', not element.enabled),
                                            ('password', element.password)) if on]
            if states:node['states'] = states
            node['actions'] = list(element.operations)
            if snapshot.twins[element.index][1] > 1:node['twins'] = snapshot.twins[element.index][1]
            if include_bounds:node.update(bounds=list(element.bounds), class_name=element.class_name)
            elements.append(node)
        text = public['text']
        data = {'snapshot_id': snapshot.id, 'foreground': snapshot.foreground, 'in_app': self._in_app(snapshot.foreground, snapshot.screen),
                'screen': {'width': snapshot.screen.width, 'height': snapshot.screen.height}, 'fingerprint': snapshot.screen.fingerprint,
                'ref_count': len(elements), 'complete': len(elements) < 100, 'elements': elements,
                'text': text[:TEXT_LIMIT], 'text_truncated': len(text) > TEXT_LIMIT}
        if GUARD_TEXT in snapshot.screen.text:data['warning'] = 'The app rejected this device as an emulator.'
        return data

    def _in_app(self, foreground: str, screen: Screen) -> bool:
        if foreground and foreground in self.allowed_packages:return True
        if self.platform == 'iOS':return bool(self.device.permits_foreground(foreground, screen))
        return foreground == self.package

    def _fresh(self) -> tuple[Screen, str]:
        """Observe now, clearing a recognized Android save-password sheet the way the run pipeline does."""
        self.agent.flush_screenshots()
        screen, foreground = self.device.observe(), self.device.foreground()
        if self.platform == 'Android' and foreground == CREDENTIAL_MANAGER:
            cancel = next((e for e in screen.elements if e.label.casefold() == 'cancel' and 'TAP' in e.operations), None)
            if not known_credential_prompt(screen.text) or cancel is None:
                raise DriverError('CREDENTIAL_PROMPT', 'An unrecognized Android credential prompt is in front of the app.',
                                  'Ask the user to dismiss it on the device, then take a new snapshot.', retry='after_user_action')
            self.device.tap(cancel)
            following = self.device.wait_for_change(screen, 4)
            self._record({'operation': 'DISMISS_SAVED_PASSWORD'}, screen, following)
            screen, foreground = following, self.device.foreground()
        return screen, foreground

    def _require_in_app(self, screen: Screen, foreground: str) -> None:
        if not self._in_app(foreground, screen):
            raise DriverError('APP_BOUNDARY', f'The foreground app is {foreground or "unknown"}, not {self.package}; driver mode acts only inside the target app.',
                              'Use mobile_back to return, or end the session and start one whose allowed_packages declares this app if the user approves acting in it.',
                              snapshot=self._snapshot_data(self._take(screen, foreground)))

    # ----- refs ------------------------------------------------------------------------------------------------

    @staticmethod
    def parse_ref(ref: str | None) -> re.Match:
        match = REF.fullmatch(ref or '')
        if not match:
            raise DriverError('INVALID_ARGS', 'Refs look like @s1a2b3c4d5:e3 and come from a snapshot of this session.', 'Take a snapshot and use one of its refs.')
        return match

    def resolve(self, ref: str, screen: Screen, foreground: str) -> tuple[Element, Snapshot]:
        match = self.parse_ref(ref)
        snapshot = self.snapshots.get(match.group(1))
        if snapshot is None:
            raise DriverError('SNAPSHOT_NOT_FOUND', 'That snapshot is not part of this session (or is too old).', 'Take a new snapshot.')
        captured = snapshot.element(int(match.group(2)))
        if captured is None:
            raise DriverError('STALE_REF', 'That ref is not in its snapshot.', 'Take a new snapshot.')
        refreshed = lambda: self._snapshot_data(self._take(screen, foreground))
        if foreground != snapshot.foreground:
            raise DriverError('STALE_REF', 'The foreground app changed since that snapshot.', 'Use the refs in the attached snapshot.', snapshot=refreshed())
        if screen.fingerprint == snapshot.screen.fingerprint:
            same = screen.elements[int(captured.index) - 1] if int(captured.index) <= len(screen.elements) else None
            if same is not None and identity(same) == identity(captured):return same, snapshot
        position, count = snapshot.twins[captured.index]
        if count > 1:
            raise DriverError('AMBIGUOUS_TARGET', f'{count} identical controls matched this ref when it was captured, and the screen has changed since.',
                              'Use the refs in the attached snapshot right away.', details={'reason': 'identity_not_unique'}, snapshot=refreshed())
        live = [element for element in screen.elements if identity(element) == identity(captured)]
        if not live:
            raise DriverError('STALE_REF', 'The control is no longer on screen.', 'Use the refs in the attached snapshot.',
                              details={'reason': 'saved_ref_absent'}, snapshot=refreshed())
        if len(live) > 1:
            raise DriverError('AMBIGUOUS_TARGET', f'{len(live)} controls now match this ref.', 'Use the refs in the attached snapshot.',
                              details={'reason': 'saved_ref_ambiguous'}, snapshot=refreshed())
        return live[0], snapshot

    # ----- guards ----------------------------------------------------------------------------------------------

    def guard(self, operation: str, element: Element, screen: Screen) -> None:
        """The run pipeline's locked guards, applied to one host-chosen action."""
        agent = self.agent
        label = element.label
        if operation == 'TAP' and SWIPE_INSTRUCTION.search(screen.text):
            raise DriverError('SWIPE_INSTRUCTION', 'A swipe-up instruction is visible; the controls behind it may be covered.', 'Swipe up first (mobile_swipe direction=up).')
        if self.platform == 'iOS' and not agent.config.allow_consent and self.device.has_alert(screen) and not DENY_LABEL.fullmatch(label.strip()):
            raise DriverError('IOS_ALERT', 'An iOS system alert needs an explicit permission choice.', 'Ask the user; start the session with allow_consent only when they authorize accepting it.', retry='never')
        # Stricter than the pipeline's exact-label rule: the host picks every tap, so on a screen showing terms or
        # consent text, any agree/accept/continue-style control (including an "I have read and agree" checkbox) counts.
        consent = agent.consent_confirmation_required(label, screen.text) or bool(CONSENT_GATE.search(screen.text) and CONSENT_WORD.search(label))
        if consent and not agent.config.allow_consent:
            raise DriverError('CONSENT_REQUIRED', 'This is a legal or consent action; explicit user confirmation is required.',
                              'Ask the user; start a session with allow_consent=true only when they authorize accepting it.', retry='never')
        if RISKY.search(label):
            raise DriverError('CONSEQUENTIAL_CONTROL', f'Scout never touches purchase, transfer, subscription, withdrawal or account-deletion controls: {agent.redact(label)}', retry='never')
        if agent.repeated_without_progress(operation, element, screen):
            raise DriverError('NO_PROGRESS', f'{operation} on {agent.redact(label)!r} already produced no screen change.', 'Choose a different action or wait for the screen.', retry='never')

    # ----- actions ---------------------------------------------------------------------------------------------

    def _begin(self, ref: str | None = None, in_app: bool = True) -> tuple[Screen, str]:
        if self.ended is not None:raise DriverError('SESSION_ENDED', 'This session has ended.', 'Start a new session.', retry='never')
        if self.actions >= MAX_ACTIONS:raise DriverError('ACTION_LIMIT', f'A session allows {MAX_ACTIONS} actions.', 'End this session and start a new one.', retry='never')
        if ref is not None:self.parse_ref(ref)
        screen, foreground = self._fresh()
        if in_app:self._require_in_app(screen, foreground)
        return screen, foreground

    def _record(self, entry: dict[str, Any], before: Screen, after: Screen) -> dict[str, Any]:
        agent = self.agent
        step = len(agent.history)
        entry.update(step=step, driver=True, elapsed_ms=agent.elapsed_ms(), before_fingerprint=before.fingerprint,
                     after_fingerprint=after.fingerprint, page_changed=after.fingerprint != before.fingerprint,
                     screen=agent.public_screen(after), screenshot=agent.screenshot_deferred(after, step))
        agent.history.append(entry)
        agent._save_partial_trace()
        return entry

    def _dispatch(self, operation: str, before: Screen, entry: dict[str, Any], act) -> dict[str, Any]:
        try:
            act()
        except TargetCovered as exc:
            raise DriverError('TARGET_COVERED', str(exc), 'Scroll the control into view, then take a new snapshot.') from None
        except DriverError:
            raise
        except (DeviceError, ExecutionBlocked) as exc:
            # Input may have reached the app: record what is on screen now and never retry blindly.
            try:after = self.device.observe()
            except DeviceError:after = before
            self._record({**entry, 'error': self.agent.redact(str(exc))[:300]}, before, after)
            raise DriverError('DEVICE_ERROR', self.agent.redact(str(exc))[:500], 'Read the attached snapshot before acting again.', delivery='unknown',
                              retry='unsafe', snapshot=self._snapshot_data(self._take(after, self.device.foreground()))) from None
        self.actions += 1
        after = self.device.wait_for_change(before, SETTLE_SECONDS.get(operation, 4))
        recorded = self._record(entry, before, after)
        data = self._snapshot_data(self._take(after, self.device.foreground()))
        return {'step': recorded['step'], 'page_changed': recorded['page_changed'], 'screenshot': recorded['screenshot'], 'snapshot': data}

    def _element_entry(self, operation: str, element: Element, screen: Screen, ref: str) -> dict[str, Any]:
        twins = sum(identity(other) == identity(element) for other in screen.elements)
        return {'operation': operation, 'ref': ref, 'label': self.agent.redact(element.label), 'resource_id': element.resource_id,
                'class_name': element.class_name, 'target_bounds': list(element.bounds), 'twins': twins,
                'foreground': self.snapshots[self.parse_ref(ref).group(1)].foreground}

    def tap(self, ref: str) -> dict[str, Any]:
        screen, foreground = self._begin(ref)
        element, _ = self.resolve(ref, screen, foreground)
        if 'TAP' not in element.operations:
            hint = 'Use mobile_type for text fields.' if element.role == 'textbox' else 'This control is disabled or not tappable.'
            raise DriverError('UNSUPPORTED_ACTION', f'{element.role} does not support TAP.', hint, retry='never')
        self.guard('TAP', element, screen)
        return self._dispatch('TAP', screen, self._element_entry('TAP', element, screen, ref), lambda: self.device.tap(element, screen))

    def _focused_field(self, element: Element, screen: Screen) -> tuple[Element, Screen]:
        """On Android, focus the field first and confirm the intended field took focus (as the pipeline does)."""
        if self.platform == 'iOS' or element.focused:return element, screen
        self.device.tap(element, screen)
        # Focusing opens the keyboard, which can slide the field (a bottom sheet moves up). Use the field only once
        # two observations agree on its bounds; an earlier read would locate it where it no longer is.
        deadline, previous = time.monotonic() + FOCUS_SETTLE_SECONDS, None
        while True:
            focused_screen, foreground = self._fresh()
            self._require_in_app(focused_screen, foreground)
            focused = self.agent.focused_text_field(focused_screen, element)
            if focused is not None and previous is not None and focused.bounds == previous.bounds:break
            if time.monotonic() >= deadline:
                if focused is None:raise DeviceError('The intended text field did not gain focus.')
                break
            previous = focused
            time.sleep(.2)
        return focused, focused_screen

    def type(self, ref: str, text: str | None = None, credential: str | None = None) -> dict[str, Any]:
        if (text is None) == (credential is None):
            raise DriverError('INVALID_ARGS', 'Pass exactly one of text or credential.', retry='never')
        if credential is not None and credential not in {'email', 'password'}:
            raise DriverError('INVALID_ARGS', 'credential must be email or password.', retry='never')
        if text is not None and (not text.strip() or len(text) > 200):
            raise DriverError('INVALID_ARGS', 'text must be 1–200 characters.', retry='never')
        screen, foreground = self._begin(ref)
        element, _ = self.resolve(ref, screen, foreground)
        if 'TYPE_TEXT' not in element.operations:
            raise DriverError('UNSUPPORTED_ACTION', 'That control is not a text field.', retry='never')
        self.guard('TYPE_TEXT', element, screen)
        if credential is not None:
            provided = self.agent.credential_for(element, screen)
            if provided is None or provided[1] != credential:
                raise DriverError('CREDENTIAL_FIELD', f'This field was not recognized as the {credential} field.', 'Use the field the app labels for it.', retry='never')
            if not provided[0]:
                raise DriverError('CREDENTIAL_MISSING', f'SCOUT_TEST_{credential.upper()} is missing from the local .env.', 'Ask the user to add it to .env.', retry='never')
            value = provided[0]
            entry = {**self._element_entry('TYPE_CREDENTIAL', element, screen, ref), 'credential': credential, 'text_source': f'local {credential} credential'}
        else:
            if element.password or is_credential_field(element) or PRIVATE_CODE_FIELD.search(f'{element.label} {element.resource_id}'):
                raise DriverError('CREDENTIAL_FIELD', 'Credentials and private codes are never typed from host text.', 'Use credential=email or credential=password, which read the local provider.', retry='never')
            try:check_text_entry(self.agent, element, text)
            except ExecutionBlocked as exc:raise DriverError('CREDENTIAL_FIELD', str(exc), retry='never') from None
            value = text
            entry = {**self._element_entry('TYPE_TEXT', element, screen, ref), 'text': self.agent.redact(text), 'text_source': 'MCP host'}

        def act():
            field_element, _ = self._focused_field(element, screen)
            if credential is not None:self.agent.credential_used = True
            self.device.type_text(field_element, value)
            self._hide_keyboard()
        reply = self._dispatch('TYPE_TEXT', screen, entry, act)
        if credential is None:self.typed_texts.append(text)
        return reply

    def clear(self, ref: str) -> dict[str, Any]:
        screen, foreground = self._begin(ref)
        element, _ = self.resolve(ref, screen, foreground)
        if element.role != 'textbox':raise DriverError('UNSUPPORTED_ACTION', 'Only text fields can be cleared.', retry='never')
        self.guard('CLEAR_TEXT', element, screen)
        if not element.value:raise DriverError('NOTHING_TO_CLEAR', 'The field is already empty.', retry='never')
        return self._dispatch('CLEAR_TEXT', screen, self._element_entry('CLEAR_TEXT', element, screen, ref), lambda: self.device.clear_text(element))

    def swipe(self, direction: str, ref: str | None = None) -> dict[str, Any]:
        if direction not in {'up', 'down', 'left', 'right'}:raise DriverError('INVALID_ARGS', 'direction must be up, down, left or right.', retry='never')
        screen, foreground = self._begin(ref or None)
        if ref:
            element, _ = self.resolve(ref, screen, foreground)
            self.guard('SWIPE', element, screen)
            rect, (far, near) = element.bounds, (.85, .15)
            entry = {**self._element_entry('SWIPE', element, screen, ref), 'direction': direction}
        else:
            rect, (far, near) = (0, 0, screen.width, screen.height), (.75, .30)
            entry = {'operation': 'SWIPE_' + direction.upper(), 'direction': direction}
        x1, y1, x2, y2 = rect
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        points = {'up': (cx, int(y1 + (y2 - y1) * far), cx, int(y1 + (y2 - y1) * near)), 'down': (cx, int(y1 + (y2 - y1) * near), cx, int(y1 + (y2 - y1) * far)),
                  'left': (int(x1 + (x2 - x1) * far), cy, int(x1 + (x2 - x1) * near), cy), 'right': (int(x1 + (x2 - x1) * near), cy, int(x1 + (x2 - x1) * far), cy)}[direction]
        if points[:2] == points[2:]:raise DriverError('UNSUPPORTED_ACTION', 'The target is too small for this gesture.', retry='never')
        entry['gesture'] = {'start': list(points[:2]), 'end': list(points[2:]), 'duration_ms': 320}
        return self._dispatch('SWIPE', screen, entry, lambda: self.device.swipe_coordinates(*points, 320))

    def back(self) -> dict[str, Any]:
        # Back is the way home from a screen outside the app, so it is the one action allowed there.
        screen, foreground = self._begin(in_app=False)
        return self._dispatch('BACK', screen, {'operation': 'BACK', 'foreground': foreground}, self.device.back)

    def _hide_keyboard(self) -> None:
        """Close the keyboard only when it is showing; Android's fallback (Back) would otherwise navigate."""
        call = getattr(self.device, '_call', None)
        if call is None:return
        try:
            if call(lambda driver: driver.is_keyboard_shown()):call(lambda driver: driver.hide_keyboard())
        except DeviceError:
            pass

    def snapshot(self, include_bounds: bool = False) -> dict[str, Any]:
        if self.ended is not None:raise DriverError('SESSION_ENDED', 'This session has ended.', 'Start a new session.', retry='never')
        screen, foreground = self._fresh()
        return self._snapshot_data(self._take(screen, foreground), include_bounds)

    def find(self, query: str) -> dict[str, Any]:
        query = (query or '').strip()
        if not query or len(query) > 240:raise DriverError('INVALID_ARGS', 'query must be 1–240 characters.', retry='never')
        data = self.snapshot()
        needle = query.casefold()
        matches = [node for node in data['elements'] if needle in node.get('label', '').casefold() or needle in node.get('id', '').casefold()]
        return {'snapshot_id': data['snapshot_id'], 'query': query, 'matches': matches, 'in_page_text': needle in data['text'].casefold(),
                'foreground': data['foreground'], 'in_app': data['in_app']}

    def wait(self, text: str | None = None, absent_text: str | None = None, timeout_ms: int = 5000, poll_ms: int = 250) -> dict[str, Any]:
        if (bool(text and text.strip())) == (bool(absent_text and absent_text.strip())):
            raise DriverError('INVALID_ARGS', 'Pass exactly one of text or absent_text.', retry='never')
        if not 100 <= timeout_ms <= 60000 or not 50 <= poll_ms <= 5000:
            raise DriverError('INVALID_ARGS', 'timeout_ms must be 100–60000 and poll_ms 50–5000.', retry='never')
        if self.ended is not None:raise DriverError('SESSION_ENDED', 'This session has ended.', 'Start a new session.', retry='never')
        started = time.monotonic()
        deadline = started + timeout_ms / 1000
        polls = 0
        while True:
            screen, foreground = self._fresh()
            polls += 1
            seen = ' '.join([screen.text, *[e.label for e in screen.elements]]).casefold()
            met = (text.casefold() in seen) if text else (bool(seen.strip()) and absent_text.casefold() not in seen)
            if met or time.monotonic() >= deadline:
                data = self._snapshot_data(self._take(screen, foreground))
                waited = round((time.monotonic() - started) * 1000)
                if not met:
                    raise DriverError('TIMEOUT', f'The condition did not hold within {timeout_ms} ms.', 'Read the attached snapshot.',
                                      details={'waited_ms': waited, 'polls': polls}, snapshot=data)
                return {'waited_ms': waited, 'polls': polls, 'snapshot': data}
            time.sleep(poll_ms / 1000)

    def screenshot(self) -> tuple[str, bytes]:
        if self.ended is not None:raise DriverError('SESSION_ENDED', 'This session has ended.', 'Start a new session.', retry='never')
        screen, _ = self._fresh()
        step = len(self.agent.history)
        name = self.agent.screenshot(screen, step)
        if name is None:
            raise DriverError('SCREENSHOT_WITHHELD', 'This screen is withheld from evidence by the privacy policy (credential fields or values).', retry='never')
        self.agent.history.append({'step': step, 'driver': True, 'operation': 'OBSERVE', 'note': 'host screenshot', 'elapsed_ms': self.agent.elapsed_ms(),
                                   'screen': self.agent.public_screen(screen), 'screenshot': name, 'after_fingerprint': screen.fingerprint})
        self.agent._save_partial_trace()
        return name, (self.agent.output / name).read_bytes()


# ----- registry ------------------------------------------------------------------------------------------------

_SESSIONS: dict[str, DriverSession] = {}
_REGISTRY = Lock()


def _expire() -> None:
    now = time.monotonic()
    with _REGISTRY:
        idle = [s for s in _SESSIONS.values() if now - s.last_used > IDLE_SECONDS]
    for session in idle:
        with session.lock:session.close(f'Ended after {IDLE_SECONDS // 60} idle minutes.')
        with _REGISTRY:_SESSIONS.pop(session.id, None)


def start(platform: str, package: str, serial: str, adb: str = 'adb', title: str = '', allow_consent: bool = False, launch: bool = True,
          allowed_packages: list[str] | None = None, project: str = 'General', ticket_key: str = '') -> dict[str, Any]:
    _expire()
    try:
        session = DriverSession(platform, package, serial, adb, title, allow_consent, allowed_packages=allowed_packages,
                                project=project, ticket_key=ticket_key)
        snapshot = session.start(launch)
    except DriverError as exc:
        return exc.envelope('session_start')
    except (DeviceError, ValueError, OSError) as exc:
        return DriverError('DEVICE_ERROR', str(exc)[:500], 'Check the device and Appium setup (docs/appium-trial.md, docs/ios-appium.md).', retry='never').envelope('session_start')
    with _REGISTRY:_SESSIONS[session.id] = session
    return ok('session_start', {'session_id': session.id, 'run_id': session.run_id, 'platform': platform, 'package': package, 'device': serial,
                                'allow_consent': allow_consent, 'allowed_packages': session.allowed_packages, 'snapshot': snapshot})


def call(session_id: str, command: str, method: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
    _expire()
    with _REGISTRY:session = _SESSIONS.get(session_id)
    if session is None:
        return DriverError('SESSION_NOT_FOUND', 'No active driver session has that ID.', 'Start a session with mobile_session_start.', retry='never').envelope(command)
    with session.lock:
        session.last_used = time.monotonic()
        try:
            data = getattr(session, method)(*args, **kwargs)
        except DriverError as exc:
            return exc.envelope(command)
        except (DeviceError, OSError, ValueError) as exc:
            return DriverError('DEVICE_ERROR', session.agent.redact(str(exc))[:500], 'Take a new snapshot before acting again.', delivery='unknown', retry='unsafe').envelope(command)
    return ok(command, data)


def screenshot(session_id: str) -> tuple[str, bytes]:
    with _REGISTRY:session = _SESSIONS.get(session_id)
    if session is None:raise DriverError('SESSION_NOT_FOUND', 'No active driver session has that ID.', retry='never')
    with session.lock:
        session.last_used = time.monotonic()
        return session.screenshot()


def end(session_id: str) -> dict[str, Any]:
    with _REGISTRY:session = _SESSIONS.pop(session_id, None)
    if session is None:
        return DriverError('SESSION_NOT_FOUND', 'No active driver session has that ID.', retry='never').envelope('session_end')
    with session.lock:
        return ok('session_end', session.close('Ended by the host.'))


def sessions() -> list[dict[str, Any]]:
    _expire()
    with _REGISTRY:
        return [{'session_id': s.id, 'run_id': s.run_id, 'platform': s.platform, 'package': s.package, 'device': s.serial, 'actions': s.actions,
                 'idle_seconds': round(time.monotonic() - s.last_used)} for s in _SESSIONS.values()]


@atexit.register
def _close_all() -> None:
    with _REGISTRY:
        pending = list(_SESSIONS.values());_SESSIONS.clear()
    for session in pending:
        try:session.close('The MCP server stopped.')
        except Exception:pass
