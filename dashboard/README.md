# Jev Mobile dashboard

Workspace-based dashboard for Android/iOS test cases, manual results, imported Jev Android runner results, and evidence. The Test cases tree nests runs and evidence under each project, ticket, and test case; Canvas shows the visual execution flow. Create a workspace per app, team, or environment; switching workspaces scopes the case library, run history, and evidence together. Existing records are migrated into workspaces named after their current project labels, including orphaned historical runs using their saved report snapshot.

Create a workspace for an app, team, or environment, then keep its cases, runs, and evidence in that space. Use project labels to group work further inside a workspace. Add an Android package or iOS bundle ID, goals, steps, expected results, and an optional exact visible-text assertion to each case. Export a case to `jev_mobile`, then import the runner's `result.json` into the Test cases tree. Prompt-driven MCP runs are synced from the local bridge into the dashboard with their artifacts, without requiring a saved case first. The dashboard stores each run's test revision and action timeline. Expand a Jev decision to inspect its request questions, selected answers, option probabilities, confidence, model, latency, and request/response JSON. The runner also writes `jev-output.json` for standalone analysis. Attach screenshots, videos, or logs to the run; uploads are limited to 25 MB per file. Canvas groups cases by project and ticket and plays attached screen recordings alongside the latest run.

The dashboard does not directly control a USB device. The Android runner is local and described in the [workspace README](../README.md). The installed AI Avatar UAT build currently rejects the emulator before its authentication screen, so there is no verified login test yet.

## Prompt-run report sync

When an MCP `run_android_test_from_prompt` call completes, it returns a dashboard URL containing the project and local run ID. The MCP server starts the local dashboard and bridge on demand when dashboard dependencies are installed. Opening the URL imports the run, saves an on-demand test snapshot, uploads its evidence, deduplicates the run, and opens the report. **Test cases → Sync MCP runs** imports local prompt runs and retries missing evidence without duplicating cases or runs. Runs retain a compact decision summary in their timeline; the full Jev request/response is kept in the `jev-output.json` evidence file. Project names are labels entered on cases or supplied to MCP; use consistent project labels to filter the Canvas and test library.

## Run Jev from the dashboard

The dashboard UI runs in a local worker-style runtime, so it cannot call ADB itself. Prompt-driven MCP runs start the local bridge automatically. To run a saved case manually, start the bridge from the workspace root:

    python3 -m jev_mobile.local_server

Keep that terminal open. The dashboard shows **Device runner ready** when it can reach the bridge. In **Test cases**, click **Run Jev** on an Android case. The bridge runs Jev on the connected device, temporarily suppresses Android credential prompts, then restores the original device settings. The dashboard saves the run and uploads its result, Jev audit, trace, screenshots, and screen-recording clips automatically. The bridge listens only on localhost and accepts browser requests from the local dashboard.

## Local development

Requires Node.js >=22.13.0. From this directory:

```sh
npm ci
npm run build
node --import ./scripts/sites-env.mjs ./node_modules/wrangler/bin/wrangler.js d1 execute DB --local --config dist/server/wrangler.json --persist-to .wrangler/state --file drizzle/0000_common_cardiac.sql
node --import ./scripts/sites-env.mjs ./node_modules/wrangler/bin/wrangler.js d1 execute DB --local --config dist/server/wrangler.json --persist-to .wrangler/state --file drizzle/0001_famous_living_lightning.sql
node --import ./scripts/sites-env.mjs ./node_modules/wrangler/bin/wrangler.js d1 execute DB --local --config dist/server/wrangler.json --persist-to .wrangler/state --file drizzle/0002_projects_and_prompt_runs.sql
node --import ./scripts/sites-env.mjs ./node_modules/wrangler/bin/wrangler.js d1 execute DB --local --config dist/server/wrangler.json --persist-to .wrangler/state --file drizzle/0003_project_app_ids.sql
node --import ./scripts/sites-env.mjs ./node_modules/wrangler/bin/wrangler.js d1 execute DB --local --config dist/server/wrangler.json --persist-to .wrangler/state --file drizzle/0004_clammy_mysterio.sql
node --import ./scripts/sites-env.mjs ./node_modules/wrangler/bin/wrangler.js d1 execute DB --local --config dist/server/wrangler.json --persist-to .wrangler/state --file drizzle/0005_brown_callisto.sql
node --import ./scripts/sites-env.mjs ./node_modules/wrangler/bin/wrangler.js d1 execute DB --local --config dist/server/wrangler.json --persist-to .wrangler/state --file drizzle/0006_canvas_ticket_keys.sql
node --import ./scripts/sites-env.mjs ./node_modules/wrangler/bin/wrangler.js d1 execute DB --local --config dist/server/wrangler.json --persist-to .wrangler/state --file drizzle/0007_verification_checkpoints.sql
node --import ./scripts/sites-env.mjs ./node_modules/wrangler/bin/wrangler.js d1 execute DB --local --config dist/server/wrangler.json --persist-to .wrangler/state --file drizzle/0008_run_diagnostics_notes.sql
node --import ./scripts/sites-env.mjs ./node_modules/wrangler/bin/wrangler.js d1 execute DB --local --config dist/server/wrangler.json --persist-to .wrangler/state --file drizzle/0009_checkpoint_reviews.sql
node --import ./scripts/sites-env.mjs ./node_modules/wrangler/bin/wrangler.js d1 execute DB --local --config dist/server/wrangler.json --persist-to .wrangler/state --file drizzle/0010_starting_conditions.sql
npm run dev
```

