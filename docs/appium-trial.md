# Appium Android setup and measurements

Native ADB is the default Android backend. Appium/UiAutomator2 is an opt-in
Android backend through `--driver appium` or `SCOUT_ANDROID_DRIVER=appium`, and
is required for cases that declare `tap_burst` or `target_gestures`. Appium handles hierarchy observations, screenshots, app
activation, foreground app lookup, taps, text, swipes, and Back. Android device
discovery, installation checks, metadata, logs, prompt settings, and recording
still use ADB. iOS uses the shared runner through XCUITest; see [iOS setup and limitations](ios-appium.md). Measurements below describe the original Android trial.

## Install and start

Run from the repository root with Node 22.12+ (or another version supported by
Appium 3), an Android SDK, and a JDK installed:

```sh
uv sync
npm ci --prefix tooling/appium
export APPIUM_HOME="$PWD/tooling/appium/.appium"
export ANDROID_HOME=/path/to/Android/sdk
export JAVA_HOME=/path/to/jdk/Contents/Home
tooling/appium/node_modules/.bin/appium driver install uiautomator2@8.7.0
tooling/appium/node_modules/.bin/appium driver doctor uiautomator2
npm --prefix tooling/appium start
```

The manual server command is optional after installation. On the first Appium
operation, Scout reuses a healthy server or starts the bundled server at
127.0.0.1:4723. macOS Android SDK and Java paths are discovered when possible;
set ANDROID_HOME and JAVA_HOME if installed elsewhere. A custom Appium URL
must already be running. Startup failures report the local log or setup steps.

Appium is pinned to 3.8.0; the trial uses UiAutomator2 8.7.0. Server dependencies
and installed drivers stay inside `tooling/appium`. The server listens only on
127.0.0.1:4723 and logs warnings/errors to avoid routine text-entry payload logs.
Do not enable debug logging while entering credentials.

## Choose a backend

```sh
.venv/bin/python -m scout_mobile --driver appium --case /path/to/case.json --package com.example.uat --serial DEVICE_SERIAL
```

Defaults are `SCOUT_ANDROID_DRIVER=adb` and
`SCOUT_APPIUM_URL=http://127.0.0.1:4723`; local `.env` values can override them. Restart the MCP
server and dashboard bridge using the virtual environment. All Agent entrypoints
use that setting. CLI `--driver appium` or `--driver adb` overrides it; iOS always uses Appium. Old processes must be restarted
to load the new implementation. No dashboard backend selector is added yet.

Sessions are opened lazily, use an explicit device serial, preserve application
data (`noReset=true`, `fullReset=false`), and do not automatically launch an app.
The runner controls app activation. Sessions close on completion/error and remain
open during a pending text request. No UI command silently falls back to ADB.
Appium native element lookup must match the observed bounds unambiguously.
The lookup filters for actionable nodes so a label child with the same bounds
as its clickable parent does not create an ambiguous match.

Results record `automation_backend` and Appium session startup milliseconds in
device info. Observation timings include `page_source_ms` in the local trace.
The dashboard accepts and displays backend metadata when runs are imported.

## Read-only speed comparison

Keep the device on one stable screen, with no other automation running:

```sh
.venv/bin/python -m scripts.benchmark_android_observation --serial DEVICE_SERIAL --samples 5 --output runner-output/appium-trial/observation-benchmark.json
```

This measures ADB observations followed by Appium observations, with cold Appium
startup measured separately. It prints medians, ranges, element counts, and the
number of distinct screen fingerprints. It performs no taps, saves no screen
content, and calls no model. A changing screen, different element coverage,
batch ordering, or a small sample size limits comparisons. This is not a full
test-run benchmark. The default idle wait is 1000 ms, based on the emulator and Samsung trial.
Reducing waits further may change observation reliability.
For a controlled comparison, `--idle-timeout-ms 1000` sets Appium's idle wait
to one second. Runs can use the equivalent `SCOUT_APPIUM_IDLE_TIMEOUT_MS=1000`;
leaving that variable unset uses 1000 ms. Set 10000 to try a longer wait. Startup and source
timings should always be measured separately on a warm session.

Contract checks: `.venv/bin/python -m unittest discover -s checks`.

## Initial local measurements (2026-10-02)

On `emulator-5554`, Arcana debug app's stable Settings screen, five observations
per backend (ADB first):

| Measurement | ADB | Appium, idle timeout 1000 ms |
| --- | ---: | ---: |
| Median observation | 2549 ms | 45 ms |
| Range | 2240–2742 ms | 43–197 ms |
| Appium session startup, separate | — | 2888 ms |
| Last actionable control count | 14 | 14 |
| Last visible text length | 238 | 238 |

Both batches had one stable screen fingerprint internally. These measurements
show a substantial observation improvement on this screen, not an end-to-end
speed guarantee. An earlier animated home-screen comparison with default
Appium settings returned different element coverage and is not a fair speed
comparison. A Samsung UAT profile navigation smoke test has also passed. Authentication
entry and typing have not been benchmarked.
Raw local metrics are in `runner-output/appium-trial/settings-benchmark.json`.

Official references: [UiAutomator2 driver](https://github.com/appium/appium-uiautomator2-driver)
and [Appium Python client](https://github.com/appium/python-client).
