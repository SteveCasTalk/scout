# iOS through Appium

Scout supports iOS cases through XCUITest on macOS. Android still uses UiAutomator2
(or an explicitly selected ADB backend). Cases, checkpoints, starting conditions,
review and evidence use the existing dashboard workflow.

## Host setup

Install full Xcode, select its developer directory, and complete Xcode's initial
setup. Install the project dependencies, then install the iOS driver:

```sh
uv sync
npm --prefix tooling/appium ci
APPIUM_HOME="$PWD/tooling/appium/.appium" tooling/appium/node_modules/.bin/appium driver install xcuitest@12.13.3
APPIUM_HOME="$PWD/tooling/appium/.appium" tooling/appium/node_modules/.bin/appium driver doctor xcuitest
```

Restart a running Appium server after installing a new driver. Scout starts the
project's installed server automatically when its default local port is free.
No drivers are installed automatically during a run.

For a physical device: pair/trust the Mac, enable Developer Mode, unlock it, and
configure WebDriverAgent signing in `.env`:

- `SCOUT_IOS_TEAM_ID`: your Apple development team ID.
- `SCOUT_IOS_SIGNING_ID`: usually `Apple Development`.
- `SCOUT_IOS_WDA_BUNDLE_ID`: a bundle ID provisioned by that team, when needed.
- `SCOUT_IOS_USE_PREINSTALLED_WDA=true`: optional, only for an already installed,
  correctly signed WebDriverAgent.

Scout does not choose a team, create certificates, or accept signing agreements.
Refer to the [XCUITest real-device configuration documentation](https://appium.github.io/appium-xcuitest-driver/latest/preparation/real-device-config/).

Boot a simulator yourself if using one. Discovery includes paired connected
physical iOS devices and booted, available iOS simulators; it does not boot or
reset devices automatically. Install the target app using your existing process.

## Running

In Test cases, choose **iOS**, set the app's **bundle ID**, and select **Run**.
Device discovery follows the case platform. Suites must contain one platform;
run Android and iOS separately. Relaunch preserves app data and login state.

CLI example (replace the identifiers with your own):

```sh
uv run scout --case case.json --platform iOS --package com.example.uat --serial IOS_UDID
```

MCP tools:

- `list_ios_devices` returns real device UDIDs and booted simulator IDs.
- `run_mobile_test` reads the platform from an exported case.
- `run_mobile_test_from_prompt` accepts `platform="iOS"` and an explicit bundle
  ID in `package`. Use `get_test_case_template` to define checkpoints first.
- Existing Android tool names remain compatible.

Reload the MCP server and local dashboard runner after updating Python code.

## Behavior and limits

- Native XCUITest hierarchy and element actions; no ADB commands on iOS.
- Screenshot coordinates are in iOS points. Original screenshots are preserved.
- Native fields can expose placeholder text as their value, so the selector can
  choose an iOS field with a nonempty value. Text entry clears then fills it.
- iOS has no universal Back button. The selector uses TAP on observed navigation
  controls; the generic BACK operation is excluded from iOS decisions.
- Picker wheels and sliders expose SET_VALUE. Put exact picker values in the case
  steps; slider positions must be explicit numbers from 0 to 1. The resulting
  control value is checked. Missing values are requested from the user, never
  invented. The Android birthday shortcut does not run on iOS.
- Accessible custom controls are exposed when the hierarchy explicitly marks
  them accessible. Unlabelled or inaccessible controls still require app changes.
- Focus is taken only from the native field attribute. Keyboard visibility never
  marks other fields focused. Input targets the exact native element and verifies
  that element's value; screenshot capture is withheld while the keyboard is visible.
- An active alert limits selection to its controls. SpringBoard is allowed only
  while an alert is visible. Accepting requires explicit per-run consent via MCP
  `allow_consent` or the dashboard setup checkbox; deny/cancel controls remain
  available. Consent is not enabled by default.
- Each execution segment attempts an MP4 screen recording, capped at 10 minutes.
  Pauses for user input split segments. ffmpeg is required. Capture failures are
  reported in outcome notes; they do not turn an app pass into an app failure.
- Syslog capture is best effort and exported only for the target app's observed
  PID. Other process lines are excluded. Unavailable logs are stated explicitly.
  Device/app version discovery is best effort. Unverifiable required versions
  produce Blocked.
- External app handoffs (including Safari authentication) are Blocked with a
  boundary explanation. They need a separately configured flow; this release
  does not automatically authorize external apps or forward credentials to them.
- WebViews can use controls exposed through native accessibility. Dedicated DOM
  context automation remains unsupported. If a WebView cannot progress, the run
  reports Blocked with that limitation. Purchases retain the existing consequential
  action guard on both platforms.
- Real-device signing and end-to-end app behavior still need validation with the
  selected target app. Installing the driver and running doctor do not establish
  that a test or recording will succeed.
