"""OS-backed per-device ownership shared by MCP, CLI and bridge processes."""
from __future__ import annotations
import hashlib
import os
from .config import ROOT
from .execution_runtime import ExecutionBlocked

class DeviceLease:
    def __init__(self,serial):
        self.serial=serial;self.handle=None
    def acquire(self):
        if self.handle:return
        folder=ROOT/'runner-output'/'.device-locks';folder.mkdir(parents=True,exist_ok=True)
        handle=(folder/(hashlib.sha256(self.serial.encode()).hexdigest()+'.lock')).open('a+')
        try:
            if os.name=='nt':
                import msvcrt
                handle.seek(0);handle.write('0');handle.flush();handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            handle.close();raise ExecutionBlocked('Another Scout process owns this device; wait for its run to finish.') from None
        self.handle=handle
    @staticmethod
    def busy(serial):
        path=ROOT/'runner-output'/'.device-locks'/(hashlib.sha256(serial.encode()).hexdigest()+'.lock')
        if not path.is_file():return False
        with path.open('r+') as handle:
            try:
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1);handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
                else:
                    import fcntl
                    fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(handle,fcntl.LOCK_UN)
                return False
            except OSError:return True
    def release(self):
        if self.handle:self.handle.close();self.handle=None
