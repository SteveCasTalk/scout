import { brand } from '@/lib/brand';

export type DocBlock =
  | { kind: 'text'; text: string }
  | { kind: 'list'; title?: string; items: string[]; ordered?: boolean }
  | { kind: 'table'; columns: string[]; rows: string[][] }
  | { kind: 'code'; title: string; language: string; code: string }
  | { kind: 'callout'; title: string; text: string };

export type DocSection = { id: string; category: string; title: string; summary: string; blocks: DocBlock[] };

// Product documentation describes implemented behavior. Keep it in step with
// the runner contracts and technical guides when changing a capability.
export const documentation: DocSection[] = [
  {
    id: 'overview', category: 'Understand the platform', title: `What is ${brand.name}?`,
    summary: 'An evidence-first workspace for testing mobile apps with an LLM, a device runner, and human review.',
    blocks: [
      { kind: 'text', text: `${brand.name} turns a testing goal into a repeatable case, executes it on an Android or iOS device, and saves the observations behind the result. The dashboard brings cases, suites, run history, checkpoints, screenshots, recordings, logs, and reviews together.` },
      { kind: 'text', text: `${brand.name} is the platform: the case library, automation, verification, network sandbox, scenario matrices, evidence, and review tools. The current runner uses Jev for action selection and classification, and Appium for device control. The name ${brand.name} reflects a curious fox that explores apps and investigates results.` },
      { kind: 'list', title: 'Our testing philosophy', items: [
        'Explore before defining a test. Base steps on observed screens and transitions; do not invent navigation or selectors.',
        'Define success before execution. Turn each acceptance criterion into a specific, observable checkpoint.',
        'Separate navigation from verification. Completing actions does not establish that the expected result happened.',
        'Preserve evidence and uncertainty. A missing observation is a verification gap; it is not automatically an app bug.',
        'Keep people in the review loop. Retain Jev’s original decisions alongside human acceptance, disputes, and explanations.',
        'Make runs reproducible. Save the accepted definition, fixture, starting conditions, device details, and revision with each result.'
      ] },
      { kind: 'callout', title: 'What verification can establish', text: 'The runner verifies accessible UI text and control states. Screenshots and recordings support human inspection. UI success alone does not prove backend correctness, pixel-perfect rendering, or release readiness.' }
    ]
  },
  {
    id: 'concepts', category: 'Understand the platform', title: 'Core concepts',
    summary: 'The objects that connect a goal, an execution, and its evidence.',
    blocks: [
      { kind: 'table', columns: ['Concept', 'Meaning'], rows: [
        ['Workspace', 'A scoped library for an app, team, or environment. Cases, runs, and evidence belong to its owner.'],
        ['Project / Jira ticket', 'Organizing labels inside a workspace. A Jira key is optional; cases without tickets still belong in the library.'],
        ['Test case', 'A platform-specific definition: app ID, goal, steps, expected result, starting conditions, and checkpoints. Edits create revisions.'],
        ['Suite', 'Related cases grouped by workspace, project, suite name, and platform. Run one case, a subset, or the suite.'],
        ['Checkpoint', 'An observable expectation evaluated during the run or on its final observation. Required checkpoints determine the outcome.'],
        ['Run / snapshot', 'One execution and the accepted definition it used. Later case edits do not rewrite that snapshot.'],
        ['Evidence / canvas', 'Captured screens, recordings, traces, and diagnostics. The canvas inside a case shows its observed execution flow.'],
        ['Sandbox scenario', 'A saved network fixture describing scoped HTTP responses or WebSocket behavior.'],
        ['Scenario matrix / batch', 'One base case with multiple fixture variants and variant-specific expectations. A batch is one execution of selected variants.'],
        ['Review', 'A timestamped human decision about a checkpoint. It is retained separately from Jev’s original verdict.']
      ] }
    ]
  },
  {
    id: 'architecture', category: 'Understand the platform', title: 'How execution works',
    summary: 'The host LLM defines intent; Jev chooses actions; Appium controls the device; checkpoints verify observations.',
    blocks: [
      { kind: 'list', ordered: true, items: [
        'The host LLM reads the request, acceptance criteria, existing case history, and the canonical test template. It proposes steps and observable checkpoints based on app exploration.',
        'MCP tools or the dashboard accept a definition and an explicit device. Saved-library execution freezes the selected revision before device actions.',
        'The local runner launches the app and checks structured starting conditions. Missing or uncertain prerequisites produce Blocked.',
        'The runner observes the native hierarchy. TypeSafe’s Jev model selects an indexed operation and target from available choices; the runner re-observes the target before acting.',
        'Appium executes the interaction. UiAutomator2 handles Android; XCUITest handles iOS. ADB remains an Android support tool for discovery, diagnostics, settings, and recording.',
        'Checkpoint verification evaluates accessible observations as the run proceeds or ends. The navigation model reporting DONE does not by itself produce Passed.',
        'The result and available evidence are saved locally and synced to the dashboard. A reviewer can investigate and accept or dispute the original decisions.'
      ] },
      { kind: 'code', title: 'System boundaries', language: 'Architecture', code: 'User / host LLM\n  → MCP tools or dashboard\n  → local Python bridge and runner\n  → Jev action selection ↔ native observations\n  → Appium → Android / iOS app\n  → checkpoint verification\n  → local artifacts → dashboard records + evidence\n  → human review' },
      { kind: 'text', text: 'The dashboard does not directly operate a USB device. The bridge runs on the computer connected to the device. ARTEMIS may be used when exploring apps during development, but it is not the Scout runtime runner.' }
    ]
  },
  {
    id: 'quick-start', category: 'Get started', title: 'Your first run',
    summary: 'Choose the app and device, define observable success, then inspect the evidence.',
    blocks: [
      { kind: 'list', ordered: true, items: [
        'Prepare the local Python environment, dashboard database, Appium driver, and an installed UAT app. Use the setup section below.',
        'Start the dashboard and local bridge on the same computer. Open the dashboard using its active local URL and complete its development sign-in.',
        'Create or select a workspace. In Test cases, create a case with a project, optional suite/ticket, platform, and Android package or iOS bundle ID.',
        'Explore the app, then enter the goal, verified navigation steps, expected outcome, starting conditions, and required checkpoints. Keep credentials in local configuration.',
        'Select Run, choose the intended device, and review starting conditions and consent. Relaunch reopens the app but keeps login and app data.',
        'Watch progress and supply user-authorized ordinary text if requested. Stop requests take effect at an action boundary.',
        'Open the saved run. Review the outcome reason, checkpoint decisions, canvas, recording when available, logs, device information, and notes.'
      ] },
      { kind: 'callout', title: 'Before a regression', text: 'Read case dependencies and arrange execution order. Ordinary suites stop at the first non-passing outcome. Android and iOS suites execute separately.' }
    ]
  },
  {
    id: 'setup', category: 'Get started', title: 'Local setup & integrations',
    summary: 'Python, Appium, the local bridge, dashboard storage, and an MCP host.',
    blocks: [
      { kind: 'text', text: 'Use Python 3.11 or newer and Node 22.13 or newer for the dashboard. Run these commands from the repository root. Configure TYPESAFE_API_KEY in a local .env; set SCOUT_TEST_EMAIL and SCOUT_TEST_PASSWORD there when authentication tests need them. Never place keys or passwords in case definitions.' },
      { kind: 'code', title: 'Install project dependencies', language: 'Shell', code: 'uv sync\nnpm ci --prefix dashboard\nnpm ci --prefix tooling/appium' },
      { kind: 'text', text: 'A fresh local dashboard database needs the SQL migrations in dashboard/drizzle applied in numeric order through 0014. Existing databases need only unapplied migrations. Follow dashboard/README.md for the D1 build/configuration commands, then apply the additional migration files using the same command. Evidence is stored through R2; records use D1.' },
      { kind: 'code', title: 'Android driver setup · requires Android SDK and JDK', language: 'Shell', code: 'export APPIUM_HOME="$PWD/tooling/appium/.appium"\ntooling/appium/node_modules/.bin/appium driver install uiautomator2@8.7.0\ntooling/appium/node_modules/.bin/appium driver doctor uiautomator2' },
      { kind: 'code', title: 'iOS driver setup · macOS with full Xcode configured', language: 'Shell', code: 'export APPIUM_HOME="$PWD/tooling/appium/.appium"\ntooling/appium/node_modules/.bin/appium driver install xcuitest@12.13.3\ntooling/appium/node_modules/.bin/appium driver doctor xcuitest' },
      { kind: 'text', text: 'The installed local Appium server starts on demand. Drivers are installed during setup, not automatically during execution. See docs/appium-trial.md and docs/ios-appium.md for detailed prerequisites.' },
      { kind: 'code', title: 'Start these in separate terminals', language: 'Shell', code: '# Terminal 1: device bridge\nuv run python -m scout_mobile.local_server\n\n# Terminal 2: dashboard\nnpm --prefix dashboard run dev' },
      { kind: 'code', title: 'Example stdio MCP configuration · replace the checkout path', language: 'TOML', code: '[mcp_servers.scout]\ncommand = "uv"\nargs = ["run", "--directory", "/absolute/path/to/scout", "scout-mcp"]' },
      { kind: 'text', text: 'Use equivalent stdio configuration for an MCP host that expects JSON. Reload the MCP server after configuration or Python changes, and restart the bridge after updating its code. Appium defaults to port 4723, the bridge to 8765, the sandbox proxy to 8899, and the dashboard usually to 5173; use the dashboard’s returned URL if its port changes.' },
      { kind: 'callout', title: 'Local sign-in and sync', text: 'Saved-library MCP tools use the local dashboard’s normal development sign-in and owner-scoped APIs. This does not authenticate against a hosted dashboard. The bridge reads this computer’s runner-output; it does not automatically share artifacts between computers. Use the same hostname consistently because localhost and 127.0.0.1 have different cookies.' }
    ]
  },
  {
    id: 'verification', category: 'Run & review', title: 'Test definitions & verification',
    summary: 'Make success explicit, and understand exactly which evidence is being evaluated.',
    blocks: [
      { kind: 'text', text: 'Call get_test_case_template before defining new MCP input. Cases support up to 12 checkpoints with unique IDs and at least one required checkpoint. Write an expectation that identifies the relevant screen and state; a generic word such as “Success” can match an unrelated screen.' },
      { kind: 'table', columns: ['Field / method', 'Behavior'], rows: [
        ['during_run', 'An occurrence checkpoint. Retains its first supported satisfied/violated decision; it does not continuously enforce an invariant.'],
        ['final', 'Checks only the final observation, not every screen visited earlier.'],
        ['classification', 'Jev evaluates accessible text/control states and selects a verdict plus a supporting observed step. Both confidences must reach 0.85 for satisfied/violated.'],
        ['text_present / text_absent', 'Case-insensitive substring checks on observed screen text. An empty/unavailable observation cannot establish absence.'],
        ['required', 'A required violation yields Failed; all required checkpoints satisfied yields Passed, subject to execution and network coverage checks.'],
        ['Legacy assertion', 'Cases without checkpoints can use the visible-text assertion fallback. It is a substring check, not exact equality with a screenshot.']
      ] },
      { kind: 'code', title: 'Illustrative checkpoint input · adapt after exploring your app', language: 'JSON', code: JSON.stringify({ checkpoints: [ { id: 'login_form', expected: 'A login form with email and password fields is visible.', scope: 'during_run', required: true, method: 'classification' }, { id: 'account_settings', expected: 'Account settings is visible with account management controls after login.', scope: 'final', required: true, method: 'classification' } ] }, null, 2) },
      { kind: 'text', text: 'Classification uses up to eight recent observations; final checkpoints receive the last observation only. It does not examine screenshot pixels or the full video. A confidence threshold is an operational decision rule, not a calibrated probability that the app is correct. Checkpoint verdicts are satisfied, violated, not_observable, or not_reached.' },
      { kind: 'list', title: 'Starting conditions', items: [
        'Check the installed app version, required login state, visible account identifier, and up to eight required visible text values before actions.',
        'Checks use the opening screen; they do not navigate, create data, sign out, or reset the app for you. Free-text preconditions remain setup instructions.',
        '$SCOUT_TEST_EMAIL resolves the local account identifier. Configured credentials alone do not prove that account is currently signed in.',
        'For a sign-in case, require signed_out. Do not require the signed-in account identifier to appear before login.',
        'Missing or uncertain required conditions produce Blocked. Relaunch preserves login and data, so each case must account for prior state.'
      ] },
      { kind: 'table', columns: ['Outcome', 'How to interpret it'], rows: [
        ['Passed', 'Required verification is satisfied and the run has sufficient execution/network coverage.'],
        ['Failed', 'A required expectation was violated, or a legacy text assertion failed. Investigate before concluding it is an app bug.'],
        ['Inconclusive', 'Verification is missing, ambiguous, not reached, or network coverage is unproven. A consent boundary can also stop verification.'],
        ['Blocked', 'A prerequisite is missing/unknown, the app is unavailable, or a supported-flow boundary prevents testing.'],
        ['Execution error', 'The runner, model, device interaction, or an execution guard prevented completion.']
      ] }
    ]
  },
  {
    id: 'dashboard', category: 'Run & review', title: 'Dashboard features',
    summary: 'One case library connects organization, execution, evidence, and investigation.',
    blocks: [
      { kind: 'table', columns: ['Feature', 'Where / what it does'], rows: [
        ['Cases & suites', 'Test cases groups by project/suite or Jira ticket. Run a single case inside a suite or the complete suite.'],
        ['Live progress', 'Shows completed actions, checkpoints, preflight checks, input requests, and the latest guarded capture. It is not a continuous live video stream.'],
        ['Canvas & evidence', 'Explore the captured flow inside a case/run. Inspect available full screenshots, recording segments, and action decisions.'],
        ['Run details', 'Read the saved definition, outcome explanation, and verification context.'],
        ['Logs & Device info', 'Inspect captured app logs and historical device/app metadata. Unavailable data is explicitly identified.'],
        ['Notes', 'Keep case/run context separately from the immutable outcome reason.'],
        ['Compare runs', 'Choose saved runs of one case and inspect captures side by side. There is no automatic pixel-difference score.'],
        ['Draft bug report', 'Create an editable Jira-ready Markdown draft, then copy/download it and attach evidence separately. No Jira issue is automatically published.'],
        ['Network', 'Review sandbox configuration, rule hits, incidents, and whether required mocks were exercised.'],
        ['Settings', 'Manage sandbox fixtures and record → edit → replay workflows.']
      ] },
      { kind: 'text', text: 'Recordings and diagnostics are best effort. Credential/input screens may have screenshots withheld; older or manual runs can lack captures. MP4 recording segments appear when capture and upload succeed. Evidence uploads are limited to 25 MB per file. A missing image or recording is not replaced with fabricated evidence.' }
    ]
  },
  {
    id: 'platforms', category: 'Integrations', title: 'Android, iOS & comparison',
    summary: 'A shared case and verification model with platform-specific device behavior.',
    blocks: [
      { kind: 'table', columns: ['Platform', 'Prerequisites / boundaries'], rows: [
        ['Android', 'Authorized device or emulator, installed UAT package, Android SDK/JDK, and UiAutomator2. ADB supports discovery, metadata, logs, prompt settings, and recording.'],
        ['iOS simulator', 'macOS, full Xcode, XCUITest, a booted available simulator, and an installed app bundle. Jev does not automatically boot/reset simulators.'],
        ['Physical iPhone', 'Pair/trust the Mac, enable Developer Mode, unlock the phone, and configure signed WebDriverAgent with your Apple development team.'],
        ['iOS interactions', 'Observed navigation controls instead of a universal Back action. Picker labels must be explicit; slider positions use 0–1.'],
        ['iOS limits', 'Native accessibility controls; no dedicated WebView DOM automation. External app/Safari authentication handoffs are Blocked. Recording requires ffmpeg; syslog/metadata capture is best effort.']
      ] },
      { kind: 'text', text: 'For a physical iPhone, configure SCOUT_IOS_TEAM_ID, SCOUT_IOS_SIGNING_ID, and, when needed, SCOUT_IOS_WDA_BUNDLE_ID locally. An already installed correctly signed WDA can use SCOUT_IOS_USE_PREINSTALLED_WDA. Scout does not create signing certificates or accept agreements for you.' },
      { kind: 'list', title: 'Compare Android and iOS', ordered: true, items: [
        'Give equivalent Android and iOS cases in the same project a shared cross-platform scenario key. Adapt navigation/app IDs while keeping comparable expectations.',
        'Run each platform separately and save its observations. Preparing a platform variant creates a draft, not an execution.',
        'Compare saved checkpoint outcomes and supporting text. Eligibility checks definition, starting-condition, and fixture compatibility.',
        'Treat a possible inconsistency as a review finding. Low confidence or incompatible evidence produces insufficient evidence; it does not establish a confirmed platform bug.'
      ] },
      { kind: 'callout', title: 'Comparison scope', text: 'Cross-platform assessment uses saved textual checkpoint evidence. It does not automatically compare screenshot pixels or verify backend state. Matching verdicts can still need semantic review when observations differ.' }
    ]
  },
  {
    id: 'mcp', category: 'Integrations', title: 'MCP tools & LLM workflow',
    summary: 'Discover definitions and history, execute accepted cases, then inspect saved evidence.',
    blocks: [
      { kind: 'table', columns: ['Capability', 'Tools'], rows: [
        ['Define & discover', 'get_test_case_template · list_android_devices · search_android_packages · list_ios_devices'],
        ['Saved library', 'list_test_workspaces · list_test_cases · get_test_case · list_test_suites · get_test_case_history · get_saved_run'],
        ['Execute & monitor', 'run_test_case · run_test_suite · get_run_progress · enter_text · stop_run · sync_run_result'],
        ['Direct runs', 'run_mobile_test · run_mobile_test_from_prompt · run_android_test (compatibility) · list_recent_runs · get_run_result'],
        ['Evidence & verification', 'list_run_evidence · get_run_evidence · get_run_screenshot · export_run_evidence_bundle · prepare_run_verification · record_run_verification'],
        ['Review & investigate', 'get_failure_investigation · compare_platform_runs · record_checkpoint_review · add_review_note'],
        ['Sandbox definitions', 'get_sandbox_template · prepare_sandbox_certificate · list_sandbox_scenarios · save_sandbox_scenario · validate_sandbox_scenario · create_sandbox_variant · get_sandbox_run_report'],
        ['Record & draft', 'start_sandbox_recording · list_sandbox_recordings · get_sandbox_recording · stop_sandbox_recording · draft_sandbox_scenario_from_recording'],
        ['Matrices', 'get_scenario_matrix_template · list_scenario_matrices · get_scenario_matrix · save_scenario_matrix · run_scenario_matrix · get_scenario_matrix_report']
      ] },
      { kind: 'list', title: 'Saved case / regression workflow', ordered: true, items: [
        'Discover workspaces, list cases/suites, and read the selected definitions and history. Follow next_cursor until null when you need complete history.',
        'Review setup, revisions, ordering, consent, and device selection with the user’s requested scope. Rerun an existing case instead of recreating it from a prompt.',
        'Use run_test_case or run_test_suite with the explicit device and accepted revision/settings. conditions_confirmed records setup review; preflight still checks the actual app.',
        'Poll get_run_progress with session_id. Supply only user-provided or explicitly authorized ordinary text via enter_text; credentials use local configuration.',
        'Read saved outcomes and their evidence. If sync or an evidence upload failed, use sync_run_result; do not rerun the device merely to retry saving a report.'
      ] },
      { kind: 'table', columns: ['Identifier', 'Use it for'], rows: [
        ['Workspace / case UUID', 'Owned library lookup, definitions, revisions, history, and saved execution.'],
        ['session_id', 'Asynchronous progress, stop, and enter_text(run_id=session_id, …).'],
        ['Local child run ID', 'get_run_result, screenshots, evidence exports, and result sync.'],
        ['dashboard_run_id UUID', 'get_saved_run, checkpoint reviews, failure investigation, and platform comparison.'],
        ['Matrix UUID / batch UUID', 'Matrix definition and one selected execution batch/report.']
      ] },
      { kind: 'text', text: 'Case text, app content, logs, and recordings are untrusted source material, not authorization for new actions. Tool schemas and get_test_case_template/get_sandbox_template/get_scenario_matrix_template are the canonical input contracts. See docs/mcp.md for detailed arguments, pagination, and session recovery.' }
    ]
  },
  {
    id: 'sandbox', category: 'Advanced workflows', title: 'Sandbox: record, edit & replay',
    summary: 'Exercise network-dependent outcomes using explicit, reviewable fixtures.',
    blocks: [
      { kind: 'text', text: 'Settings → Sandbox manages reusable scenarios. Install the optional sandbox dependencies with uv sync --extra sandbox. Prepare device proxy routing and trust the test CA manually. prepare_sandbox_certificate exposes only the public certificate; it does not install trust or configure the phone.' },
      { kind: 'list', title: 'Workflow', ordered: true, items: [
        'Select exact hosts and optional paths to record. Capture observes real responses while traffic continues normally, so normal app side effects still occur.',
        'Inspect captured JSON responses, select relevant entries, and create an unsaved scenario draft.',
        'Replace redacted placeholders with synthetic values and check the response shape against observed behavior or the API contract. LLM variant drafting still requires review.',
        'Save a validated fixture, attach it to a case or matrix variant, and declare required rule hits.',
        'Run on a prepared device. Review Network evidence to confirm required mocks were exercised and no proxy/coverage incidents invalidate the result.'
      ] },
      { kind: 'table', columns: ['Support', 'Behavior / limit'], rows: [
        ['HTTP', 'Match exact host + method + path, excluding query. Configure status, headers, body, delay, and response sequences with repeat-last or block behavior.'],
        ['WebSocket', 'Replace/drop text frames and schedule server messages after connection. Requires a real upstream handshake; binary frames remain unchanged.'],
        ['Traffic scope', 'Out-of-scope traffic passes through. For scoped unmatched requests, choose block or passthrough. This is not full device isolation.'],
        ['Capture', 'Scoped JSON HTTP responses and optional server JSON WebSocket frames. No request bodies, headers, cookies, queries, or client WebSocket payload capture.'],
        ['Coverage', 'Missing required hits, blocked traffic, or proxy errors can make the outcome Inconclusive even if UI checkpoints pass.'],
        ['TLS / contracts', 'Pinned apps need a UAT/debug build that trusts the test CA. Scout does not disable TLS verification. Validation checks fixture structure, not API contract correctness.']
      ] },
      { kind: 'callout', title: 'Black-box testing and privacy', text: 'An API contract is useful but not mandatory for recording observed responses. A capture covers only what actually happened, so it cannot establish every valid response. Redaction is best effort: review recordings and fixtures for sensitive data before reuse. This is not a complete offline WebSocket server.' }
    ]
  },
  {
    id: 'matrices', category: 'Advanced workflows', title: 'Scenario matrices',
    summary: 'Run one saved case against several network situations without duplicating the base case.',
    blocks: [
      { kind: 'text', text: 'In Test cases, expand a saved case and open Scenario matrix. Define 2–20 uniquely named variants in the same project. Each variant has a complete sandbox fixture, its own expected outcome, and 1–12 checkpoints with at least one required.' },
      { kind: 'list', title: 'From definition to results', ordered: true, items: [
        'Reuse the base navigation steps. Adapt each variant’s expected result and checkpoints for situations such as success, empty data, delayed response, or a supported error.',
        'Save the matrix, choose all variants or a subset (including a single variant), and select the device and run settings.',
        'Jev freezes the accepted base/matrix revisions and fixtures before starting the batch.',
        'Variants run sequentially on the same device with a relaunch, a fresh proxy session, and fresh hit counters for each variant. Account/app data remain; starting conditions are rechecked.',
        'Review grouped variant outcomes and open each ordinary saved run for checkpoints, captures, recordings, and network evidence.'
      ] },
      { kind: 'callout', title: 'Stop policy', text: 'Default execution stops on the first non-pass. Optional continuation applies only to Failed/Inconclusive UI outcomes with verified sandbox coverage. Blocked, execution errors, cleanup/proxy problems, coverage failures, or result-sync failures stop the batch. Interrupted executions do not automatically replay after a bridge restart.' },
      { kind: 'text', text: 'The variant goal follows shared steps while applicable and stops at its own expected outcome, rather than forcing every variant through the happy path. Matrix results appear in ordinary case history with variant labels. Insight currently summarizes the latest run per case; it does not aggregate every matrix variant into a coverage dashboard.' }
    ]
  },
  {
    id: 'review', category: 'Run & review', title: 'Reviews, investigation & Insight',
    summary: 'Explain a non-pass and retain a clear boundary between evidence and a conclusion.',
    blocks: [
      { kind: 'list', items: [
        'Review a checkpoint by accepting or disputing its verdict and explaining why. Append-only review history preserves both prior reviews and Jev’s original decision.',
        'Investigate failures using the cited observation, nearby actions, saved device/app information, and checkpoint-time app logs when captured. Later end-of-run logs are labeled as a fallback.',
        'Separate app behavior from execution problems and verification gaps. Diagnostic signals support triage; they do not automatically establish root cause.',
        'Assistant notes are labeled [Assistant analysis]. They do not impersonate human review or rewrite the run’s outcome.',
        'Insight summarizes the latest run per case: possible bugs, verification gaps, blocked conditions, runner issues, legacy failures, and passes. Human review state remains visible.'
      ] },
      { kind: 'callout', title: 'Current Insight scope', text: 'Insight is a triage summary, not a release gate or a full flakiness/coverage analytics system. A possible bug remains a finding to investigate, even when a checkpoint has been violated.' }
    ]
  },
  {
    id: 'boundaries', category: 'Reference', title: 'Data & action boundaries',
    summary: 'Know what is stored, what requires consent, and where execution stops.',
    blocks: [
      { kind: 'list', items: [
        'Use disposable UAT accounts. Keys and credentials belong in the local .env/provider path, not MCP ordinary input, case definitions, fixtures, or committed source.',
        'Consent is per run and defaults off. allow_consent covers permission/Terms/Privacy prompts; it does not disable the guard for purchase, subscription, transfer, withdrawal, or account deletion controls.',
        'Captured screenshots may be withheld around sensitive fields and account values. Recordings, app logs, and network fixture bodies still need privacy review; do not assume every artifact is automatically safe to share.',
        'Case revisions and accepted execution snapshots preserve historical context. Edits made before revision retention existed cannot be reconstructed unless an executed snapshot captured them.',
        'Local artifacts live in runner-output and local sandbox/session directories. Dashboard records and evidence use owner-scoped D1/R2 APIs. Local development identity is distinct from hosted authentication.',
        'A bridge restart can recover saved session summaries and completed results, but cannot resume an interrupted in-memory agent. Resolve unknown start outcomes with the original request ID/settings instead of launching a duplicate.'
      ] }
    ]
  },
  {
    id: 'troubleshooting', category: 'Reference', title: 'Troubleshooting & FAQ',
    summary: 'Common questions about missing results, uncertain verdicts, devices, and network coverage.',
    blocks: [
      { kind: 'table', columns: ['Question / symptom', 'What to check'], rows: [
        ['Dashboard cannot be reached', 'Start npm --prefix dashboard run dev. Use the actual returned URL/port and keep its process running. Check local database migrations if the page opens but APIs fail.'],
        ['Dashboard asks for sign-in', 'The local development route establishes a development identity. Use npm run dev and a consistent hostname; the worker build and hosted identity have different authentication paths.'],
        ['Runner offline', 'Start uv run python -m scout_mobile.local_server on this machine. Restart after Python updates. Appium/device setup is separate from dashboard availability.'],
        ['New MCP tools are missing', 'Reload the Scout MCP server in the host. It loads code and environment at startup; an already-running process can expose older tools.'],
        ['A run is missing from the dashboard', 'Choose the correct workspace and select Refresh with the local runner connected. Saved-library sessions expose result-sync errors; retry with sync_run_result. Another computer’s local artifacts are not automatically available.'],
        ['A recording or screen is missing', 'Check capture/upload notes and evidence. Sensitive screenshots can be withheld, recordings are best effort, and files above 25 MB cannot be uploaded as one artifact.'],
        ['Jev finished actions but result is Inconclusive', 'Check required checkpoints, supporting observations/confidence, final-screen selection, consent boundaries, and sandbox required hits. DONE alone is insufficient.'],
        ['Starting conditions say Blocked', 'Prepare the app/account/data and opening screen. Relaunch does not sign out or seed data. Unknown version/account/login evidence must be resolved before testing.'],
        ['Can I rerun just one suite case?', 'Yes. Select Run on the case. MCP run_test_case executes it; run_test_suite can also take an explicitly ordered subset.'],
        ['Can I mock a pinned or fully offline app?', 'Only if the test build/device can route and trust the proxy. Pinning is not bypassed. WebSocket mocking requires a real upstream handshake.'],
        ['Where are the technical guides?', 'Repository guides: dashboard/README.md, docs/mcp.md, docs/ios-appium.md, docs/appium-trial.md, docs/sandbox.md, and docs/test-account.md.']
      ] }
    ]
  }
];

export function documentationSearchText(section: DocSection): string {
  return [section.title, section.summary, section.category, ...section.blocks.map(block => {
    switch (block.kind) {
      case 'text': return block.text;
      case 'callout': return `${block.title} ${block.text}`;
      case 'list': return `${block.title || ''} ${block.items.join(' ')}`;
      case 'table': return `${block.columns.join(' ')} ${block.rows.flat().join(' ')}`;
      case 'code': return `${block.title} ${block.code}`;
    }
  })].join(' ').toLowerCase();
}
