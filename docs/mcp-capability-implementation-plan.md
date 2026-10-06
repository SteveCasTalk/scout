# Scout MCP capability implementation plan

Date: 2026-10-05. Status: generic capability implementation completed in the working
checkout at the user's request. Synthetic validation is recorded below; device
acceptance and deployment remain separate.
Baseline inspected: commit `56a03b5`, plus the current uncommitted workspace edits.

## Objective and agreed scope

Enable the requested Twomi coverage through Scout MCP while preserving existing
cases, integrations, safeguards, historical results, and review provenance.
Scout is the default exploration and execution tool. ARTEMIS is not required.
This phase implements generic Scout capabilities. It does not author Twomi
navigation cases or claim the feature suite has passed.

The conversation narrows two original requests:

- **G01: purchase-entry CTA only.** Permit one explicitly scoped app CTA that
  opens a purchase flow. Do not confirm payment, complete a subscription, retry
  a purchase, or claim entitlement activation. Google Play license-test setup
  is not a prerequisite for this scope. A CTA that itself commits a transaction
  is outside this capability. Unknown action semantics remain blocked.
- **G02: multiple approved packages in one run.** Scout can already open Twomi
  and inspect its UI tree. The missing behavior is continuing a run across an
  approved package boundary, then checking its return. An embedded WebView in
  Twomi normally remains inside its package; browser Custom Tabs and external
  browsers may cross that boundary. WebView accessibility is a separate issue.

The selected device for later validation is Samsung SM-S906E, serial
`RFCTB15BTEW`. Selection persists; no new device run is part of writing this plan.

## Evidence baseline

The running MCP executable uses the `scout` symlink to this checkout. The original
process did not publish a startup source hash, so its exact in-memory revision
cannot be independently attested from the Git revision alone. Add that to G10.

Source inspection confirms the consequential-label guard in `agent.py`, the
purchase prohibition in `model.py`, the Android foreground-package restriction,
and the limited action/checkpoint contracts. G05's current fixture schema uses
exact paths and limits scheduled WebSocket pushes to 60 seconds. G09 authoring
tools are absent from the exposed MCP inventory.

The earlier dashboard discovery error was reproduced. A basic opening-screen
observation reached Twomi User Settings on `1.16.0-UAT`, version code 29; it did
not establish buddy feature readiness. That run exposed a credential-setting
restoration issue. A local patch and a follow-up observation verified restoration
for that observed empty-setting case. These are setup/runner findings, not buddy
feature results. No buddy, purchase, plan, or conversation feature suite has run.

Existing uncommitted changes to AGENTS.md, the older planning note, and credential
restoration must be reviewed separately from the future capability changes.

## Compatibility contract

1. **Old cases keep old semantics.** Missing capability configuration means the
   existing action set and safeguards. `during_run` continues to mean observed
   at least once; `final` continues to mean the final observation. Do not reinterpret
   either as a temporal invariant. Existing checkpoint IDs and outcomes remain intact.
2. **Preserve existing entry points.** Keep MCP tool names, required arguments,
   Android compatibility aliases, CLI flags, return identifiers, and existing
   `SCOUT_*`/legacy `JEV_*` configuration precedence. New arguments are optional.
   Add discovery and authoring tools without requiring existing clients to call them.
3. **Version definitions separately from edits.** Introduce a versioned execution
   contract and a declared `required_capabilities` set. Case `revision` remains
   the optimistic-concurrency counter; it is not a schema version. Validate the
   same contract in Python and TypeScript using shared JSON fixtures.
4. **Do not silently downgrade.** New runners accept old cases. Old runners are
   supported for old cases only. They must not receive runnable definitions that
   require new behavior. Reject unsupported capabilities before launch or setup
   mutations, with a specific reason. Use an explicit versioned export envelope
   for new cases that old CLI/MCP loaders reject for missing legacy top-level
   fields. Never export a new case as a legacy flat object after dropping options.
5. **Gate mixed deployments at the server.** Require a capability handshake for
   new-case freeze, execution, editing, and import. Legacy clients may use legacy
   cases; reject edits/runs of new cases through legacy routes to prevent field
   loss. Block downgraded dashboard/bridge deployment while new cases are runnable;
   older software cannot be made safe by adding an ignored field to its input.
