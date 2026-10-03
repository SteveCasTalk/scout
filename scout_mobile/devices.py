"""Platform-aware device discovery shared by CLI, MCP and dashboard."""
from .device import AndroidDevice

def connected(platform: str = 'Android', adb: str = 'adb') -> list[str]:
    if platform == 'Android':return AndroidDevice.connected(adb)
    if platform == 'iOS':
        from .ios_device import discover_ios
        return [item['serial'] for item in discover_ios()]
    raise ValueError('Platform must be Android or iOS.')
