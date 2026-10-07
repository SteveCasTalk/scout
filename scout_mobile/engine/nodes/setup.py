"""Setup stage: acquire resources, launch the app, and check the run may proceed."""
from __future__ import annotations
import json
import re
import time
from ...safety import GUARD_TEXT
from ...starting_conditions import check_starting_conditions
from ..node import Node, RunContext


class AcquireDeviceLease(Node):
    name='device_lease';stage='setup';role='resource';locked=True
    summary='Take the per-device OS lock so only one controller drives the device.'
    def run(self,ctx:RunContext):
        ctx.agent.lease.acquire()


class StartSandbox(Node):
    name='sandbox';stage='setup';role='resource';locked=True
    summary='Start the network sandbox when the case declares fixtures.'
    def run(self,ctx:RunContext):
        agent=ctx.agent
        if not agent.config.test_case.get('sandbox'):return None
        from ...sandbox import Session
        try:
            fixture=agent.config.test_case['sandbox']
            if any(secret in json.dumps(fixture) for secret in agent.secrets):
                raise ValueError('Sandbox fixtures must not contain locally configured credentials. Use synthetic values.')
            agent.sandbox_session=Session(fixture,agent.output,run_origin=agent.started)
            agent.sandbox_session.start()
        except (ValueError,OSError) as exc:
            return ctx.finish('Blocked','Sandbox prerequisite missing: '+str(exc),None)
        return None


class CheckAppInstalled(Node):
    name='app_installed';stage='setup';role='guard';locked=True
    summary='Block the run when the target package or bundle is not installed.'
    def run(self,ctx:RunContext):
        agent=ctx.agent
        if agent.device.installed(agent.config.package):return None
        agent.starting_condition_results=[{'kind':'app_installed','expected':agent.config.package,'actual':'Not installed','status':'missing','reason':'The required app package is not installed on this device.','observed_step':0}]
        agent.history.append({'step':0,'elapsed_ms':agent.elapsed_ms(),'operation':'CHECK_STARTING_CONDITIONS','starting_condition_results':agent.starting_condition_results,'screenshot':None})
        return ctx.finish('Blocked','Starting conditions blocked: required app package is not installed.',None)


class PrepareLifecycle(Node):
    name='lifecycle_prepare';stage='setup';role='resource';locked=True
    summary='Apply declared lifecycle setup (resets, permissions) for deterministic executions.'
    def run(self,ctx:RunContext):
        if ctx.agent.lifecycle:ctx.agent.lifecycle.prepare()


class LaunchApp(Node):
    name='launch_app';stage='setup';role='perception'
    summary='Launch the app, wait for content, and record the opening observation.'
    provides=('screen',)
    def run(self,ctx:RunContext):
        agent=ctx.agent;device=agent.device
        started=time.perf_counter()
        device.launch(agent.config.package)
        launch_ms=ctx.ms_since(started)
        started=time.perf_counter()
        ctx.screen=screen=device.wait_for_content(20)
        wait_for_content_ms=ctx.ms_since(started)
        started=time.perf_counter()
        initial=agent.screenshot(screen,0)
        initial_screenshot_ms=ctx.ms_since(started)
        agent.history.append({'step':0,'elapsed_ms':agent.elapsed_ms(),'operation':'OBSERVE','screen':agent.public_screen(screen),'screenshot':initial,'timings_ms':{'launch_ms':launch_ms,'wait_for_content_ms':wait_for_content_ms,'content_wait':agent.device_timing_details('last_content_wait_timings'),'screenshot_ms':initial_screenshot_ms,'last_observation':agent.device_timing_details('last_observation_timings')}})


class CheckStartingConditions(Node):
    name='starting_conditions';stage='setup';role='guard';locked=True
    summary='Block when declared app version, account, login state, or data prerequisites are not observed.'
    requires=('screen',)
    def run(self,ctx:RunContext):
        agent=ctx.agent;screen=ctx.screen;conditions=agent.starting_conditions
        if not (conditions['app_version'] or conditions['account'] or conditions['login_state']!='any' or conditions['required_data']):return None
        info=agent.capture_device_info()
        public=agent.public_screen(screen)
        agent.starting_condition_results=agent.redact_object(check_starting_conditions(conditions,screen,info,agent.test_email,agent.redact(str(agent.config.test_case.get('goal',''))),public['text'],public['elements']))
        agent.history[0]['starting_condition_results']=agent.starting_condition_results
        if agent.config.on_progress:agent.config.on_progress(agent.history)
        missing=[item for item in agent.starting_condition_results if item['status']!='met']
        if missing:
            return ctx.finish('Blocked','Starting conditions blocked: '+'; '.join(item['kind']+' — '+item['reason'] for item in missing))
        return None