6. **Additive persistence.** Add nullable/defaulted capability JSON and version
   columns with a migration. Old rows decode to legacy defaults. Freeze the full
   normalized contract and its fingerprint in case revisions, suite/matrix entries,
   and run snapshots. Preserve old snapshots without rewriting history.
7. **Separate definitions from permission.** A case describes requested behavior;
   its text, imported fixture, or saved policy is not authorization. New purchase
   entry and destructive preparation require explicit run-level grants bounded
   by the case declaration. Existing session authorization may supply those grants;
   do not repeatedly ask for permission already given. `allow_consent` stays separate.
8. **Preserve result compatibility.** Keep Passed, Failed, Inconclusive, Blocked,
   and Execution error. Add machine-readable reason codes and evidence references.
   Persist high-volume samples in a bounded, versioned evidence artifact instead
   of exceeding the current trace/checkpoint limits. Update every evidence allowlist
   and sync path together. Original verdicts and human reviews remain append-only.
9. **Platform/backend capability checks.** Advertise support per Android/iOS and
   Appium/ADB adapter. Android-only additions do not change iOS behavior. An
   unsupported adapter returns Blocked; never silently switch adapters or emulate
   precision it cannot provide.

Proposed additive fields, subject to schema review:

| Location | Fields / responsibility |
| --- | --- |
| Saved definition | `execution_contract_version`, `required_capabilities`, `execution_policy`, `actions`, `temporal_assertions`, `lifecycle`, `request_assertions`, `media_assertions` |
| Run request | Narrow `authorizations`, explicit selected device, expected revisions, existing request ID; grants cannot widen the saved declaration |
| Discovery | `get_runner_capabilities`: loaded build identity, supported contract versions, platform/adapter feature set, numerical limits |
| Readiness | `diagnose_environment`: per-dependency status and remedy, separately from capability discovery |
| Result/evidence | Contract fingerprint, loaded component identities, structured policy decisions, monotonic events, coverage/cleanup summaries, evidence references |

Keep free-text steps available. Add typed actions only where deterministic gesture,
timing, or boundary behavior is needed. Resolve their selectors from fresh observed
UI state; do not turn model-generated prose into executable shell commands.

## G01 — Purchase-entry CTA

Implementation:

- Add a purchase-entry declaration with target app, exact grounded selector,
  screen preconditions, expected destination, and one allowed dispatch per entry.
  Bind run authorization to the case revision and that declaration.
- Replace neither the global consequential-action regex nor the default model
  prohibition. Add a narrowly evaluated exception for this declared entry action,
  and expose it to the model only when authorized and applicable.
- Revalidate foreground, selector uniqueness, enabled state, and preconditions
  immediately before the tap. Missing or ambiguous grounding stops the action.
- Consume the dispatch allowance before sending the input. Timeout, lost response,
  or unchanged screen does not authorize a retry. Preserve that fact through
  resume and request-ID retries; a new intentional run requires new run scope.
- Observe the expected handoff and stop at its declared boundary. Permit a safe
  return only if specified. Keep checkout screens observation-only by default,
  regardless of whether a final button happens to say Buy, Confirm, or Continue.
- Record entry/handoff evidence, explicitly labeled `purchase_entry_only`.
  `allow_consent`, a package allowlist, or a tap burst cannot authorize checkout.

Acceptance: approved CTA dispatches once; unapproved/ambiguous CTA is blocked;
checkout commitment remains blocked; interrupted dispatch is not retried; legacy
cases still block purchase labels. Positive device validation occurs later.

## G02 — Approved cross-package execution

Implementation:

- Add explicit source/destination transitions, entry preconditions, allowed
  actions, maximum time/actions, and an expected return package/screen.
  Package membership alone does not authorize every control in that package.
- Centralize boundary enforcement for model actions, typed actions, waits, bursts,
  permission handling, and existing automatic prompt helpers. Check the current
  foreground and fresh UI together; unknown foreground is not approval.
- Observe a permitted destination through the existing adapter and UI tree.
  Preserve dynamic target selection. Missing/obscured controls remain unsupported;
  do not assume package knowledge guarantees useful accessibility.