Apply each migration only once to a local database. Existing checkouts need only migrations they have not already applied. Migration `0002_projects_and_prompt_runs.sql` adds project labels and MCP-run deduplication; `0003_project_app_ids.sql` adds the Android package or iOS bundle ID per case; `0004_clammy_mysterio.sql` adds workspaces and groups existing records by project label; `0005_brown_callisto.sql` adds workspace lookup indexes; `0006_canvas_ticket_keys.sql` adds an optional Jira ticket key used by Canvas. The bundled local sign-in route creates a development identity; production identity is supplied by the hosting platform.

```sh
npx tsc --noEmit
python3 checks/api-smoke.py
```

The API smoke check creates labeled synthetic records in the local development database. It verifies validation, revision conflicts, immutable snapshots, imports, uploads, byte-range downloads, and access rejection. Local data is ignored by Git and is not deployed.

## Structure

- `app/workspace.tsx`: test library, run history, evidence viewer, and Jev import/export.
- `app/api/`: authenticated cases, runs, evidence upload/download endpoints.
- `lib/contracts.ts`: shared validation and types.
- `db/schema.ts` and `drizzle/`: database schema and migrations.
- `.openai/hosting.json`: logical hosting and storage declarations.

## Sign-in or sync problems on another machine

For a local dashboard use `npm run dev` and open `http://localhost:5173` on the same machine as Jev. The local **Sign in with ChatGPT** route creates the bundled development identity; it does not require a real ChatGPT account. Use the same hostname consistently because `localhost` and `127.0.0.1` have separate sign-in cookies. `npm start` serves the worker build and does not install the development sign-in middleware.

If the runner shows offline, start `python3 -m jev_mobile.local_server` from the repository root on that machine, then use **Test cases → Sync MCP runs**. The bridge reads that checkout's `runner-output`, not runs stored on another computer. Fresh checkouts also need the local database migrations listed above and a workspace before importing runs. Hosted dashboards cannot reach this loopback-only bridge through the local development workflow.

Dashboard readiness uses `/api/health`, independently of sign-in. MCP starts the bridge even while the dashboard is starting, and report links preserve their run ID through sign-in.

### Suites, live execution, comparison, and bug drafts

- **Test cases** is the combined case and suite library. It groups by project and suite by default; use **Group by → Jira ticket** to switch grouping. **Organize suites** exposes case selection and assignment controls. **Run suite** runs the entire named suite, including cases hidden by filters. Select cases and enter a suite name to move them, or create a case in a suite. Jira keys remain optional. Membership edits create a new case revision; old run snapshots are unchanged.
- **Run again / Run suite** opens a setup dialog. Choose an authorized Android serial, review every case's preconditions, arrange suite execution order, and choose existing app state or force-stop/relaunch. Relaunch preserves app data and login. All selected cases need their Android package ID. Suites stop on the first non-passing outcome.
- The local bridge exposes `POST /jobs`, `GET /jobs/:id`, `POST /jobs/:id/input`, and `POST /jobs/:id/stop`. Jobs run in background threads under the existing dashboard execution lock. Progress includes completed actions and the latest agent-approved screenshot; credential screens can be withheld. Stop takes effect at the next action boundary. Ordinary text requests pause for user input and expire after 15 minutes. Credentials stay in the existing local runner configuration.
- The browser stores its active queue in session storage and resumes polling after a reload in the same tab. Final results and recordings are imported through the existing authenticated dashboard APIs. A completed result can be recovered after a bridge restart; an interrupted in-memory agent cannot resume. Keep the dashboard tab open to advance a suite and sync results.
- **Compare runs** is available from a run header. Choose another saved run of the same case and independently select the captured steps to compare. This is visual side-by-side comparison, not automatic image-difference scoring.
- **Draft bug report** is available on non-passing runs. Choose a captured step, regenerate and edit the draft, then copy or download Markdown. Evidence downloads are provided separately for Jira attachment. No Jira issue is created automatically.
- Restart `python3 -m jev_mobile.local_server` after updating Python bridge code; the Vite UI refreshes independently.


### Checkpoint verification and Insight

Cases accept up to 12 checkpoints. Each has a unique `id`, observable `expected`, `scope` (`during_run` or `final`), `required` boolean, and `method` (`classification`, `text_present`, `text_absent`). At least one checkpoint must be required. Define them in the case editor; they persist in case revisions, JSON exports, and run snapshots. Old cases retain their legacy assertion behavior.