class InitialCheckpoints(Node):
    name='initial_checkpoints';stage='setup';role='verification'
    summary='Assess checkpoints against the opening screen.'
    requires=('screen',)
    def run(self,ctx:RunContext):
        ctx.agent.assess_checkpoints(ctx.screen,0)
        if ctx.config.on_progress:ctx.config.on_progress(ctx.agent.history)


class InitialEmulatorGuard(Node):
    name='emulator_guard_initial';stage='setup';role='guard';locked=True
    summary='Stop when the app rejects this device as rooted or emulated before authentication.'
    requires=('screen',)
    def run(self,ctx:RunContext):
        if GUARD_TEXT in ctx.screen.text:
            return ctx.finish('Execution error','The app blocks rooted devices and emulators before authentication. Use a permitted physical device or emulator-enabled UAT build.')
        return None


class DeterministicExecution(Node):
    name='deterministic_execution';stage='setup';role='action';locked=True
    summary='Run the declared deterministic execution protocol and, for verify-only finishes, decide the result.'
    requires=('screen',)
    def run(self,ctx:RunContext):
        agent=ctx.agent
        if not agent.execution:return None
        agent.boundary.check(agent.device.foreground(),ctx.screen)
        ctx.screen=screen=agent.protocol.run()
        if agent.execution['finish']!='verify':return None
        from ...media_verification import verify_metadata
        media=verify_metadata(agent.output,agent.execution['media_assertions'])
        agent.protocol.results.extend(media);agent.protocol.save()
        matched=agent.verify_result(screen,len(agent.history))
        status=agent.checkpoint_outcome() if agent.checkpoints else ('Passed' if matched else 'Failed' if agent.config.expected_text else 'Inconclusive')
        temporal=agent.protocol.outcome()
        required_media=[r for r in media if r['required']]
        extra_required=any(r['required'] for r in agent.execution['temporal_assertions']) or bool(required_media)
        if not agent.checkpoints and not agent.config.expected_text and extra_required:status='Passed'
        if temporal=='Failed' or any(r['verdict']=='violated' for r in required_media):status='Failed'
        elif status!='Failed' and (temporal=='Inconclusive' or any(r['verdict']!='satisfied' for r in required_media)):status='Inconclusive'
        return ctx.finish(status,'Deterministic execution completed; supplemental evidence is recorded independently.')


class VerificationOnly(Node):
    name='verification_only';stage='setup';role='verification'
    summary='For step-less verify/confirm/check goals, assert on the opening screen without acting.'
    requires=('screen',)
    def run(self,ctx:RunContext):
        agent=ctx.agent;case=agent.config.test_case;screen=ctx.screen
        goal_text=str(case.get('goal','')).strip()
        assertion=agent.config.expected_text.strip()
        if str(case.get('steps','')).strip() or not re.match(r'^(verify|confirm|check|observe)\b',goal_text,re.I):return None
        matched=agent.verify_result(screen,1,{'verification_only':1})
        if agent.checkpoints:return ctx.finish(agent.checkpoint_outcome(),'Checkpoint verification completed.')
        if matched:return ctx.finish('Passed',f'Exact visible-text assertion passed: {assertion}')
        if assertion:return ctx.finish('Failed',f'Exact visible-text assertion failed. Expected on screen: {assertion}')
        return ctx.finish('Inconclusive','This verification case has no exact visible-text assertion.')


class ComposeGoal(Node):
    name='compose_goal';stage='setup';role='decision';locked=True
    summary='Build the redacted goal prompt and the first step number for the step loop.'
    provides=('goal','first_step')
    def run(self,ctx:RunContext):
        agent=ctx.agent;case=agent.config.test_case
        ctx.goal=agent.redact(f"{case.get('goal','')}\nSteps:\n{case.get('steps','')}\nExpected:\n{case.get('expected','')}")
        ctx.first_step=max((entry['step'] for entry in agent.history),default=0)+1 if agent.execution else 1