- Keep existing known credential-manager handling narrowly scoped. Add explicit
  permission and chooser rules without authorizing unrelated settings or shares.
- Capture redacted destination evidence for unexpected packages and stop with
  `Blocked` and a boundary reason. Returning to the right package alone is not
  sufficient when the case requires a particular Twomi screen.

Acceptance: declared A→B→A flow is supported; A→unexpected-C stops before action;
declared return timeout is reported; unknown foreground stops; checkout guards
still hold in an allowed Play package. G02 behavior is opt-in for legacy cases.

## G03 — Grounded gestures and bounded bursts

Implementation:

- Define typed target swipe, drag, and repeated-tap actions. Parameters include
  source selector, destination selector or target-relative endpoint, direction,
  duration, bounded count/interval, and timing tolerance.
- Support observed non-clickable message/handle bounds for gestures; the current
  actionable-element list alone may exclude these. Preserve the default model
  action list and add gesture candidates only for opted-in cases.
- Use native adapter gesture sequences. Resolve targets dynamically, re-observe
  stale targets, and allow coordinate fallback only when explicitly configured,
  previously verified, and compatible with the current viewport and screen.
- Keep bursts short and restricted to controls known to be safe for repetition.
  Do not use them for purchase entry, consent, or cross-package transitions. Do
  not re-ground between tightly timed taps and pretend the interval was preserved.
- Record target bounds, screen fingerprint, dispatch start/end, requested device
  sequence offsets, measured timing where available, and backend identity. Host
  dispatch timestamps are not proof of exact device event delivery times.

Acceptance: selected message swipe does not use a whole-screen default; drag
resolves both ends; duplicate or stale targets stop; bounded taps execute without
model latency between taps. Unmeasurable or out-of-tolerance timing is inconclusive
for a timing assertion, even if the action request succeeded.

## G04 — Temporal and ordered assertions

Implementation:

- Add separate temporal definitions with explicit trigger, predicate, mode
  (`within`, `until`, `never_during`, `ordered`, or sampled `stable_for`), window,
  tolerance, and required evidence source. Do not add new meanings to old scopes.
- Implement a bounded deterministic observer using monotonic time. Define whether
  a deadline starts at input dispatch, dispatch completion, or an observed app
  event. Correlate app/network clocks explicitly; wall-clock text is insufficient.
- Schedule UI reads and device actions through one device owner, rather than
  issuing concurrent Appium commands. Capture observation start/end, gaps, errors,
  dropped events, interruption, and source availability. Do not hide LLM time in
  an unobserved interval.
- Distinguish sampled UI checks from continuous instrumented-event evidence.
  UI sampling may establish an observed violation or deadline success, but cannot
  prove no brief welcome/data flash occurred between samples. Strict absence
  requires a complete event source covering the interval; otherwise inconclusive.
- Ordered events observed in one ambiguous sample do not establish their order.
  A condition found after a sampling gap crossing a deadline does not prove the
  deadline was missed. Positive violations and complete evidence must be assessed
  separately from mere missing observations.
- Stop observers on cancellation/failure, persist partial evidence, bound sample
  storage, and report truncation. No incomplete observation window passes.

Acceptance: synthetic timelines cover on-time, late, early forbidden event,
missing trigger, missing interval, reordered and tied events, cancellation, and
clock uncertainty. Later device demonstrations use actual observed triggers.
Full reminder/no-flash coverage depends on suitable app instrumentation.

## Additional capabilities

