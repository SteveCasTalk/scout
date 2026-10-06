# Next slice: a real Android execution path

The current dashboard is a persistent foundation, not an autonomous testing engine.

Start with one selected Android device and one app flow. Use Scout to inspect the real UI and verify interactions before authoring mobile test code, following the repository's [mobile testing instructions](../../AGENTS.md). ARTEMIS is optional and only used when explicitly requested. iOS needs a separate platform driver; no iOS execution support is claimed today.

Proposed work:

1. Identify target app/build, connected device, test account, reset strategy, and assertions.
2. Add a local worker that owns device access. The hosted dashboard cannot directly access a USB device.
3. Introduce queued/running/completed job states, a device lease, cancellation, and heartbeats. Keep manual result records separate from worker-generated results.
4. Authenticate workers with narrowly scoped credentials; never expose device control through unauthenticated dashboard endpoints.
5. Store an append-only action trace with monotonically increasing timestamps, observed locators, actions, waits, assertion evidence, and failure reasons.
6. Upload evidence incrementally. Link video offsets and screenshots to trace steps.
7. Implement independent assertions and report inconclusive outcomes explicitly. Do not turn runner failures into product failures.
8. Verify repeated runs from a known starting state before expanding to more flows or iOS.

Suggested domain additions: builds, devices, jobs, execution_steps, assertion_results. Device identifiers and app artifact storage belong to this future slice, not to the current manual run form.
