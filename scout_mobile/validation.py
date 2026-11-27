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


def validate_prompt_account(email: object, password: object) -> tuple[str, str]:
    """An account the user gave in the prompt for one run. Messages never repeat the values."""
    if not isinstance(email, str) or not isinstance(password, str):
        raise ValueError("test_email and test_password must be text.")
    email = email.strip()
    if len(email) > 254 or len(password) > 200:
        raise ValueError("test_email or test_password exceeds the supported length.")
    if email and "@" not in email:
        raise ValueError("test_email must be a valid-looking email address.")
    if bool(email) != bool(password):
        raise ValueError("Give both test_email and test_password, or neither.")
    return email, password
