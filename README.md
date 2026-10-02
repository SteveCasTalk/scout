# Jev Mobile

This workspace adapts the [Jev Ultrafast](https://github.com/browser-use/jev-ultrafast) observe–choose–act design to Android testing and pairs it with a dashboard for test cases, results, and evidence.

## Current state

- `dashboard/`: create and revise test cases, record manual runs, import Jev runner results, inspect per-step questions, answers, probabilities, confidence, and latency, attach evidence, and review saved test snapshots.
- `jev_mobile/`: Python runner using Android UI hierarchy plus TypeSafe's Jev model to choose an indexed operation and target. It re-observes a target before acting and independently checks exact visible text before reporting Passed.
- MCP server: local tools for device discovery, Jev test execution, run history, and result inspection; see [MCP setup](docs/mcp.md).
- `.env`: local, Git-ignored owner-only UAT credentials and model keys. Copy `.env.example` if needed, then fill values locally; see [test account setup](docs/test-account.md). **Do not send credentials in chat or put them in test cases.**

The runner currently targets Android. There is no iOS driver. Jev chooses operations and targets; Appium with UiAutomator2 provides device observations, actions, and screenshots. ADB supports Android discovery, diagnostics, prompt settings, and recording. ARTEMIS is not used by the runner. It captures an action trace and screenshots, including an authenticated outcome screen when no input field or account value is visible. The runner also captures low-bitrate Android screen-recording clips for each execution segment; Jev and dashboard imports attach the MP4 clips to the test run when they are available.

## AI Avatar UAT

The installed package is `com.wallet.walkthedog.uat`. Version 3.34.0 blocks the emulator with a root/emulator alert. On 2026-09-26, the authentication case passed on a physical Samsung SM-S906E: the runner entered the locally configured test account, handled Android password-manager prompts without using or saving their credentials, and verified the authenticated **LOUNGE** tab. See [exploration notes](docs/aiavatar-exploration.md) and the reusable case at `runner-output/aiavatar-samsung-login-case.json` (local, Git-ignored).

## Run from the dashboard

Prompt-driven MCP runs start the local dashboard and device bridge on demand when the dashboard dependencies are installed. The returned dashboard link uses the active local port, so it remains openable when the default port is already occupied. For manually launched dashboard runs, start the dashboard with `cd dashboard && npm run dev` and the local device bridge with `uv run python -m jev_mobile.local_server`; runs and safe evidence are saved automatically. See [dashboard runner setup](dashboard/README.md#run-jev-from-the-dashboard).

## Run a case

Appium is the default Android backend and starts automatically when installed.
Complete the [Appium setup](docs/appium-trial.md) once. Use `--driver adb` only
when explicitly choosing the previous backend.

1. Add an Android test case in the dashboard. Give it an exact visible text assertion when possible.
2. Export the case JSON from the Test cases table.
3. Fill the local `.env` with `TYPESAFE_API_KEY`, `JEV_TEST_EMAIL`, and `JEV_TEST_PASSWORD` for a disposable UAT account. The text-model key is needed only for non-credential text fields.
4. Run with an attached, authorized Android device:

```sh
python3 -m jev_mobile --case /absolute/path/to/jev-case.json --package com.wallet.walkthedog.uat --serial DEVICE_SERIAL --adb /Users/phucnguyen/Library/Android/sdk/platform-tools/adb
```

By default, each run temporarily disables Android autofill and credential providers, which prevents Samsung Pass and Google Password Manager save-password dialogs from blocking Jev. It also temporarily grants and silences Android 13+ notification permission so its runtime prompt does not block the test. The runner restores the device's original settings and notification permission when the run ends, including after a test failure. Use `--allow-device-prompts` to keep autofill and credential providers enabled for a CLI run; notification prompts remain suppressed. The runner still dismisses recognized prompts if one appears despite the device setting.

The runner writes `result.json`, `trace.json`, `jev-output.json`, and safe screenshots into a timestamped, Git-ignored `runner-output/` directory. Each result includes a separate verification phase with its method, expected visible text, observed screen text, and pass/fail/inconclusive status. `jev-output.json` contains the credential-redacted request questions and Jev answer payload for each model call, including option probabilities, confidence, model, and latency. Import `result.json` from **Test cases → Import Jev result**, then expand a **Jev decision** in the action timeline to see the breakdown or the request/response JSON. Attach `jev-output.json` and screenshots as evidence when needed. The test revision must still match the exported case.

`Passed` requires the exact visible text; without an assertion, Jev's `DONE` yields `Inconclusive`. Device/model errors yield `Execution error`. The runner will not tap controls whose labels suggest purchases, transfers, subscription, or account deletion. Legal and privacy consent gates stop as `Inconclusive` before agreement or submission; the user must explicitly authorize that step. Checkable state is included in screen fingerprints, and repeating an action without an observable screen change stops the run instead of toggling the control repeatedly.

## Local dashboard

See [dashboard setup](dashboard/README.md). The dashboard uses D1 for records and R2 for evidence, with the hosting platform's identity for access control. Its local development sign-in is for the preview only.

### iOS support

The same runner and dashboard now route iOS cases through Appium/XCUITest.
See [iOS setup and limitations](docs/ios-appium.md) for device discovery,
WebDriverAgent signing, CLI/MCP use, and recordings.
