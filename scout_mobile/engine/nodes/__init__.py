"""Built-in pipeline nodes, in default execution order."""
from __future__ import annotations
from ..node import Node
from .setup import AcquireDeviceLease, StartSandbox, CheckAppInstalled, PrepareLifecycle, LaunchApp, CheckStartingConditions, InitialCheckpoints, InitialEmulatorGuard, DeterministicExecution, VerificationOnly, ComposeGoal
from .guards import StopRequest, TimeLimit, ObserveForeground, CredentialPrompt, AppBoundary, DateGate, CycleDetector, TutorialGuard, TutorialGesture, AuthorizeGesture, IOSAlertGuard, ConsentGuard, ConsequentialControlGuard, RepeatGuard, EmulatorGuard
from .decide import JevDecision, RecordDecision, Done, Blocked
from .act import EvidenceBarrier, GroundTarget, FocusField, ResolveText, PerformAction, Settle, StepCheckpoints, ReportProgress
from .teardown import DrainEvidence, RestoreLifecycle, SaveExecutionEvidence, StopSandbox, CloseDevice, ReleaseDeviceLease, PipelineReport

DEFAULT_NODES:tuple[type[Node],...]=(
    # setup
    AcquireDeviceLease, StartSandbox, CheckAppInstalled, PrepareLifecycle, LaunchApp, CheckStartingConditions,
    InitialCheckpoints, InitialEmulatorGuard, DeterministicExecution, VerificationOnly, ComposeGoal,
    # step: perceive and guard, decide, guard the decision, act, settle, verify
    StopRequest, TimeLimit, ObserveForeground, CredentialPrompt, AppBoundary, DateGate, CycleDetector, TutorialGuard,
    JevDecision, TutorialGesture, AuthorizeGesture, RecordDecision, Done, Blocked,
    IOSAlertGuard, ConsentGuard, ConsequentialControlGuard, RepeatGuard,
    EvidenceBarrier, GroundTarget, FocusField, ResolveText, PerformAction, Settle, StepCheckpoints, ReportProgress, EmulatorGuard,
    # teardown (order matters: restore before closing the driver, release the lease last)
    DrainEvidence, RestoreLifecycle, SaveExecutionEvidence, StopSandbox, CloseDevice, PipelineReport, ReleaseDeviceLease,
)
