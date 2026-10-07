"""Ordered, editable node graph that executes a run: setup → step loop → teardown."""
from __future__ import annotations
import inspect
import time
from typing import Any, Generator, Iterable
from .node import STAGES, ROLES, NEXT_STEP, Finish, Node, RunContext

# Context fields available before any node runs.
BASE_FIELDS=frozenset({'agent','trace','extras'})
# Fields begin_step() sets at the start of every step-loop iteration.
STEP_FIELDS=frozenset({'step'})


class PipelineError(ValueError):
    pass


class Pipeline:
    def __init__(self,nodes:Iterable[Node]=()):
        self._stages:dict[str,list[Node]]={stage:[] for stage in STAGES}
        for node in nodes:self.append(node)

    # ----- inspection -------------------------------------------------------
    def nodes(self,stage:str|None=None)->list[Node]:
        if stage:return list(self._stages[self._stage(stage)])
        return [node for name in STAGES for node in self._stages[name]]

    def get(self,name:str)->Node:
        for node in self.nodes():
            if node.name==name:return node
        raise PipelineError(f'No pipeline node named {name!r}.')

    def __contains__(self,name:object)->bool:
        return any(node.name==name for node in self.nodes())

    def describe(self)->dict[str,Any]:
        return {stage:[node.describe() for node in self._stages[stage]] for stage in STAGES}

    def validate(self)->None:
        """Fail closed when a node reads a context field that no earlier node provides."""
        available=set(BASE_FIELDS)
        for stage in ('setup','step'):
            if stage=='step':available|=STEP_FIELDS
            for node in self._stages[stage]:
                missing=[name for name in node.requires if name not in available]
                if missing:
                    raise PipelineError(f'Node {node.name!r} requires {", ".join(missing)}, which no earlier node provides.')
                available.update(node.provides)

    # ----- editing ----------------------------------------------------------
    def append(self,node:Node)->Pipeline:
        self._check_new(node)
        self._stages[node.stage].append(node)
        return self

    def insert(self,node:Node,*,before:str|None=None,after:str|None=None)->Pipeline:
        if (before is None)==(after is None):raise PipelineError('Insert needs exactly one of before= or after=.')
        self._check_new(node)
        anchor=self.get(before or after)
        if anchor.stage!=node.stage:
            raise PipelineError(f'Node {node.name!r} is a {node.stage} node; {anchor.name!r} is in {anchor.stage}.')
        nodes=self._stages[node.stage]
        position=nodes.index(anchor)+(0 if before else 1)
        nodes.insert(position,node)
        return self

    def replace(self,name:str,node:Node)->Pipeline:
        current=self._editable(name)
        if node.name!=name and node.name in self:raise PipelineError(f'A node named {node.name!r} already exists.')
        if node.stage!=current.stage:raise PipelineError(f'Replacement for {name!r} must be a {current.stage} node.')
        self._validate_node(node)
        nodes=self._stages[current.stage]
        nodes[nodes.index(current)]=node
        return self

    def remove(self,name:str)->Pipeline:
        node=self._editable(name)
        self._stages[node.stage].remove(node)
        return self

    def _editable(self,name:str)->Node:
        node=self.get(name)
        if node.locked:raise PipelineError(f'Node {name!r} is locked: it enforces safety or resource ownership.')
        return node

    def _check_new(self,node:Node)->None:
        self._validate_node(node)
        if node.name in self:raise PipelineError(f'A node named {node.name!r} already exists.')

    @staticmethod
    def _validate_node(node:Node)->None:
        if not isinstance(node,Node):raise PipelineError(f'{node!r} is not a pipeline Node.')
        if not node.name:raise PipelineError(f'{type(node).__name__} has no name.')
        if node.stage not in STAGES:raise PipelineError(f'Node {node.name!r} has unknown stage {node.stage!r}.')
        if node.role not in ROLES:raise PipelineError(f'Node {node.name!r} has unknown role {node.role!r}.')

    @staticmethod
    def _stage(stage:str)->str:
        if stage not in STAGES:raise PipelineError(f'Unknown stage {stage!r}.')
        return stage

    # ----- execution --------------------------------------------------------
    def run(self,ctx:RunContext)->Generator[Any,Any,dict[str,Any]]:
        """Run setup and the step loop. Teardown is separate so callers can own their try/finally."""
        for node in self._stages['setup']:
            out=yield from self._call(node,ctx)
            if isinstance(out,Finish):return out.result
            if out is NEXT_STEP:raise PipelineError(f'Setup node {node.name!r} cannot end a step.')
        agent=ctx.agent
        for step in range(ctx.first_step,ctx.first_step+agent.config.max_steps):
            ctx.begin_step(step)
            for node in self._stages['step']:
                out=yield from self._call(node,ctx)
                if isinstance(out,Finish):return out.result
                if out is NEXT_STEP:break
        return agent.write_result('Inconclusive',f'Maximum {agent.config.max_steps} actions reached without a verified outcome.',ctx.screen)

    def teardown(self,ctx:RunContext)->None:
        """Run every teardown node even if one fails, then re-raise the first failure."""
        failure:BaseException|None=None
        for node in self._stages['teardown']:
            try:
                out=node.run(ctx)
                if inspect.isgenerator(out):raise PipelineError(f'Teardown node {node.name!r} cannot suspend.')
                self._record(ctx,node,'next',0.0)
            except BaseException as exc:
                self._record(ctx,node,'error:'+type(exc).__name__,0.0)
                if failure is None:failure=exc
        if failure is not None:raise failure

    def _call(self,node:Node,ctx:RunContext)->Generator[Any,Any,Any]:
        started=time.perf_counter()
        outcome='error'
        try:
            out=node.run(ctx)
            if inspect.isgenerator(out):out=yield from out
            outcome='finish' if isinstance(out,Finish) else 'next_step' if out is NEXT_STEP else 'next'
            if out is not None and outcome=='next':
                raise PipelineError(f'Node {node.name!r} returned {out!r}; expected None, NEXT_STEP or Finish.')
            return out
        except BaseException as exc:
            outcome='error:'+type(exc).__name__
            raise
        finally:
            self._record(ctx,node,outcome,started)

    @staticmethod
    def _record(ctx:RunContext,node:Node,outcome:str,started:float)->None:
        ctx.trace.append({'stage':node.stage,'step':ctx.step if node.stage=='step' else None,'node':node.name,'outcome':outcome,'duration_ms':round((time.perf_counter()-started)*1000) if started else 0})