| Gap | Implementation slice | Dependency and acceptance boundary |
| --- | --- | --- |
| G05 | Add versioned query/header/body predicates, explicit path templates, session correlation, deterministic response advancement, and event-relative late WS scheduling. Detect conflicting matches and define precedence. Preserve v1 exact host/method/path and arrival-order behavior for v1 fixtures. | Implement generic matching now; Twomi fixtures require actual contracts. Verify concurrent requests get their intended responses independent of arrival order. Missing correlation/trigger is an incident. WS still requires a real handshake; no LiveKit/WebRTC media claim. Bound late timers and cancel them on teardown. |
| G06 | Add typed pre/post hooks for process death, supported permission/network changes, and explicit app-supported fixture hooks; snapshot changed state and verify restoration. Add destructive reset grants separately. | No arbitrary model shell. Account/cache seeding requires a real app hook or verified procedure. Preserve relaunch semantics. Existing notification suppression must be selectable for new permission cases, with legacy defaults unchanged. Cleanup errors stop the next variant, even with continue-on-failure, and require reconciliation after a crash. |
| G07 | Define an optional verifier interface with input artifacts, verifier version, expected tolerances, structured verdict and evidence locations. Start with exported-file metadata and bounded frame comparisons; add audio only with a valid capture source. | Missing artifact/source is inconclusive. Define each requirement before choosing a verifier: frame change alone does not prove correct playback; host mute does not prove app mute. Keep visual/media assertions out of text-only classifier success. Do not install heavyweight media tooling by default. |
| G08 | Add opt-in in-memory structural assertions for allowlisted request/event fields, counts, ordering, and duplicate detection. Correlate with action/checkpoint timestamps. Persist redacted structural results, not raw conversations or credentials. | Real endpoint/event schemas and capture source required. Test redaction before storage and model exposure. A proxy hit is not payload correctness. Include unmatched requests, dropped events, and capture completeness in the verdict. |
| G09 | Add `validate_test_cases`, `create_test_case`, `update_test_case`, and `import_test_cases` using owner/workspace-scoped dashboard services. Require expected revision on update, request IDs on writes, canonical payload hashes, and bounded bulk size. | Each item is atomic with an explicit success/error; bulk partial success is visible. Same ID + same payload returns the original result; same ID + different payload conflicts. Dry-run writes nothing and does not reserve revisions. Validate matrix references only against saved compatible cases. Never execute as a save side effect. |
| G10 | Add read-only component readiness and capability discovery. Publish startup-captured build/source fingerprint, schema versions, and adapter support for MCP, bridge, and dashboard. Check authentication/workspace separately from HTTP health. | Probe device/app only when a serial is selected and idle; do not launch or reset apps. Report credential presence only. Proxy listener presence does not prove app traffic routes through it or trusts the CA. Mark those unverified unless an explicit later probe provides evidence. Report active locks and exact remedies without bypassing auth. |

## Implementation sequence and review units

| Stage | Deliverable | Main files / areas | Exit condition |
| --- | --- | --- | --- |
| 0 | Review the pre-existing cleanup fix independently; freeze baseline compatibility fixtures and this scope | `device.py`, existing checks, exported legacy definitions/results | Empty, absent, populated and shell-sensitive settings restore; failures remain visible; no scope expansion |
| 1 | Version/capability contract and G10 read-only discovery | `mcp_server.py`, `local_server.py`, `dashboard/lib/contracts.ts`, new shared contract fixtures | Old inputs round-trip; unknown requirements block; loaded component mismatch is visible |
| 2 | Additive persistence, snapshots, and G09 authoring | `dashboard/app/api/cases/route.ts`, `api/library/route.ts`, `case-record.ts`, Drizzle migration, `dashboard_client.py` | Revision conflicts/idempotency work; no execution on writes; no field loss on import/export |
| 3 | Narrow G01 and G02 through every execution entry point | `model.py`, `agent.py`, `mcp_server.py`, `__main__.py`, `dashboard_jobs.py`, `library_sessions.py` | Entry-only exception and approved transitions work in synthetic integration checks; no guard bypass via other actions/helpers |
| 4 | G03 typed actions and adapter implementations | `device.py`, `appium_device.py`, model action exposure and runner dispatch | Grounding, timing bounds, stale-target handling, unsupported backend rejection |
| 5 | Standard G06 hooks and cleanup enforcement | jobs/sessions, adapter lifecycle, preparation/cleanup evidence | Starting state verified; restoration runs on all exits; cleanup failure stops suite/matrix |
| 6 | G04 observer and temporal evidence | new temporal evaluator, runner scheduling, evidence APIs/import UI | Synthetic timelines yield correct failed/inconclusive distinctions; cancellation and completeness accounted for |
| 7 | Contract-dependent G05/G08 slices | sandbox validators/addons, evidence handling, dashboard network view | Real schema available before Twomi fixture authoring; concurrency/redaction/ordering verified |
| 8 | Optional G07 verifiers and later device acceptance | verifier interface, media artifacts, result viewer | Explicit evidence source/tolerance per requirement; no unsupported visual/audio claims |

