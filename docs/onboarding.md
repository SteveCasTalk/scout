# New teammate setup

A checklist for running Scout on your own machine for the first time. Scout is
local-first: the runner, device bridge, Appium, and dashboard all run on the
computer the phone is plugged into, and each teammate has their own dashboard
database. Shared test cases travel as exported JSON (see the last step).

Work through the steps in order; each links to the detailed guide.

## 1. Prerequisites

- [ ] macOS (required for iOS; Android also works on Linux)
- [ ] [uv](https://docs.astral.sh/uv/) and Python 3.11+
- [ ] Node.js 22.13+ (dashboard and Appium)
- [ ] Android SDK platform-tools (`adb`) and a JDK
- [ ] For iOS only: Xcode and an Apple development team you can sign with
- [ ] A physical Android device with USB debugging authorized; some UAT builds
      reject emulators

## 2. Clone and install

```sh
git clone https://github.com/SteveCasTalk/scout.git
cd scout
uv sync
```

## 3. Local secrets

```sh
cp .env.example .env
```

Fill `.env` locally. Never paste these values into chat, test cases, or commits.

- [ ] `TYPESAFE_API_KEY`: the Jev model key; ask the team lead how keys are issued
- [ ] `SCOUT_TEST_EMAIL` / `SCOUT_TEST_PASSWORD`: **your own** disposable UAT
      account. Do not share an account with another teammate; concurrent sessions
      on one account break login tests. Never use production credentials.

Details: [test account setup](test-account.md).

## 4. Appium (Android)

Follow [Appium setup → Install and start](appium-trial.md#install-and-start)
once. Scout starts the installed server on demand afterwards.

For iOS, also follow [iOS host setup](ios-appium.md#host-setup) and set the
`SCOUT_IOS_*` values in `.env`.

## 5. Dashboard

```sh
cd dashboard
npm ci
npm run build
npm run db:migrate
npm run dev
```

Open [localhost:5173](http://localhost:5173), use the local development sign-in,
and create a workspace with the team's agreed name for your app. Rerun
`npm run db:migrate` after every pull that adds a `drizzle/*.sql` file. See the
[dashboard README](../dashboard/README.md).

## 6. Connect your assistant (MCP)

- **Claude Code:** start it inside the checkout and approve the `scout` server
  from the project `.mcp.json`. See [MCP setup → Claude Code](mcp.md#claude-code).
- **Claude Desktop or Codex:** add the server manually with your checkout path;
  see [MCP setup](mcp.md#setup).

Reload the MCP server after any `.env` change.

## 7. Check the device

```sh
adb devices -l
```

- [ ] Your device shows as `device` (not `unauthorized` or `offline`)
- [ ] The UAT build of the app under test is installed
- [ ] Nobody else is driving this device: only one controller may run on a
      device at a time

## 8. First prompt run

Ask your assistant for a short, bounded exploration, for example:

> On my Android device, open the app and confirm the home screen appears. Use at
> most 10 steps.

- [ ] The run finishes and returns a dashboard link
- [ ] The run appears in the dashboard with screenshots and a trace

If it fails, check the run's folder and the `*.log` files in `runner-output/`
before retrying, then the troubleshooting sections of
[Appium setup](appium-trial.md) or [iOS setup](ios-appium.md).

## 9. Load the team's shared cases

Ask your assistant to import the team's exported case JSON into your workspace
with `import_test_cases`, running it with `dry_run=true` first to validate. For a
new `cases.csv` from the `generate-test-cases` skill, use
`import_generated_test_cases` instead. Then run one saved case end to end.

- [ ] One saved case ran and its result synced to your dashboard

You are set up. Before filing a bug from a Failed run, review the checkpoint
evidence: a violated checkpoint is a possible bug until a person accepts it.
