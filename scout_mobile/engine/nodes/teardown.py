"""Teardown stage: restore device state and release resources. Every node runs even if one fails."""
from __future__ import annotations
import json
from ...device import DeviceError
from ..node import Node, RunContext


class DrainEvidence(Node):
    name='evidence_drain';stage='teardown';role='reporting';locked=True
    summary='Finish background screenshots before the driver closes.'
    def run(self,ctx:RunContext):
        ctx.agent.close_evidence()


class RestoreLifecycle(Node):
    name='lifecycle_restore';stage='teardown';role='resource';locked=True
    summary='Restore device settings changed by lifecycle setup; mark cleanup failed on error.'
    def run(self,ctx:RunContext):
        lifecycle=ctx.agent.lifecycle
        if not lifecycle:return None
        try:lifecycle.restore()
        except (DeviceError,OSError):lifecycle.failed=True


class SaveExecutionEvidence(Node):
    name='execution_evidence';stage='teardown';role='reporting';locked=True
    summary='Persist deterministic execution assertions and evidence.'
    def run(self,ctx:RunContext):
        if ctx.agent.protocol:ctx.agent.protocol.save()


class StopSandbox(Node):
    name='sandbox_stop';stage='teardown';role='resource';locked=True
    summary='Stop the network sandbox and restore routing.'
    def run(self,ctx:RunContext):
        if ctx.agent.sandbox_session:ctx.agent.sandbox_session.stop()


class CloseDevice(Node):
    name='device_close';stage='teardown';role='resource';locked=True
    summary='Close the driver session.'
    def run(self,ctx:RunContext):
        ctx.agent.device.close()


class ReleaseDeviceLease(Node):
    name='device_lease_release';stage='teardown';role='resource';locked=True
    summary='Release the per-device lock unless the caller manages it.'
    def run(self,ctx:RunContext):
        if not ctx.agent.lease_managed:ctx.agent.lease.release()


class PipelineReport(Node):
    name='pipeline_report';stage='teardown';role='reporting'
    summary='Write pipeline.json: the node graph used and a per-node outcome/timing trace.'
    def run(self,ctx:RunContext):
        agent=ctx.agent
        report={'schema_version':1,'nodes':agent.pipeline.describe(),'trace':ctx.trace}
        (agent.output/'pipeline.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
