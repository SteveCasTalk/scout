"""Dedicated optional-dependency process; never import mitmproxy in the runner."""
from .config import getenv
from mitmproxy.tools.main import mitmdump
from pathlib import Path
import sys
import os
import threading
import time

if __name__ == '__main__':
    # Stop the proxy if its owning runner dies; do not leave device traffic
    # routed through an orphaned worker after MCP shutdown.
    parent = int(os.environ['SCOUT_SANDBOX_PARENT_PID'])
    def watch_parent():
        while True:
            time.sleep(2)
            if os.getppid() != parent:
                os._exit(0)
    threading.Thread(target=watch_parent, daemon=True).start()
    addon = 'sandbox_recording_addon.py' if getenv('SCOUT_SANDBOX_MODE') == 'record' else 'sandbox_addon.py'
    mitmdump(['-s', str(Path(__file__).with_name(addon)), *sys.argv[1:]])
