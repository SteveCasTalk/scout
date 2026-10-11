"""Decision agent and terminal operations (DONE / BLOCKED).

``decide`` is the replaceable agent slot: a plugin can swap it for another decision
agent as long as the replacement sets ``decision``, ``op``, ``selected``, ``public`` and
``loop_started`` on the context. The decision dict carries ``operation``, ``target``,
``confidence``, ``model``, ``latency_ms`` and ``jev`` (the audit payload).
"""
from __future__ import annotations
import json
import time
from ... import model
from ..node import Node, RunContext


class JevDecision(Node):
    name='decide';role='decision'
    summary='Ask the Jev model to choose one operation and observed target for the current screen.'
    provides=('decision','op','selected','public','loop_started')
    def run(self,ctx:RunContext):
        agent=ctx.agent;screen=ctx.screen
        ctx.public=agent.public_screen(screen)
        ctx.loop_started=time.perf_counter()
        goal=ctx.goal
        if agent.checkpoints:
            goal+='\nVerification checkpoints: '+json.dumps([{'id':item['id'],'expected':item['expected'],'scope':item['scope'],'required':item['required'],'verdict':item['verdict']} for item in agent.checkpoint_verdicts.values()],ensure_ascii=False)+'\nDo not revisit already satisfied during_run checkpoints. Final checkpoints are assessed when you declare DONE; finish navigation at their intended screen. Unknown verification is not permission to repeat completed actions.'
        ctx.decision=self.choose(agent,screen.elements,ctx.public['text'],goal,agent.history,platform=agent.platform)
        ctx.op=ctx.decision['operation']
        ctx.selected=next((e for e in screen.elements if e.index==ctx.decision['target']),None)

    def choose(self,agent,*args,**kwargs):
        return agent.decide(*args,**kwargs)


class LLMDecision(JevDecision):
    """Same options, rules and guards as Jev; a general chat LLM (TEXT_MODEL) makes the choice."""
    summary='Ask a general chat LLM (TEXT_MODEL, or SCOUT_DECISION_MODEL) to choose the operation and target.'
    def choose(self,agent,*args,**kwargs):
        return model.choose_llm(*args,**kwargs)


DECISION_AGENTS={'jev':JevDecision,'llm':LLMDecision}


class RecordDecision(Node):
    name='record_decision';role='reporting';locked=True
    summary='Build the redacted trace entry and phase timings for this step.'
    requires=('decision','selected')
    provides=('entry','phases')
    def run(self,ctx:RunContext):
        agent=ctx.agent;decision=ctx.decision;selected=ctx.selected
        ctx.phases={'decision_ms':decision['latency_ms']}
        ctx.entry={'step':ctx.step,'elapsed_ms':agent.elapsed_ms(),'operation':ctx.op,'target':decision['target'],'label':agent.redact(selected.label) if selected else None,'resource_id':selected.resource_id if selected else None,'confidence':decision['confidence'],'model':decision['model'],'latency_ms':decision['latency_ms'],'before_fingerprint':ctx.screen.fingerprint,'jev':agent.redact_object(decision['jev']),'timings_ms':ctx.phases}


class Done(Node):
    name='done';role='verification';locked=True
    summary='On DONE, re-observe and let checkpoints or the visible-text assertion decide the result.'
    requires=('entry','phases','loop_started')
    def run(self,ctx:RunContext):
        if ctx.op!='DONE':return None
        agent=ctx.agent;phases=ctx.phases;entry=ctx.entry;step=ctx.step
        started=time.perf_counter()
        final=agent.device.observe()
        if agent.boundary:agent.boundary.check(agent.device.foreground(),final)
        phases['final_observe_ms']=ctx.ms_since(started)
        phases['final_observation']=agent.device_timing_details('last_observation_timings')
        entry['screen']=agent.public_screen(final)
        started=time.perf_counter()
        entry['screenshot']=agent.screenshot(final,step)
        phases['screenshot_ms']=ctx.ms_since(started)
        phases['step_total_ms']=ctx.ms_since(ctx.loop_started)
        agent.history.append(entry)
        matched=agent.verify_result(final,step+1)
        expected=agent.config.expected_text.strip()
        if agent.checkpoints:return ctx.finish(agent.checkpoint_outcome(),'Checkpoint verification completed.',final)
        if matched:return ctx.finish('Passed',f'Exact visible-text assertion passed: {expected}',final)
        if not expected:return ctx.finish('Inconclusive','The agent declared DONE, but this case has no exact visible-text assertion.',final)
        return ctx.finish('Failed',f'Exact visible-text assertion failed. Expected on screen: {expected}',final)


class Blocked(Node):
    name='blocked';role='verification';locked=True
    summary='On BLOCKED, report a platform limitation as Blocked, otherwise Inconclusive.'
    requires=('entry',)
    def run(self,ctx:RunContext):
        if ctx.op!='BLOCKED':return None
        agent=ctx.agent
        agent.history.append(ctx.entry)
        if agent.platform=='iOS':
            limitation=agent.device.limitation_reason(ctx.screen)
            if limitation:return ctx.finish('Blocked',limitation)
        return ctx.finish('Inconclusive','The agent could not progress using observed controls.')
