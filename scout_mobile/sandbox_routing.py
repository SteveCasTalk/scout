"""Explicit, reversible Android device routing for the network sandbox.

Scout never changes device network settings during a run. This module is the one place that
does, and only when a person runs `scout sandbox-routing up|down|status`:

  up      adb reverse the sandbox proxy port (and any extra ports, e.g. a local media server),
          then point the device's global HTTP proxy at it. The previous proxy value is saved.
  down    restore the saved proxy value (or clear it) and remove only the tunnels `up` created.
  status  report the proxy, tunnels, and whether this tool has an active routing record.

While the proxy is set, the device's HTTP traffic only works during a sandbox run, because the
proxy listens only then. Run `down` when finished.
"""
from __future__ import annotations
import json
import re
import subprocess
from pathlib import Path
from .config import ROOT, getenv

STATE_DIR=ROOT/'runner-output'/'.sandbox-routing'
CLEARED={'',':0','null'}


class RoutingError(RuntimeError):
    pass


def proxy_port()->int:
    return int(getenv('SCOUT_SANDBOX_PORT','8899'))


def _adb(adb:str,serial:str,*args:str)->str:
    try:
        done=subprocess.run([adb,'-s',serial,*args],capture_output=True,text=True,timeout=15)
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise RoutingError(f'adb failed: {type(exc).__name__}') from None
    if done.returncode!=0:
        raise RoutingError(f'adb {" ".join(args[:3])} failed: {(done.stderr or done.stdout).strip()[:200]}')
    return done.stdout.strip()


def _state_path(serial:str)->Path:
    if not re.fullmatch(r'[A-Za-z0-9._:-]{1,80}',serial):raise RoutingError('Invalid device serial.')
    return STATE_DIR/(serial.replace(':','_')+'.json')


def _require_device(adb:str,serial:str)->None:
    try:output=subprocess.run([adb,'devices'],capture_output=True,text=True,check=True,timeout=12).stdout
    except (OSError,subprocess.SubprocessError) as exc:raise RoutingError(f'adb devices failed: {type(exc).__name__}') from None
    ready=[line.split()[0] for line in output.splitlines()[1:] if line.strip().endswith('\tdevice')]
    if serial not in ready:raise RoutingError(f'Device {serial} is not connected and authorized.')


def status(serial:str,adb:str='adb')->dict:
    _require_device(adb,serial)
    proxy=_adb(adb,serial,'shell','settings','get','global','http_proxy')
    tunnels=sorted(set(re.findall(r'tcp:(\d+)\s+tcp:\d+',_adb(adb,serial,'reverse','--list'))),key=int)
    path=_state_path(serial)
    record=json.loads(path.read_text()) if path.is_file() else None
    expected=f'127.0.0.1:{proxy_port()}'
    return {'serial':serial,'proxy':proxy or 'null','reverse_ports':[int(p) for p in tunnels],
            'sandbox_routing_active':proxy==expected and str(proxy_port()) in tunnels,'record':record}


def up(serial:str,extra_ports:list[int],adb:str='adb')->dict:
    _require_device(adb,serial)
    port=proxy_port()
    ports=[port,*[p for p in dict.fromkeys(extra_ports) if p!=port]]
    for value in ports:
        if not 1024<=value<=65535:raise RoutingError(f'Port {value} must be 1024–65535.')
    path=_state_path(serial)
    previous=json.loads(path.read_text()) if path.is_file() else None
    current=_adb(adb,serial,'shell','settings','get','global','http_proxy')
    # Keep the original proxy across repeated `up` calls so `down` restores the pre-Scout value.
    original=previous['original_proxy'] if previous else current
    created=list(previous['reverse_ports']) if previous else []
    existing={int(p) for p in re.findall(r'tcp:(\d+)\s+tcp:\d+',_adb(adb,serial,'reverse','--list'))}
    for value in ports:
        if value not in existing:created.append(value)
        _adb(adb,serial,'reverse',f'tcp:{value}',f'tcp:{value}')
    STATE_DIR.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({'serial':serial,'original_proxy':original,'reverse_ports':sorted(set(created))},indent=2)+'\n')
    _adb(adb,serial,'shell','settings','put','global','http_proxy',f'127.0.0.1:{port}')
    result=status(serial,adb)
    if not result['sandbox_routing_active']:raise RoutingError('Routing did not take effect; run `scout sandbox-routing down`.')
    return result


def down(serial:str,adb:str='adb')->dict:
    _require_device(adb,serial)
    path=_state_path(serial)
    record=json.loads(path.read_text()) if path.is_file() else {'original_proxy':'','reverse_ports':[proxy_port()]}
    original=record.get('original_proxy','')
    # A loopback proxy left from a previous sandbox session is not worth restoring.
    restore=':0' if original in CLEARED or original.startswith('127.0.0.1:') else original
    _adb(adb,serial,'shell','settings','put','global','http_proxy',restore)
    for value in record.get('reverse_ports',[]):
        try:_adb(adb,serial,'reverse','--remove',f'tcp:{value}')
        except RoutingError:pass  # Already removed.
    path.unlink(missing_ok=True)
    return status(serial,adb)
