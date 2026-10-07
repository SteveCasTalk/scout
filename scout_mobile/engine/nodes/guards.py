"""Step-stage guards: checks that run before or around each decision and may stop the run."""
from __future__ import annotations
import re
import time
from ...safety import CREDENTIAL_MANAGER, DATE_OF_BIRTH_GATE, GUARD_TEXT, RISKY, SWIPE_INSTRUCTION, known_credential_prompt
from ..node import NEXT_STEP, Node, RunContext

ELEMENT_OPS=frozenset({'TAP','TYPE_TEXT','SET_VALUE'})


def dismiss_credential_prompt(ctx:RunContext,prompt,check_boundary:bool=False):
    """Cancel a recognized Android save-password sheet and return the following screen, or None if unrecognized."""
    agent=ctx.agent
    cancel=next((e for e in prompt.elements if e.label.casefold()=='cancel' and 'TAP' in e.operations),None)
    if not known_credential_prompt(prompt.text) or not cancel:return None
    agent.flush_screenshots()
    if agent.boundary:
        if check_boundary:agent.boundary.check(agent.device.foreground(),prompt)
        agent.boundary.authorize('TAP',cancel)
    agent.device.tap(cancel)
    return agent.device.wait_for_change(prompt,4)


# ----- before the decision ---------------------------------------------------

class StopRequest(Node):
    name='stop_request';role='guard';locked=True
    summary='Honor a stop request from the dashboard or MCP host before the next action.'
    def run(self,ctx:RunContext):
        if ctx.config.should_stop and ctx.config.should_stop():
            return ctx.finish('Inconclusive','Stopped by the dashboard before the next action.')
        return None


class TimeLimit(Node):
    name='time_limit';role='guard';locked=True
    summary='Stop with an execution error once the run time limit is exceeded.'
    def run(self,ctx:RunContext):
        agent=ctx.agent
        limit=agent.execution['timeout_seconds'] if agent.execution else agent.config.timeout_seconds
        if time.monotonic()-agent.started>limit:
            return ctx.finish('Execution error','Runner time limit reached.')
        return None


class ObserveForeground(Node):
    name='foreground';role='perception';locked=True
    summary='Read the foreground app and, under a declared app boundary, re-observe and check it.'
    provides=('foreground',)
    def run(self,ctx:RunContext):
        agent=ctx.agent
        ctx.foreground=agent.device.foreground()
        if agent.boundary:
            ctx.screen=agent.device.observe()
            agent.boundary.check(ctx.foreground,ctx.screen)


class CredentialPrompt(Node):
    name='credential_prompt';role='guard';locked=True
    summary='Dismiss a recognized Android save-password prompt; stop on an unrecognized one.'
    requires=('foreground',)
    def run(self,ctx:RunContext):
        if ctx.foreground!=CREDENTIAL_MANAGER:return None
        agent=ctx.agent
        prompt=agent.device.observe()
        following=dismiss_credential_prompt(ctx,prompt)
        if following is None:
            return ctx.finish('Execution error','An unrecognized Android credential prompt interrupted the app.',prompt)
        ctx.screen=following
        agent.history.append({'step':ctx.step,'elapsed_ms':agent.elapsed_ms(),'operation':'DISMISS_SAVED_PASSWORD','screen':agent.public_screen(following),'screenshot':agent.screenshot(following,ctx.step)})
        return NEXT_STEP


class AppBoundary(Node):
    name='app_boundary';role='guard';locked=True
    summary='Stop when the run has left the target app without an approved external flow.'
    requires=('foreground',)
    def run(self,ctx:RunContext):
        agent=ctx.agent;foreground=ctx.foreground
        if agent.platform=='iOS':
            ctx.screen=agent.device.observe()
            if not agent.device.permits_foreground(foreground,ctx.screen):
                return ctx.finish('Blocked',f'External iOS flow requires a configured app boundary: foreground is {foreground or "unknown"}. Return to the target app before resuming.')
        elif not agent.boundary and foreground and foreground!=agent.config.package:
            return ctx.finish('Execution error',f'App left the allowed package; foreground is {foreground}.')
        return None


class DateGate(Node):
    name='date_gate';role='action'
    summary='Complete a date-of-birth gate once with its preselected value; never guess a date.'
    requires=('foreground',)
    def run(self,ctx:RunContext):
        agent=ctx.agent
        if agent.boundary and ctx.foreground!=agent.config.package:return None
        gate_screen=agent._base_date_gate_step(ctx.screen)
        if gate_screen is None:return None
        if DATE_OF_BIRTH_GATE.search(gate_screen.text):
            return ctx.finish('Inconclusive','Date submission did not leave the date gate; stopped without retrying.',gate_screen)
        ctx.screen=gate_screen
        return NEXT_STEP


