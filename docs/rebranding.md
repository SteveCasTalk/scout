# Scout rename and compatibility

The platform is Scout. Its Python distribution is `scout-mobile`, its source package is `scout_mobile`, and the local commands are `scout`, `scout-mcp`, and `scout-local-runner`.

## Configuration

New setup uses `SCOUT_*` environment variables, including `SCOUT_TEST_EMAIL`, `SCOUT_TEST_PASSWORD`, `SCOUT_ANDROID_DRIVER`, `SCOUT_APPIUM_URL`, and `SCOUT_IOS_*`. Older `JEV_*` environment settings are accepted as a fallback; an explicitly set Scout value takes precedence, including an empty value. The local `.env` keys have been migrated without changing credential values.

Saved cases can use `$SCOUT_TEST_EMAIL`. Historical `$JEV_TEST_EMAIL` account placeholders remain readable. Browser workspace and active-run selections migrate from the older storage keys when opened.

## Historical results

New results identify `Scout Android runner` or `Scout iOS runner` and import as `Scout import`. Dashboard imports still accept the previous runner sources and import labels, so old results do not need to be rewritten. Existing result snapshots and reviews are preserved.

`jev-output.json`, the `jev` action-audit field, `assessment="jev"`, and `jev-latest` identify the current TypeSafe model/decision protocol. They are engine identifiers rather than the platform name. References to the upstream Jev project remain attributed to their actual source.

## Local checkout and MCP

The checkout is available through a `scout` directory link. The physical `jev-mobile` directory remains registered as this chat’s writable workspace root: Codex rejects a symlink at that root. Rename the physical directory when reopening the project in a workspace registered at its new path. Existing workspace attachments and historical absolute artifact paths continue to resolve. Updated setup examples and MCP configuration use the canonical `scout` path and `scout-mcp` command. Reload the MCP host after updating its configuration.

The GitHub repository is [SteveCasTalk/scout](https://github.com/SteveCasTalk/scout), and this checkout’s `origin` points to `https://github.com/SteveCasTalk/scout.git`. GitHub redirects old repository links after the rename.
