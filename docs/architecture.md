# Architecture: layers and the node pipeline

Scout's runner is organised as **layers** (what a module may depend on) and a
**node pipeline** (how a run executes). Each step of a run is a named node that
you can inspect, and unlocked nodes can be replaced, removed, or extended with
plugins.

## Layers

`scout_mobile/architecture.py` assigns every module to a layer. A module may
import only from its own layer or a lower one. `checks/test_architecture.py`
enforces this, including lazy imports inside functions, and fails when a new
module has no layer.

| Rank | Layer | Responsibility | Modules |
|---|---|---|---|
| 0 | foundation | Configuration and identity | `config`, `branding`, `architecture` |
| 1 | platform | Device drivers: observe, act, record | `device`, `appium_runtime`, `appium_device`, `ios_device`, `devices` |
| 2 | contracts | Pure policy and schema | `execution_contract`, `network_contract`, `temporal`, `validation`, `evidence`, `safety`, `media_verification` |
| 3 | intelligence | Model-backed judgment | `model`, `checkpoints`, `starting_conditions`, `platform_comparison` |
| 4 | runtime_services | Side services a run can start | `sandbox*`, `sandbox_variants`, `run_analysis` |
| 5 | engine | Run orchestration | `engine/` (pipeline + nodes), `agent`, `execution_runtime`, `lifecycle`, `device_lease`, `capabilities` |
| 6 | application | Jobs, sessions, dashboard sync | `dashboard_client`, `dashboard_runtime`, `dashboard_jobs`, `library_sessions` |
| 7 | interfaces | Entry points | `__main__` (CLI), `mcp_server`, `local_server` |

Known exception: `capabilities.diagnose()` reaches into the application layer to
report dashboard and job health. It is listed in `ALLOWED_UPWARD` and should move
to the application layer.

## The run pipeline

`Agent` is the **run session**. It owns the device, credentials and redaction,
evidence, checkpoint verdicts, and result writing. The run itself is a
`Pipeline` of nodes in three stages:

```
setup     device_lease → sandbox → app_installed → lifecycle_prepare → launch_app
          → starting_conditions → initial_checkpoints → emulator_guard_initial
          → deterministic_execution → verification_only → compose_goal

step      stop_request → time_limit → foreground → credential_prompt → app_boundary
(loop)    → date_gate → cycle_detector → tutorial_guard
          → decide                                  ← decision agent slot
          → tutorial_gesture → authorize_gesture → record_decision → done → blocked
          → ios_alert_guard → consent_guard → consequential_control_guard → repeat_guard
          → evidence_barrier → ground_target → focus_field → resolve_text → perform_action
          → settle → step_checkpoints → report_progress → emulator_guard

teardown  evidence_drain → lifecycle_restore → execution_evidence → sandbox_stop → device_close
          → pipeline_report → device_lease_release
```

Run `scout nodes` to print the pipeline that is actually assembled, including
installed plugins and disabled nodes.

### Node contract

```python
from scout_mobile.engine import Node, NEXT_STEP

class MyNode(Node):
    name = 'my_node'           # unique across the pipeline
    stage = 'step'             # setup | step | teardown
    role = 'verification'      # resource | perception | guard | decision | action | verification | reporting
    summary = 'One line shown by `scout nodes`.'
    requires = ('next_screen',)  # context fields read; checked when the pipeline is assembled
    provides = ()                # context fields set

    def run(self, ctx):
        ...                    # return None to continue,
                               # NEXT_STEP to end this loop iteration (step stage only),
                               # ctx.finish(status, reason) to end the run.
```

`ctx` is a `RunContext`. Run-wide services live on `ctx.agent` (`device`,
`history`, `redact`, `screenshot`, `write_result`, and others). Per-step state
lives on the context itself (`screen`, `step`, `decision`, `op`, `selected`,
`target`, `entry`, `phases`, `next_screen`, and others). Plugin state belongs in
`ctx.extras[node_name]`.

A node can also be a generator. Anything it yields goes to the host, and the
host's reply is sent back into the node. `resolve_text` uses this to pause for
MCP host text (`awaiting_input`).

### Evidence capture and settle timing

`settle` starts the step screenshot in a background thread so the capture overlaps
checkpoint evaluation and the next decision. The locked `evidence_barrier` waits for
it before the next step touches the device. The date-gate and credential-prompt
handlers also wait before they tap. A failed capture stops the run as an execution
error. If the run is already finishing, the failure is added to the result notes
instead. Files are written to `NNN.png.part` and renamed, so live viewers never see
a partial image. After a credential has been used, capture is synchronous again.

`settle` waits up to 4 s for a change after taps, typing and back. After swipes it
waits up to 1.5 s, because a swipe that changes nothing has reached the end of its
content. The last poll is returned without an extra observation after the deadline.

### Locked nodes

Some nodes enforce safety or own resources: the consent, purchase/transfer,
credential, app-boundary, and stale-target guards, plus the lease, sandbox, and
lifecycle nodes. These are `locked`. `remove`, `replace`, and
`SCOUT_DISABLED_NODES` refuse them. A plugin can add checks around a locked node
but cannot bypass it.

The `decide` node is the replaceable **decision agent** slot. A replacement must
set `decision`, `op`, `selected`, `public`, and `loop_started`. The decision dict
carries `operation`, `target`, `confidence`, `model`, `latency_ms`, and `jev` (the
audit payload). The guards that follow still apply to whatever the replacement
chooses.

## Plugging nodes in and out

A plugin is a callable that edits the pipeline:

```python
# my_package/scout_plugin.py
from scout_mobile.engine import Node

class SlowScreenDetector(Node):
    name = 'slow_screen_detector'
    role = 'verification'
    summary = 'Flag steps whose settle wait exceeded 3 s.'
    requires = ('phases',)
    def run(self, ctx):
        if ctx.phases.get('wait_for_change_ms', 0) > 3000:
            ctx.entry['slow_screen'] = True

def install(pipeline):
    pipeline.insert(SlowScreenDetector(), before='step_checkpoints')
```

Install it in one of two ways:

- **Package entry point** (persistent): in the plugin package's `pyproject.toml`
  ```toml
  [project.entry-points."scout.pipeline"]
  slow-screen = "my_package.scout_plugin:install"
  ```
- **Environment** (local and ad hoc): `SCOUT_PIPELINE_PLUGINS=my_package.scout_plugin:install`

To remove unlocked nodes, set `SCOUT_DISABLED_NODES=cycle_detector,date_gate`.

The editing API is `insert(node, before=|after=)`, `replace(name, node)`,
`remove(name)`, `append(node)`, `get(name)`, `nodes(stage)`, and `describe()`.
Plugin errors, duplicate names, edits to locked nodes, and unmet `requires` fail
when the pipeline is assembled, before a device is touched.

## Inspecting a run, node by node

Every run writes `runner-output/<run>/pipeline.json`, which contains:

- `nodes`: the exact graph used, with each node's source class
- `trace`: one entry per node execution, with `stage`, `step`, `node`, `outcome`
  (`next`, `next_step`, `finish`, or `error:<Type>`), and `duration_ms`

`pipeline.json` is local only. It is not part of the evidence inventory that is
synced to the dashboard.

From MCP:

- `get_runner_pipeline()` returns the layers and the assembled pipeline
- `get_runner_pipeline(run_id=...)` returns that run's graph and node trace
- `get_runner_pipeline(run_id=..., node="decide")` returns one node's executions
