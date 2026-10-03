# Scout

[Source repository](https://github.com/SteveCasTalk/scout)

Scout is a mobile testing platform for Android and iOS. It brings test authoring, automation, checkpoint verification, evidence, sandbox scenarios, and human review into one workspace. Its future mascot is a curious fox that explores apps and investigates results.

The current execution engine adapts the [Jev Ultrafast](https://github.com/browser-use/jev-ultrafast) observe–choose–act design with Appium device control. Jev is one component of Scout, alongside the dashboard, MCP tools, network sandbox, scenario matrices, and review workflows.

## Naming and migration

Python source lives in `scout_mobile/`; launch the CLI with `scout` and MCP with `scout-mcp`. Settings use the `SCOUT_*` prefix. See [rename and compatibility notes](docs/rebranding.md) for existing configuration and historical results.

## Documentation

Open **Documentation** in the dashboard sidebar or visit `/docs` on its active local URL (normally [localhost:5173/docs](http://localhost:5173/docs)). The searchable product guide covers concepts, philosophy, setup, Android/iOS, MCP tools, verification, sandbox replay, scenario matrices, reviews, and troubleshooting. It contains no account data and can be read without signing in. Technical setup guides remain in `docs/` and `dashboard/README.md`.

## Current state

- `dashboard/`: create and revise test cases, record manual runs, import Scout runner results, inspect per-step questions, answers, probabilities, confidence, and latency, attach evidence, and review saved test snapshots.
- `scout_mobile/`: Python runner using native accessibility observations plus TypeSafe's Jev model to choose an indexed operation and target. It re-observes targets before acting and verifies required checkpoints before reporting Passed.
- MCP server: local tools for device discovery, Scout test execution, run history, and result inspection; see [MCP setup](docs/mcp.md).
- Saved-library MCP tools discover cases/suites, inspect revisions, rerun cases or regressions, and monitor asynchronous progress with results synced to the local dashboard.
- Analysis MCP tools draft sandbox variants, inspect network coverage and failure diagnostics, compare Android/iOS runs, and append reviews or labeled assistant notes.
- Scenario matrices run one saved case against several fixtures with variant-specific checkpoints, frozen snapshots, live progress and grouped results in the dashboard or MCP.
- `.env`: local, Git-ignored owner-only UAT credentials and model keys. Copy `.env.example` if needed, then fill values locally; see [test account setup](docs/test-account.md). **Do not send credentials in chat or put them in test cases.**

The runner supports Android through Appium/UiAutomator2 and iOS through Appium/XCUITest on macOS. Jev chooses operations and targets; Appium provides native observations, actions, and screenshots. ADB supports Android discovery, diagnostics, prompt settings, and recording. ARTEMIS is not used by the runner. It captures an action trace and screenshots, including an authenticated outcome screen when no input field or account value is visible. The runner also captures screen-recording clips on both platforms when recording prerequisites are available for each execution segment; Jev and dashboard imports attach the MP4 clips to the test run when they are available.

## Run from the dashboard

Prompt-driven MCP runs start the local dashboard and device bridge on demand when the dashboard dependencies are installed. The returned dashboard link uses the active local port, so it remains openable when the default port is already occupied. For manually launched dashboard runs, start the dashboard with `cd dashboard && npm run dev` and the local device bridge with `uv run python -m scout_mobile.local_server`; runs and safe evidence are saved automatically. See [dashboard runner setup](dashboard/README.md#run-scout-from-the-dashboard).

## Run a case

Appium is the default Android backend and starts automatically when installed.
Complete the [Appium setup](docs/appium-trial.md) once. Use `--driver adb` only
when explicitly choosing the previous backend.

1. Add a test case in the dashboard with its platform and app ID. Define observable required checkpoints; a literal visible-text assertion remains available as a legacy fallback.
2. Export the case JSON from the Test cases table.
3. Fill the local `.env` with `TYPESAFE_API_KEY`, `SCOUT_TEST_EMAIL`, and `SCOUT_TEST_PASSWORD` for a disposable UAT account. The text-model key is needed only for non-credential text fields.
4. Run with an attached, authorized Android device:

```sh
python3 -m scout_mobile --case /absolute/path/to/jev-case.json --package com.wallet.walkthedog.uat --serial DEVICE_SERIAL --adb /Users/phucnguyen/Library/Android/sdk/platform-tools/adb
```

By default, each run temporarily disables Android autofill and credential providers, which prevents Samsung Pass and Google Password Manager save-password dialogs from blocking Jev. It also temporarily grants and silences Android 13+ notification permission so its runtime prompt does not block the test. The runner restores the device's original settings and notification permission when the run ends, including after a test failure. Use `--allow-device-prompts` to keep autofill and credential providers enabled for a CLI run; notification prompts remain suppressed. The runner still dismisses recognized prompts if one appears despite the device setting.

The runner writes `result.json`, `trace.json`, `jev-output.json`, and safe screenshots into a timestamped, Git-ignored `runner-output/` directory. Each result includes a separate verification phase with its method, expected visible text, observed screen text, and pass/fail/inconclusive status. `jev-output.json` contains the credential-redacted request questions and Jev answer payload for each model call, including option probabilities, confidence, model, and latency. Import `result.json` from **Test cases → Import Scout result**, then expand a **Jev decision** in the action timeline to see the breakdown or the request/response JSON. Attach `jev-output.json` and screenshots as evidence when needed. The test revision must still match the exported case.

`Passed` requires satisfied required checkpoints, or a successful legacy visible-text substring assertion when no checkpoints are defined. Without verification, Jev's `DONE` yields `Inconclusive`. Missing or unknown starting conditions yield `Blocked`. Device/model errors yield `Execution error`. The runner will not tap controls whose labels suggest purchases, transfers, subscription, or account deletion. Legal and privacy consent gates stop as `Inconclusive` before agreement or submission; the user must explicitly authorize that step. Checkable state is included in screen fingerprints, and repeating an action without an observable screen change stops the run instead of toggling the control repeatedly.

## Local dashboard

See [dashboard setup](dashboard/README.md). The dashboard uses D1 for records and R2 for evidence, with the hosting platform's identity for access control. Its local development sign-in is for the preview only.

### iOS support

The same runner and dashboard now route iOS cases through Appium/XCUITest.
See [iOS setup and limitations](docs/ios-appium.md) for device discovery,
WebDriverAgent signing, CLI/MCP use, and recordings.

## Network sandbox

Create reusable synthetic HTTP/WebSocket scenarios in Settings → Sandbox, attach
one to a case, and review mock-hit evidence in the run's Network tab. See
[setup, supported behavior, and MCP tools](docs/sandbox.md). The optional sandbox
extra uses mitmproxy; device proxy routing and test CA trust must be prepared.
Record → edit → replay captures scoped JSON responses locally, redacts common
sensitive fields, and creates editable fixture drafts from selected responses.