class CycleDetector(Node):
    name='cycle_detector';role='guard'
    summary='Stop after a navigation cycle repeats three times without checkpoint progress.'
    def run(self,ctx:RunContext):
        cycle=ctx.agent.recent_screen_cycle(ctx.screen)
        if cycle:
            return ctx.finish('Inconclusive',f'Stopped after detecting a repeated {cycle}-screen navigation cycle without assertion progress.')
        return None


class TutorialGuard(Node):
    name='tutorial_guard';role='guard';locked=True
    summary='Detect a visible swipe-up instruction; stop if the instructed swipe already failed.'
    provides=('tutorial_visible',)
    def run(self,ctx:RunContext):
        ctx.tutorial_visible=bool(SWIPE_INSTRUCTION.search(ctx.screen.text))
        if ctx.tutorial_visible and ctx.agent.instruction_swipe_attempted:
            return ctx.finish('Inconclusive','The instructed upward swipe did not advance the screen; stopped before tapping covered controls.')
        return None


# ----- after the decision ----------------------------------------------------

class TutorialGesture(Node):
    name='tutorial_gesture';role='guard';locked=True
    summary='While a swipe-up instruction is visible, allow only the instructed gesture.'
    requires=('tutorial_visible','op')
    def run(self,ctx:RunContext):
        if not ctx.tutorial_visible:return None
        if ctx.op!='SWIPE_UP':
            return ctx.finish('Inconclusive','An upward-swipe instruction is visible; stopped before tapping covered controls because its required gesture was not selected.')
        ctx.agent.instruction_swipe_attempted=True
        return None


class AuthorizeGesture(Node):
    name='authorize_gesture';role='guard';locked=True
    summary='Under a declared app boundary, re-check and authorize non-element operations.'
    requires=('op','selected')
    def run(self,ctx:RunContext):
        agent=ctx.agent
        if agent.boundary and ctx.op not in ELEMENT_OPS:
            ctx.screen=agent.device.observe();agent.boundary.check(agent.device.foreground(),ctx.screen);agent.boundary.authorize(ctx.op,ctx.selected)


class IOSAlertGuard(Node):
    name='ios_alert_guard';role='guard';locked=True
    summary='On an iOS system alert, allow only deny-style choices unless consent is authorized.'
    requires=('entry','selected')
    def run(self,ctx:RunContext):
        agent=ctx.agent;selected=ctx.selected
        if agent.platform!='iOS' or not selected or agent.config.allow_consent or not agent.device.has_alert(ctx.screen):return None
        deny=re.fullmatch(r"(?:don[’']t allow|do not allow|deny|cancel|not now|later|許可しない|キャンセル)",selected.label.strip(),re.I)
        if deny:return None
        agent.history.append(ctx.entry)
        return ctx.finish('Blocked','iOS alert requires an explicit permission choice. Authorize this run before accepting the prompt.')


class ConsentGuard(Node):
    name='consent_guard';role='guard';locked=True
    summary='Stop before legal or consent actions unless the run explicitly authorizes consent.'
    requires=('entry','selected','public')
    def run(self,ctx:RunContext):
        agent=ctx.agent;selected=ctx.selected
        if ctx.op in ELEMENT_OPS and selected and agent.consent_confirmation_required(selected.label,ctx.public['text']) and not agent.config.allow_consent:
            ctx.entry['blocked_by_safety']='explicit user confirmation required for a legal or consent action'
            agent.history.append(ctx.entry)
            return ctx.finish('Inconclusive','Stopped before a legal or consent action. Explicit user confirmation is required to proceed.')
        return None


class ConsequentialControlGuard(Node):
    name='consequential_control_guard';role='guard';locked=True
    summary='Never touch purchase, transfer, subscription, withdrawal, or account-deletion controls.'
    requires=('entry','selected')
    def run(self,ctx:RunContext):
        selected=ctx.selected
        if selected and RISKY.search(selected.label):
            ctx.agent.history.append(ctx.entry)
            return ctx.finish('Execution error',f'Runner stopped before a consequential control: {selected.label}')
        return None


class RepeatGuard(Node):
    name='repeat_guard';role='guard';locked=True
    summary='Stop before repeating an element action that previously produced no screen change.'
    requires=('entry','selected')
    def run(self,ctx:RunContext):
        agent=ctx.agent;selected=ctx.selected;op=ctx.op
        if op in ELEMENT_OPS and selected and agent.repeated_without_progress(op,selected,ctx.screen):
            ctx.entry['blocked_by_safety']='same action repeated without an observable screen change'
            agent.history.append(ctx.entry)
            return ctx.finish('Inconclusive',f'Stopped before repeating {op} on {selected.label!r}; the prior action produced no observable screen change.')
        return None


class EmulatorGuard(Node):
    name='emulator_guard';role='guard';locked=True
    summary='Stop when the app rejects this device as an emulator after an action.'
    def run(self,ctx:RunContext):
        if GUARD_TEXT in ctx.screen.text:
            return ctx.finish('Execution error','The app rejected this emulator before authentication.')
        return None

