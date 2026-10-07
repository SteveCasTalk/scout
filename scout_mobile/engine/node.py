"""Node contract for the run pipeline.

A node is one inspectable step of a run. It reads and writes a shared RunContext and
returns one of:
  None          continue with the next node in the stage
  NEXT_STEP     end this step-loop iteration (only valid in the 'step' stage)
  Finish(...)   end the run with a written result

A node may also be a generator: anything it yields is handed to the host (for example
an ``awaiting_input`` request) and the host's reply is sent back into the node.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import time
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from ..agent import Agent
    from ..device import Element, Screen

STAGES=('setup','step','teardown')
ROLES=('resource','perception','guard','decision','action','verification','reporting')


@dataclass(frozen=True)
class Finish:
    result:dict[str,Any]


class _NextStep:
    def __repr__(self)->str:return 'NEXT_STEP'

NEXT_STEP=_NextStep()
_CURRENT=object()


class Node:
    """Base class for pipeline nodes. Subclasses set the class attributes and implement run()."""
    name:ClassVar[str]=''
    stage:ClassVar[str]='step'
    role:ClassVar[str]='guard'
    summary:ClassVar[str]=''
    # Context fields this node reads / sets. Checked when the pipeline is assembled.
    requires:ClassVar[tuple[str,...]]=()
    provides:ClassVar[tuple[str,...]]=()
    # Locked nodes enforce safety or resource ownership and cannot be removed, replaced or disabled.
    locked:ClassVar[bool]=False

    def run(self,ctx:RunContext)->Any:
        raise NotImplementedError

    def describe(self)->dict[str,Any]:
        source=type(self)
        return {'name':self.name,'stage':self.stage,'role':self.role,'summary':self.summary,'requires':list(self.requires),'provides':list(self.provides),'locked':self.locked,'source':f'{source.__module__}:{source.__qualname__}'}

    def __repr__(self)->str:return f'<{type(self).__name__} {self.name}>'


@dataclass
class RunContext:
    """State shared between nodes. Run-wide services stay on the Agent; per-step state lives here."""
    agent:Agent
    screen:Screen|None=None
    goal:str=''
    first_step:int=1
    step:int=0
    # Per-step state, reset by begin_step().
    foreground:str=''
    loop_started:float=0.0
    public:dict[str,Any]|None=None
    tutorial_visible:bool=False
    decision:dict[str,Any]|None=None
    op:str=''
    selected:Element|None=None
    target:Element|None=None
    field_screen:Screen|None=None
    text_value:str|None=None
    action_started:float=0.0
    next_screen:Screen|None=None
    entry:dict[str,Any]=field(default_factory=dict)
    phases:dict[str,Any]=field(default_factory=dict)
    # Node-level audit for this run; written to pipeline.json at teardown.
    trace:list[dict[str,Any]]=field(default_factory=list)
    # Free-form storage for plugin nodes, keyed by node name.
    extras:dict[str,Any]=field(default_factory=dict)

    @property
    def device(self):return self.agent.device

    @property
    def config(self):return self.agent.config

    def begin_step(self,step:int)->None:
        self.step=step
        self.foreground='';self.loop_started=0.0;self.public=None;self.tutorial_visible=False
        self.decision=None;self.op='';self.selected=None;self.target=None;self.field_screen=None
        self.text_value=None;self.action_started=0.0;self.next_screen=None
        self.entry={};self.phases={}

    def finish(self,status:str,reason:str,screen:Any=_CURRENT)->Finish:
        """Write the run result. Defaults to the context's current screen."""
        return Finish(self.agent.write_result(status,reason,self.screen if screen is _CURRENT else screen))

    def ms_since(self,started:float)->int:
        return round((time.perf_counter()-started)*1000)
