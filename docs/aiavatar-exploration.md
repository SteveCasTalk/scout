# AI Avatar UAT: device exploration

Explored on 2026-09-26 using Android's UI hierarchy and ADB on an emulator and a physical Samsung. The installed package is **`com.wallet.walkthedog.uat`**; `com.walkthedog.uat` is not installed. App label: UAT-AI Avatar, version 3.34.0 (784952).

On the emulator, `com.wallet.walkthedog.feature.start.StartActivity` shows a modal: **“This application is not supported on rooted devices or emulators.”** The dialog's OK control is clickable. After OK, the app closes and the Android launcher appears. No login screen is reachable there.

Observed dialog bounds on a 1344 × 2992 display:

- Message text: `[264,1375][1080,1481]` (no resource ID).
- OK button: `[264,1553][1080,1703]` (no resource ID).

The generic runner reproduced the startup block and recorded it as **Execution error** with an initial screenshot and trace. A real authentication test requires a physical non-rooted device or a UAT build authorized to run on an emulator. The runner does not alter or bypass the app's device security check.

## Samsung authentication round

On 2026-09-26, the UAT app was explored and tested on a physical Samsung SM-S906E (`RFCTB15BTEW`). Jev chose the test actions from ADB/UIAutomator observations; ADB performed device actions and captured screenshots. ARTEMIS is not a runtime dependency of the test runner.

The verified path is: landing page **Log in** → **Enter your email address** → **Sign Up or Log In** → **Enter Your Password** → **Login** → authenticated **LOUNGE** tab. The installed package is `com.wallet.walkthedog.uat`. Android can show a saved-password suggestion when the email field is focused and a Samsung Pass save-password prompt after submission; the runner dismisses each with **Cancel**. It never selects or saves a device password-manager credential.

The repeatable case is `runner-output/aiavatar-samsung-login-case.json`. The passed round is in `runner-output/samsung-login-round/result.json`, with its action trace, original screenshots from before credential entry, and a post-login screenshot with no credential fields. The test account and TypeSafe key are read from the root `.env`; the result and trace redact both credential values. The local dashboard records the passed run and seven evidence files. Current runner versions capture a safe post-login screenshot automatically.
