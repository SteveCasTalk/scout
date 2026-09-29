# Jev Mobile dashboard

Workspace-based dashboard for Android/iOS test cases, manual results, imported Jev Android runner results, and evidence. Create a workspace per app, team, or environment; switching workspaces scopes the case library, run history, and evidence together. Existing records are migrated into workspaces named after their current project labels, including orphaned historical runs using their saved report snapshot.

Create a workspace for an app, team, or environment, then keep its cases, runs, and evidence in that space. Use project labels to group work further inside a workspace. Add an Android package or iOS bundle ID, goals, steps, expected results, and an optional exact visible-text assertion to each case. Export a case to `jev_mobile`, then import the runner's `result.json` into Test runs. Prompt-driven MCP runs are synced from the local bridge into the dashboard with their artifacts, without requiring a saved case first. The dashboard stores each run's test revision and action timeline. Expand a Jev decision to inspect its request questions, selected answers, option probabilities, confidence, model, latency, and request/response JSON. The runner also writes `jev-output.json` for standalone analysis. Attach screenshots, videos, or logs to the run; uploads are limited to 25 MB per file.

The dashboard does not directly control a USB device. The Android runner is local and described in the [workspace README](../README.md). The installed AI Avatar UAT build currently rejects the emulator before its authentication screen, so there is no verified login test yet.

## Prompt-run report sync

When an MCP `run_android_test_from_prompt` call completes, it returns a dashboard URL containing the project and local run ID. Open that URL while the dashboard and local bridge are running. The dashboard imports the prompt run, saves an on-demand test snapshot under the named project, uploads its evidence, deduplicates repeated syncs, and opens the report. Alternatively, choose **Test runs → Sync MCP runs** to import local prompt runs. Project names are labels entered on cases or supplied to MCP; use consistent names such as `Arcana` and `AI Avatar` to filter their reports separately.

## Run Jev from the dashboard

The dashboard UI runs in a local worker-style runtime, so it cannot call ADB itself. Start the local Jev bridge in a second terminal from the workspace root:

    python3 -m jev_mobile.local_server

Keep that terminal open. The dashboard shows **Device runner ready** when it can reach the bridge. In **Test cases**, click **Run Jev** on an Android case. The bridge runs Jev on the connected device, temporarily suppresses Android credential prompts, then restores the original device settings. The dashboard saves the run and uploads its result, Jev audit, trace, and screenshots automatically. The bridge listens only on localhost and accepts browser requests from the local dashboard.

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
npm run dev
```

Apply each migration only once to a local database. Existing checkouts need only migrations they have not already applied. Migration `0002_projects_and_prompt_runs.sql` adds project labels and MCP-run deduplication; `0003_project_app_ids.sql` adds the Android package or iOS bundle ID per case; `0004_clammy_mysterio.sql` adds workspaces and groups existing records by project label; `0005_brown_callisto.sql` adds workspace lookup indexes. The bundled local sign-in route creates a development identity; production identity is supplied by the hosting platform.

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