Carry each new field through MCP → validation → stored case → frozen revision →
bridge/job → RunConfig → runner/adapter → result → evidence export/sync → dashboard.
Review the existing field projections in `dashboard_jobs.py` progress,
`dashboard_client.py` trace sync, `library_sessions.py` summaries, and TypeScript
run schemas. Adding a field only to the MCP input is not a completed capability.

Do not estimate this as work already covered by the two Android developers' one-week
feature sprint. Size each review unit after its schema and dependency review;
Scout ownership and app instrumentation work must be planned explicitly.

## Verification and release strategy

During implementation, use synthetic unit/contract/integration checks; do not author
Twomi device scripts from unverified selectors. Required coverage:

- Legacy flat export, prompt tool, saved case, suite, matrix, CLI and Android aliases
  behave as before with no new options. Old v1 fixtures keep their matching behavior.
- New definition survives save/read/edit/export/import/freeze/result synchronization
  with unchanged normalized fingerprint. Old revisions remain independently readable.
- New MCP + old bridge, old MCP + new dashboard, and old CLI + new export fail safely
  for new capabilities while continuing to support old cases. Test actual old-loader
  behavior against fixtures, not only the new validator's interpretation of it.
- Update conflicts, duplicate request IDs, partial imports, interrupted starts,
  stale targets, unknown foreground, denied authorization, cancellations, and cleanup
  failures preserve evidence and cannot accidentally repeat consequential actions.
- Timing/evidence gaps, network capture truncation, and unavailable media inputs
  never become a pass. Historical verdicts and human review authorship are unchanged.

Roll out schema/migration and server gates first, then capable runners, then new
authoring surfaces. Reload MCP/bridge after deploying code and verify their startup
identities. New features remain opt-in until these checks pass. For rollback, stop
active runs and verify cleanup, disable new-capability scheduling/authoring, retain
additive data and evidence, and keep the server compatibility gate deployed. Do
not downgrade new cases or drop migration columns to make an old runner accept them.

Later, when feature execution is requested, explore through Scout and create minimal
cases with verified selectors. Run on the selected Samsung with an identified build,
prepared account/fixtures, and proven starting conditions. Record each demonstration's
case revision, component build identities, source type, trace and independent review.
Package knowledge alone is not proof of feature-ready screens.

## Twomi context and smoke coverage

Preserve the six-story scope: AVA-6813, AVA-6814, AVA-6819, AVA-6816, AVA-6822,
and AVA-6821. Buddies are catalog objects. Subscriptions and conversation history
belong to the login and are shared across that login's accounts. Same-login account
switches preserve history; different logins must not expose cached data.

Keep these expectations in future case definitions:

- My plans includes active/payment-issue plans and excludes ended/revoked plans.
- Avatar detail pages vertically, without wrapping. Action, more and separate Chat
  controls are absent in this release; do not create navigation to them.
- Access is checked on conversation open. An existing session continues after
  entitlement changes; the next open rechecks access.
- Plan/detail refresh behavior follows the supplied specification rather than an
  assumed live refresh. Hidden account/entitlement state needs independent preparation.
- AVA-6818's free-month destination is outside this sprint. Missing product behavior
  is a dependency, not a Scout defect. Affiliate price presentation in My plans
  remains a specification clarification.

The requested smoke suite remains H01, H03, H07, D01, D03, D07, L02, L05, M01,
C01, C03 and P04. Minimum enabling work is G01/G02 plus G09/G10, the G06 state
isolation needed by the chosen cases, and only the G03/G04/G05 slices their actual
assertions require. G07/G08 are added when an assertion depends on their evidence.

**P04 coverage boundary:** purchase-entry support covers only reaching checkout.
It does not complete the original purchase/activation requirement. Keep that
remaining portion explicitly uncovered or blocked; do not rename an entry-only
pass as full P04 success. A separately prepared backend fixture may exercise
app-side activation handling, labeled mocked-network, without proving a store
purchase. Real checkout completion is outside the current G01 implementation.

