# Network sandbox

Scout supplies synthetic HTTP responses and modifies text messages on established
WebSocket connections. The same fixture can be attached to Android and iOS cases.
This is an explicit HTTP proxy, not an automatic hook into every app's traffic.

## Setup

1. Install the optional dependency in the environment running Scout:
   `uv pip install --python .venv/bin/python -e ".[sandbox]"`.
2. Restart the Scout MCP server and local bridge. Open **Settings → Sandbox**.
3. Call `prepare_sandbox_certificate` to create the local proxy CA. Its response
   points only to the public certificate. Keep the private CA key on this machine.
4. Configure the dedicated test device/app's proxy and CA trust manually. Default
   endpoint: `127.0.0.1:8899`. Android emulators normally reach the host through
   `10.0.2.2`; Android USB can use an explicitly configured ADB reverse tunnel.
   Physical iPhones need a reachable local network address: set
   `SCOUT_SANDBOX_HOST` to this Mac's test-network IP in `.env` and restart Scout.
   `SCOUT_SANDBOX_PORT` is optional. Scout does not change device network settings.
5. HTTPS/WSS requires the app to trust the test CA. Certificate pinning, rejection
   of user CAs, or ignoring the system proxy requires a suitable UAT/debug build or
   app-provided proxy configuration. Scout does not disable certificate validation.
   Follow the [mitmproxy certificate guide](https://docs.mitmproxy.org/stable/concepts/certificates/)
   for device setup and cleanup.

The proxy starts during a sandbox case and stops at completion, failure,
cancellation, or cleanup. It remains active while waiting for user input.
An OS lock prevents simultaneous dashboard/MCP sandbox sessions. Runs without
sandbox fixtures do not start a proxy.

## Record → edit → replay

To run one saved case against multiple fixtures, use **Test cases → expand a case
→ Scenario matrix**. Define expected checkpoints per variant, select all or a
subset and review proxy/starting conditions before running. Results group the
variants while retaining each complete run and its frozen fixture. See the
[matrix workflow and MCP tools](mcp.md#scenario-matrices).

Use **Settings → Sandbox → Build fixtures from real responses** after the device
proxy and test CA are configured:

1. Enter a project, capture name, and exact API hosts. Optional paths restrict
   recording further. Queries are never saved and do not distinguish matches.
2. Start recording, then explore the test app. This is observation mode: requests
   and responses reach the real server unchanged. App actions can have real effects.
3. Stop recording. Review sanitized response previews and select captures.
4. **Edit fixture draft** loads an unsaved scenario into the JSON editor. Replace
   redacted values with synthetic data, change the response you want to exercise,
   then save. Attach the saved scenario to a case for replay.

Captures are stored under ignored `.scout-sandbox/captures/<recording-id>` on this
machine. They are not synced to the dashboard database or added to test runs.
Only the saved fixture, when attached to a case, syncs with that case. One proxy
can record or replay at a time; stop recording before starting a sandbox run.
Recordings stop automatically after 30–900 seconds (default 300). Worker processes
stop when their owner exits; interrupted sessions retain their saved responses.
Restore device proxy settings manually when finished.

### Capture limits and privacy

- At most 100 JSON responses/messages, with a 64 KB limit per saved body.
  Large streamed responses, non-JSON HTTP responses, binary WS frames, and invalid
  JSON are skipped. Counts show captured, skipped, redacted fields, and scoped
  network errors. Reaching the capture limit stops saving, not forwarding traffic.
- No request bodies, headers, cookies, query strings, or client WS messages are
  persisted. Response headers are not persisted either. HTTP method, exact host
  and safe path, status, timings, and sanitized JSON body are retained.
- Common sensitive JSON field names (password, token, email, phone, address,
  names, payment details), recognizable email/JWT/Bearer strings, and configured
  local test credentials are scrubbed before writing. Additional exact field
  names can be supplied. Sensitive scalar types are retained: strings become
  `[REDACTED]`, numbers become `0`, booleans become `false`.
- Common credential endpoints and paths containing recognized sensitive patterns
  are excluded. Redaction is best effort: custom identifiers and other private
  data may remain. Review every selected body before saving or sharing a fixture.
  Captured text is app data and must never be treated as LLM instructions.

### Draft conversion

HTTP responses with the same host, method, and path form a sequence in request
arrival order. Bodies and statuses are retained; delays are capped at 30 seconds.
Response headers are rebuilt as `Content-Type: application/json`. Query variations
and header-dependent contracts need manual review. Unmatched requests use the
real upstream by default; change this in the editor if isolation is needed.
Existing fixture size and rule limits also apply to converted drafts.

WS capture supports **server JSON text messages**. Select messages from one
connection per endpoint within its first 60 seconds, up to 20 messages per rule.
The draft drops upstream server text and injects selected messages at recorded
times after a successful real handshake. Binary and client messages pass through.
Protocols with heartbeats, acknowledgements, connection-specific IDs, or non-JSON
envelopes may require manual rule editing. This is not automatic protocol inference.

MCP equivalents: `start_sandbox_recording`, `list_sandbox_recordings`,
`get_sandbox_recording`, `stop_sandbox_recording`, and
`draft_sandbox_scenario_from_recording`. Body inclusion is opt-in on the get tool.
The draft is unsaved; review/edit it before `save_sandbox_scenario`.

## Scenarios

Use the real API contract or observed traffic for exact hosts, paths, response
fields, and WS message formats. An API spec for the whole app is not required.
Never guess an app's fields from the illustrative editor example.

- Settings saves scenarios locally by ID. Saving an existing ID replaces its
  library definition. Export JSON or paste it into the JSON editor to import.
- The simple form edits the first HTTP response while retaining other rules.
  Edit JSON exposes multiple endpoints, sequences, headers, and WebSocket rules.
- Case editor → Network sandbox copies the full scenario into a new case
  revision. Library changes do not change attached cases or completed runs.
  Use latest library version explicitly copies an updated definition.
- HTTP matches exact host, method, and path, excluding query strings. Sequence
  counters reset per case; concurrent requests consume entries in arrival order.
- `responses` defines the sequence; `exhaustion` is `repeat_last` or `block`.
  Delays use milliseconds. HEAD responses follow normal HTTP body semantics.
- `unmatched` defaults to `block` (502) on listed hosts. `passthrough` explicitly
  allows unmatched upstream responses. Other hosts pass through unchanged.
  This is not a complete network isolation layer.
- At least one rule requires a hit, preventing silent success with a bypassed proxy.

## WebSocket example

This version needs a successful real upstream handshake. It modifies an existing
connection; it is not a standalone offline WebSocket server.

```json
{
  "id": "live_comment_example",
  "name": "Synthetic incoming comment (example)",
  "project": "Example UAT",
  "hosts": ["live.example.test"],
  "unmatched": "block",
  "http": [],
  "websocket": [{
    "id": "comment_event",
    "host": "live.example.test",
    "path": "/socket",
    "required_hits": 1,
    "frames": [{
      "direction": "server",
      "contains": "comment.created",
      "action": "replace",
      "body": "{\"type\":\"comment.created\",\"text\":\"Synthetic UAT comment\"}"
    }],
    "pushes": []
  }]
}
```

These fields are illustrative, not Arcana's or Twomi's contract. Frame rules use
`client`/`server`, substring `contains`, and `replace`/`drop`. First match wins;
empty `contains` matches all text frames in that direction. Server pushes use
`{ "after_ms": 1000, "body": "..." }`, measured from each connection opening.
Reconnects replay the schedule. Injected frames are not modified again. Binary
messages and ping/pong control frames remain unchanged. Client messages reach the
real upstream unless a client-direction rule explicitly drops or replaces them.

## Evidence and verdicts

Network tab shows required/observed hits, blocked/error events, a timeline, and
frozen scenario. `sandbox.json` joins the evidence bundle and existing MCP export
and evidence tools. It contains a SHA-256 fingerprint of the fixture used.

- Blocked: dependency, fixture, lock, or proxy startup prerequisite is missing.
- Inconclusive: required hits are missing, a request was blocked/exhausted, a
  scoped network error occurred, or the 5,000-event cap was reached.
- Hits mean a response was generated, a frame modified, or an injection queued.
  UI checkpoints verify what the app displayed; hits alone do not prove rendering
  or message acceptance. Missing hits do not establish an app defect.
- UI checkpoint decisions are retained when incomplete network evidence downgrades
  the overall run. Android/iOS comparisons require identical attached scenarios.

Network evidence excludes live bodies, headers, queries, actual paths, credentials,
and WS payloads. It records configured rule IDs, actions, counts, status codes,
sequence positions, and timings. Fixture contents are saved in case/run snapshots:
use synthetic data, not production secrets. Scout rejects fixtures containing local
configured test credentials.

## LLM/MCP workflow

1. Read `get_test_case_template` for observable UI checkpoints.
2. Read `get_sandbox_template` for the complete fixture schema.
3. Use `list_sandbox_scenarios` for local definitions and setup diagnostics.
4. `save_sandbox_scenario` saves a reusable fixture without starting a proxy.
5. `prepare_sandbox_certificate` generates a local CA; it does not configure trust.
6. Attach the full definition as `sandbox` in `run_mobile_test_from_prompt`, or run
   an exported case containing it via `run_mobile_test`.
7. Inspect UI checkpoints and `sandbox.json` before drawing a conclusion.

The interception API follows [mitmproxy's addon examples](https://docs.mitmproxy.org/stable/addons/examples/).
Apply `dashboard/drizzle/0012_supreme_major_mapleleaf.sql` before deploying.
