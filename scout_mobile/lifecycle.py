"""Typed preparation with a durable restoration journal and no generated shell."""
from __future__ import annotations
import json
import re
import time
from pathlib import Path
from .device import DeviceError
from .execution_runtime import ExecutionBlocked

class Lifecycle:
    def __init__(self,agent):
        self.a=agent;self.journal=agent.output/'.lifecycle.json';self.state=[];self.failed=False
    def _write(self,phase):
        value={'schema_version':1,'device':self.a.config.serial,'package':self.a.config.package,'phase':phase,'changes':self.state}
        temporary=self.journal.with_suffix('.tmp');temporary.write_text(json.dumps(value,indent=2)+'\n');temporary.chmod(0o600);temporary.replace(self.journal)
    def value(self,hook):
        d=self.a.device;p=self.a.config.package
        if hook['operation']=='wifi':
            raw=d.command('shell','settings','get','global','wifi_on').stdout.decode().strip()
            if raw not in {'0','1'}:raise ExecutionBlocked('Wi-Fi starting state is unavailable.')
            return raw=='1'
        details=d.command('shell','dumpsys','package',p).stdout.decode(errors='replace')
        match=re.search(re.escape(hook['permission'])+r': granted=(true|false)',details)
        if not match:raise ExecutionBlocked('Permission starting state is unavailable or not requested by this app.')
        return match[1]=='true'
    def apply(self,hook,enabled):
        d=self.a.device
        if hook['operation']=='wifi':d.command('shell','svc','wifi','enable' if enabled else 'disable')
        else:d.command('shell','pm','grant' if enabled else 'revoke',self.a.config.package,hook['permission'])
        if self.value(hook)!=enabled:raise DeviceError('Lifecycle state change could not be verified.')
    def prepare(self):
        # A prior incomplete journal is a real blocker, including after a crashed process.
        for journal in self.a.output.parent.glob('*/.lifecycle.json'):
            if journal==self.journal:continue
            try:previous=json.loads(journal.read_text())
            except (ValueError,OSError):raise ExecutionBlocked('A lifecycle journal cannot be read; inspect cleanup before continuing.') from None
            if previous.get('device')==self.a.config.serial and previous.get('phase')!='restored':
                raise ExecutionBlocked('Previous device cleanup requires reconciliation: '+journal.parent.name)
        for hook in self.a.execution['lifecycle']['before']:
            if getattr(self.a,'protocol',None):self.a.protocol.event('lifecycle_start',hook_id=hook['id'],operation=hook['operation'])
            if hook['operation']=='terminate':self.a.device.terminate(self.a.config.package)
            elif hook['operation']=='clear_data':
                if not self.a.authorizations['clear_data']:raise ExecutionBlocked('App data reset requires explicit run authorization.')
                result=self.a.device.command('shell','pm','clear',self.a.config.package).stdout.decode().strip()
                if result!='Success':raise ExecutionBlocked('App data reset did not report success.')
            else:
                original=self.value(hook)
                if original!=hook['enabled']:
                    self.state.append({'hook':hook,'original':original})
                    self._write('pending') # Journal before mutation, including ambiguous failures.
                    self.apply(hook,hook['enabled'])
            if getattr(self.a,'protocol',None):self.a.protocol.event('lifecycle_end',hook_id=hook['id'],operation=hook['operation'])
        if self.state:self._write('pending')
    def restore(self):
        errors=[]
        for item in reversed(self.state):
            try:
                if self.value(item['hook'])!=item['original']:self.apply(item['hook'],item['original'])
            except (DeviceError,OSError) as exc:errors.append(type(exc).__name__)
        self.failed=bool(errors)
        if self.state:self._write('failed' if errors else 'restored')
        if getattr(self.a,'protocol',None):self.a.protocol.event('lifecycle_cleanup',verified=not errors)
        if errors:raise DeviceError('Lifecycle restoration failed; next run is blocked until cleanup is reconciled.')


def reconcile(run_id,serial):
    """Restore only validated, previously journaled reversible changes on an idle device."""
    from types import SimpleNamespace
    from .config import ROOT,getenv
    from .device import AndroidDevice
    from .device_lease import DeviceLease
    from .execution_contract import Hook
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',run_id):raise ValueError('Invalid run ID.')
    folder=ROOT/'runner-output'/run_id
    if folder.is_symlink() or folder.resolve().parent!=(ROOT/'runner-output').resolve():raise ValueError('Invalid run directory.')
    path=folder/'.lifecycle.json'
    if path.is_symlink():raise ValueError('Invalid cleanup journal.')
    value=json.loads(path.read_text())
    if value.get('device')!=serial or not re.fullmatch(r'[A-Za-z0-9_.]{3,240}',value.get('package','')):raise ValueError('Cleanup device/package mismatch.')
    lease=DeviceLease(serial);lease.acquire()
    try:
        changes=value.get('changes')
        if not isinstance(changes,list) or len(changes)>10:raise ValueError('Invalid cleanup journal changes.')
        normalized=[]
        for change in changes:
            hook=Hook.model_validate(change['hook']).model_dump()
            if hook['operation'] not in {'permission','wifi'} or type(change.get('original')) is not bool:raise ValueError('Only recorded reversible settings can be restored.')
            normalized.append({'hook':hook,'original':change['original']})
        agent=SimpleNamespace(output=folder,config=SimpleNamespace(serial=serial,package=value['package']),device=AndroidDevice(serial,getenv('ADB_PATH') or 'adb'))
        manager=Lifecycle(agent);manager.state=normalized;manager.restore()
        return {'run_id':run_id,'device':serial,'cleanup':'restored'}
    finally:lease.release()
