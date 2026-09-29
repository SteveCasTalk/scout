# URL Knowledge

## Source
- URL: https://github.com/browser-use/jev-ultrafast
- Accessed: 2026-09-26 (Asia/Ho_Chi_Minh)
- Content type: html and Python source

## Summary
- Python browser automation agent that takes a URL and natural-language goal and operates Chrome.
- Reads structured DOM controls into an indexed table; TypeSafe Jev selects an operation and compatible target in one request. A separate text model generates field input only when required.
- Includes a reusable Agent API and local inspector/demo.

## Notable details
- Python >=3.12, browser-harness, TypeSafe API key, and text-model API key required.
- Agent loop observes, predicts, validates page freshness, executes, and repeats until done or blocked; tracks actions and optional recordings.
- README reports a roughly 7.1-second flight-search demonstration; timing excludes initial observation and is not a broad reliability benchmark.
- MVP excludes frames, shadow roots, canvas, uploads, popup tabs, nested scrolling, and arbitrary keyboard widgets. Outcomes need independent verification.
- Sources also inspected: jev_ultrafast/agent.py and pyproject.toml on the main branch.

## Open questions
- No local execution or independent performance validation performed.
- Applicability to any particular website requires verification.