## Dependencies to resolve before device acceptance

No blocker prevents the generic contracts and narrow G01/G02 implementation.
The following are later acceptance prerequisites, not reasons to invent defaults:

| Dependency | Needed for |
| --- | --- |
| Feature-ready app build and observed CTA/destination selectors | G01/G02/G03 device demonstrations |
| Approved accounts and deterministic app fixture/reset procedure | G06 and login-isolation variants |
| Real HTTP/WS/analytics contracts and field allowlists | Twomi-specific G05/G08 |
| Correlated, sufficiently complete app/event evidence | Strict G04 no-flash/no-premature-welcome and reminder assertions |
| Actual exported media/audio capture and agreed tolerances | G07 |
| Working dashboard/auth/workspace and bridge | G09 and saved-case integration acceptance |
| Proxy routing and app CA trust, verified separately | Network fixture acceptance |

References: [MCP contract and current workflow](mcp.md), [sandbox behavior](sandbox.md),
[repository instructions](../AGENTS.md), and the supplied Android documents at
`/Users/phucnguyen/Documents/custom-avatar-android/docs/testing/buddies-sprint39-test-plan.md`
and `scout-capability-gaps.md` in the same directory. This plan supersedes their
original G01/G02 scope for Scout implementation; it does not rewrite product
acceptance criteria or historical results.


## Implementation record

The working checkout now implements the versioned execution contract, exact target
selectors, purchase-entry grants, approved external flows, native gestures/bursts,
shared temporal sampling, reversible lifecycle journals/reconciliation, media file
verifiers, v2 request contracts/assertions, idempotent saved authoring and read-only
discovery. MCP, CLI, synchronous/asynchronous bridge paths, saved sessions/matrices,
case revisions, exports, run snapshots and evidence synchronization carry the new
fields. The dashboard preserves typed settings, exposes separate execution grants
and shows temporal/media evidence. V2 proxy timestamps align with runner monotonic
origin; external app clocks remain unverified.

The normalized contract lives under `execution.schema_version=2`; the plan's
proposed flat execution fields were consolidated into that object. It is opt-in.
Legacy cases/checkpoints/configuration/aliases retain their existing contract.
Android Appium is the supported execution adapter; ADB declines the combined native
gesture/burst requirements, and iOS execution/lifecycle additions are unsupported.
Sources and tolerances for continuous events, audio, playback correctness, blur,
outfit appearance, analytics and account/cache seeding still need app-specific
contracts/instrumentation. Strict no-flash/absence therefore remains inconclusive.

Validation in this checkout:

- 108 Python unit/integration checks pass, including baseline CLI/MCP loader
  execution before the device boundary, per-case grants/retry behavior, native
  adapter payloads, concurrent correlated request replay, WS timing/cancellation,
  credential restoration and incomplete lifecycle cleanup.
- 11 shared Python/TypeScript fixtures agree. SQLite integration applies every
  migration to an isolated temporary DB and verifies authoring ownership, dry-run,
  idempotency, optimistic conflicts, concurrent writes and retained snapshots.
- TypeScript type checking and lint for the new schemas/routes/evidence component
  pass. Existing run-session and scenario-matrix components retain their baseline
  eight React hook lint errors; this change introduces none in those components.
- Full dashboard build is blocked by the missing native `workerd` executable in
  the current dependency tree. No dependency installation was performed.
- No Twomi feature/device run or real dashboard DB migration was performed.

Rollout requires applying `0015_eminent_prodigy.sql` once to the intended dashboard
DB after its previous migrations, restoring the missing build dependency through
the repository's normal installation workflow, rebuilding the dashboard and
reloading MCP/bridge. Verify published component source identities and capability
handshakes before authoring/running v2 cases. Keep the server gates in place for
rollback. The selected Samsung remains `RFCTB15BTEW` for later authorized acceptance.

Usage: [MCP execution and authoring](mcp.md#opt-in-execution-and-authoring-contract-v2)
and [v2 sandbox contracts](sandbox.md#version-2-request-contracts).
