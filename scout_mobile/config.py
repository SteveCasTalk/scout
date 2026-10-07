"""Read owner-only local configuration without evaluating shell syntax."""
from __future__ import annotations
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def getenv(name: str, default: str | None = None) -> str | None:
    """Prefer Scout settings; accept the previous prefix for existing setups."""
    if name in os.environ:
        return os.environ[name]
    legacy = name.replace('SCOUT_', 'JEV_', 1) if name.startswith('SCOUT_') else name
    return os.environ.get(legacy, default)

def load_local_env(path: Path | None = None) -> None:
    path = path or ROOT / '.env'
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8').splitlines():
        item = line.strip()
        if not item or item.startswith('#') or '=' not in item:
            continue
        name, value = item.split('=', 1)
        name = name.strip()
        if not name.isidentifier() or name in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ[name] = value