- `during_run` is an occurrence checkpoint: evaluate as observations arrive and retain the first supported satisfied/violated decision. It is not a continuously enforced invariant. Transient captured evidence can satisfy it before leaving a screen.
- `final` evaluates only the final observation, when the navigation agent reports DONE (or a read-only verification runs).
- Jev classification selects a verdict and a supporting observed step. The request includes the explicit expectation and up to eight recent observations; final checkpoints only receive the last one. Evidence includes redacted accessibility text/control state, not screenshot pixels or server-side state. A supported satisfied/violated decision needs both answer and evidence confidence at least 0.85. This is an operational threshold, not calibrated certainty.
- Literal checks are case-insensitive substring checks. Empty screen text is unknown. An unmatched during-run literal checkpoint stays not reached until final evaluation.
- Required violations produce Failed; all required checkpoints must be satisfied for Passed at normal completion. Missing/ambiguous/unreached requirements yield Inconclusive. Execution errors retain their outcome and checkpoint evidence. Optional checkpoints do not decide overall pass/fail.
- Reports include verdict, expected behavior, confidence/method, reason, observed data, and referenced trace steps. Screenshot links appear when a captured artifact exists. Credential screenshot restrictions remain in effect. The final trace event `VERIFY_CHECKPOINTS` carries the structured report.
- Insight shows the latest run per case. Required checkpoint violations are **possible bugs**, not confirmed defects; missing evidence is a verification gap. Old failures stay in a separate legacy category. Existing runs are not retroactively classified.

MCP callers should call `get_test_case_template` before authoring tests. `run_android_test_from_prompt` exposes a typed checkpoint schema plus suite, preconditions, and ticket key. New calls need checkpoints or a legacy text assertion. Explore the app, map each acceptance criterion to an observable expectation, and avoid inventing evidence for backend-only or pixel-only requirements. Checkpoints take precedence over `assertion_text` when provided. Restart/reload the MCP server to publish the updated tool schema.

### Logs, device info, and review notes

- Each run has separate **Logs**, **Device info**, and **Notes** tabs. Runner logs are derived from the saved outcome, trace, and checkpoint decisions. Filter or search them, open captured step screenshots, and download a text copy.
- Android app logs are a bounded `logcat` tail scoped to the app process when the process is still available at run completion. Known local test credentials and email addresses are redacted. They may be empty on old/manual runs or when Android cannot provide a process log. No historical logcat is fabricated.
- New Jev results save manufacturer, model, Android version/API level, screen size, package, and app version when ADB provides them. The dashboard stores these with the run, so later device changes do not rewrite past metadata. Older and manual runs show fields as not captured.
- Case and run notes are separate from Jev's immutable outcome reason. Notes can be added, edited, or deleted; each record keeps creation and last edit timestamps. Notes are scoped to the signed-in workspace owner. The local database needs migration `0008_run_diagnostics_notes.sql` once.

### Human checkpoint review and failure investigation

- Open a saved run with structured checkpoints to **accept** or **dispute** each Jev verdict and explain why. Reviews are appended with timestamps; the current review and prior decisions remain visible. Jev's original verdict, run status, and evidence are never rewritten by a review. Insight marks findings as awaiting review, accepted, or disputed without silently recategorizing the original run.
- When a new run marks a checkpoint violated, Jev captures a bounded app-process log excerpt, foreground package, app-process state, and capture time at that decision. The checkpoint's **Investigate failure** section links the cited screenshot, nearby runner actions, those diagnostic signals, and the run's saved device/app metadata. If checkpoint-time logs are missing, it identifies end-of-run logs as a later fallback. The view supplies evidence for human triage; it does not declare an app bug or a runner error automatically.
- Migration `0009_checkpoint_reviews.sql` adds append-only review records. Existing checkpoint runs have no checkpoint-time diagnostic snapshot; new runs populate it. Case/run exports include saved human reviews where applicable.

### Starting conditions and Blocked runs

- A case can define an exact installed app version, required login state (`signed_in` or `signed_out`), a visible account identifier, and up to eight text values that must appear on the opening screen. Free-text Preconditions remain setup guidance; only the structured fields are checked automatically. `$JEV_TEST_EMAIL` resolves to the runner's locally configured test account without storing its address in the case.
- Jev launches and observes the app, then checks starting conditions before the first test action. Version uses Android package metadata. Account and required data use case-insensitive visible text. Login state uses a conservative Jev classification of the opening screen; missing model access, ambiguous evidence, or confidence below 0.85 is unknown. Unknown or missing requirements stop the run as **Blocked**. A missing app package is also Blocked.
- Every check records expected, observed, status, and reason in the saved trace and run UI. Blocked is distinct from an app assertion failure or runner error, and stops suite progression. Previous cases have no automated starting checks until they are edited. New prompt-driven MCP cases can provide `starting_conditions`; the test-case template documents the same contract.

### Android backend

Appium is the default. Follow [Appium setup](../docs/appium-trial.md) once, then
start the bridge with `uv run python -m jev_mobile.local_server`. The installed
local Appium server starts on demand. `JEV_ANDROID_DRIVER=adb` explicitly selects
the previous backend. Restart the bridge and MCP server after switching backends.
