"""Assemble the run pipeline from built-in nodes plus installed or configured plugins.

A plugin is a callable ``plugin(pipeline) -> None`` that edits the pipeline in place,
for example ``pipeline.insert(MyNode(), after='settle')`` or
``pipeline.replace('decide', MyDecisionAgent())``. Plugins are found from:

  * the ``scout.pipeline`` entry-point group of installed packages
  * ``SCOUT_PIPELINE_PLUGINS``: comma-separated ``module:callable`` references

``SCOUT_DECISION_AGENT`` picks the built-in decision agent (``jev`` default, or ``llm``).
``SCOUT_DISABLED_NODES`` removes unlocked nodes by name. Locked nodes enforce safety
or resource ownership and refuse removal or replacement. Plugin errors fail closed.
"""
from __future__ import annotations
from importlib import import_module
from importlib.metadata import entry_points
from typing import Callable
from ..config import getenv
from .nodes import DEFAULT_NODES
from .nodes.decide import DECISION_AGENTS
from .pipeline import Pipeline, PipelineError

ENTRY_POINT_GROUP='scout.pipeline'
Plugin=Callable[[Pipeline],None]


def default_pipeline()->Pipeline:
    return Pipeline(node() for node in DEFAULT_NODES)


def _reference(value:str)->tuple[str,Plugin]:
    module,_,attribute=value.strip().partition(':')
    if not module or not attribute:raise PipelineError(f'Pipeline plugin {value!r} must be module:callable.')
    try:target=import_module(module)
    except ImportError as exc:raise PipelineError(f'Pipeline plugin {value!r} could not be imported: {exc}') from None
    for part in attribute.split('.'):
        target=getattr(target,part,None)
        if target is None:raise PipelineError(f'Pipeline plugin {value!r} was not found.')
    return value.strip(),target


def discover_plugins()->list[tuple[str,Plugin]]:
    plugins=[]
    for point in sorted(entry_points(group=ENTRY_POINT_GROUP),key=lambda point:point.name):
        try:plugins.append((f'{point.name} ({point.value})',point.load()))
        except Exception as exc:raise PipelineError(f'Pipeline plugin {point.name!r} failed to load: {exc}') from None
    for value in (getenv('SCOUT_PIPELINE_PLUGINS') or '').split(','):
        if value.strip():plugins.append(_reference(value))
    return plugins


def build_pipeline(plugins:list[tuple[str,Plugin]]|None=None)->Pipeline:
    pipeline=default_pipeline()
    for label,plugin in (discover_plugins() if plugins is None else plugins):
        if not callable(plugin):raise PipelineError(f'Pipeline plugin {label} is not callable.')
        try:plugin(pipeline)
        except PipelineError as exc:raise PipelineError(f'Pipeline plugin {label}: {exc}') from None
    agent=(getenv('SCOUT_DECISION_AGENT') or 'jev').strip().lower()
    if agent not in DECISION_AGENTS:raise PipelineError(f'SCOUT_DECISION_AGENT must be one of {", ".join(DECISION_AGENTS)}.')
    if agent!='jev':pipeline.replace('decide',DECISION_AGENTS[agent]())
    for name in (getenv('SCOUT_DISABLED_NODES') or '').split(','):
        if name.strip():pipeline.remove(name.strip())
    pipeline.validate()
    return pipeline
