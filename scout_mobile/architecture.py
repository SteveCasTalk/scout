"""Layer model for scout_mobile. A module may import only from its own layer or a lower one.

checks/test_architecture.py enforces this, including lazy imports inside functions.
Every module must be assigned a layer; subpackages are assigned by their top-level name.
"""
from __future__ import annotations

LAYERS:tuple[tuple[str,str,tuple[str,...]],...]=(
    ('foundation','Configuration and product identity; no Scout imports.',
     ('config','branding','architecture')),
    ('platform','Device drivers: observe, act, record. Knows nothing about tests.',
     ('device','appium_runtime','appium_device','ios_device','devices')),
    ('contracts','Pure policies and schemas: execution contract, safety patterns, evidence rules.',
     ('execution_contract','network_contract','temporal','validation','evidence','safety','media_verification')),
    ('intelligence','Model-backed judgment: operation choice, checkpoint and starting-condition evaluation.',
     ('model','checkpoints','starting_conditions','platform_comparison')),
    ('runtime_services','Run-time side services the engine can start: network sandbox and recording.',
     ('sandbox','sandbox_recording','sandbox_addon','sandbox_recording_addon','sandbox_worker','sandbox_variants','run_analysis')),
    ('engine','Run orchestration: the node pipeline, the run session, leases, lifecycle, capabilities.',
     ('engine','agent','execution_runtime','lifecycle','device_lease','capabilities')),
    ('application','Job and session management, dashboard sync.',
     ('dashboard_client','dashboard_runtime','dashboard_jobs','library_sessions')),
    ('interfaces','Entry points: CLI, MCP server, local device bridge.',
     ('__main__','__init__','mcp_server','local_server')),
)

# Known upward imports, kept explicit so they cannot grow silently.
ALLOWED_UPWARD:frozenset[tuple[str,str]]=frozenset({
    # capabilities.diagnose() reports dashboard and job health; it belongs in application.
    ('capabilities','dashboard_client'),
    ('capabilities','dashboard_jobs'),
})

LAYER_OF:dict[str,int]={module:index for index,(_,_,modules) in enumerate(LAYERS) for module in modules}


def describe()->list[dict]:
    return [{'layer':name,'rank':index,'summary':summary,'modules':list(modules)} for index,(name,summary,modules) in enumerate(LAYERS)]
