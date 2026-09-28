# Test account setup

The preferred setup is to put UAT-only test credentials in the local `.env` at this repository root. The file is Git-ignored. The prompt-driven MCP tool also accepts `test_email` and `test_password` for a one-off run when the user explicitly supplies them. Those values pass through the assistant host and MCP tool call, so `.env` is more private. Use disposable UAT credentials only; never use production credentials.

The runner reads credentials for recognized authentication fields. It does not include either value in the TypeSafe request, text-helper request, action trace, or run result; values are redacted from any prompt fields that repeat them. Password entry through ADB still sends the value to the local device's input command, so use only a disposable UAT account. This ADB input path accepts ASCII letters, digits, spaces, and common punctuation (`@._+!#$&*()=:/?-`); unsupported characters cause a clear execution error before typing.
