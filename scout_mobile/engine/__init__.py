"""Scout run engine: a pipeline of inspectable, pluggable nodes.

    setup     resources, launch, starting conditions, deterministic protocol
    step      perceive → guard → decide → guard → act → settle → verify   (repeated)
    teardown  restore, persist evidence, release resources

See docs/architecture.md for the layer model and how to write a node plugin.
"""
from .node import NEXT_STEP, Finish, Node, RunContext, ROLES, STAGES
from .pipeline import Pipeline, PipelineError
from .plugins import ENTRY_POINT_GROUP, build_pipeline, default_pipeline

__all__=['NEXT_STEP','Finish','Node','RunContext','ROLES','STAGES','Pipeline','PipelineError','ENTRY_POINT_GROUP','build_pipeline','default_pipeline']
