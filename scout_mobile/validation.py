"""Input validation shared by Scout MCP entry points and dependency-light tests."""
from __future__ import annotations

import re

READ_ONLY_VERIFICATION = re.compile(r"^(?:verify|confirm|check|observe)\b", re.I)


def validate_prompt_steps(goal: str, steps: str, assertion_text: str) -> None:
    """Allow step-free runs only when they are explicit visible-state assertions."""
    if len(steps) > 8000:
        raise ValueError("steps must be at most 8000 characters.")
    if not steps and (not READ_ONLY_VERIFICATION.match(goal) or not assertion_text.strip()):
        raise ValueError("Empty steps are only valid for a read-only verification goal with assertion_text.")
