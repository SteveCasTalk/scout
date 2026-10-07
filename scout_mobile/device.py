"""Android UI hierarchy observation and bounded device actions through ADB."""
from __future__ import annotations
from dataclasses import dataclass
from contextlib import contextmanager
import hashlib
import json
import re
import shlex
import uuid
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

BOUNDS = re.compile(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]')
SENSITIVE = re.compile(r'password|passcode|pin|email|username|e-mail|account', re.I)
GENERIC_LABELS = {'background','root','decor view','decorview','content','container','view'}

class DeviceError(RuntimeError):
    pass

@dataclass(frozen=True)
class Element:
    index: str
    role: str
    label: str
    resource_id: str
    class_name: str
    value: str
    bounds: tuple[int,int,int,int]
    operations: tuple[str,...]
    sensitive: bool
    password: bool = False
    focused: bool = False
    checked: bool = False
    checkable: bool = False

    @property
    def signature(self) -> tuple[str,str,str,tuple[int,int,int,int],bool,bool,bool]:
        return self.resource_id,self.class_name,self.label,self.bounds,self.checked,self.checkable,self.focused

    @property
    def center(self) -> tuple[int,int]:
        x1,y1,x2,y2=self.bounds
        return (x1+x2)//2,(y1+y2)//2

    def public(self) -> dict:
        return dict(index=self.index,role=self.role,label=self.label,resource_id=self.resource_id,value='<redacted>' if self.sensitive and self.value else self.value,operations=list(self.operations),checked=self.checked if self.checkable else None,checkable=self.checkable,focused=self.focused)

@dataclass
class Screen:
    xml: str
    elements: list[Element]
    text: str
    fingerprint: str
    width: int
    height: int

class AndroidDevice:
    backend = 'adb'
    platform = 'Android'

    def close(self) -> None:
        """Release backend resources (ADB has no per-run session)."""

    def __init__(self,serial:str,adb:str='adb'):
        self.serial=serial
        self.adb=adb
        self._screen_size:tuple[int,int]|None=None
        self._screen_size_read_at=0.0
        self.screen_size_cache_seconds=2.0
        self.last_observation_timings:dict[str,int]={}
        self.last_wait_timings:dict[str,int]={}
        self.last_content_wait_timings:dict[str,int]={}
        self.last_size_lookup_ms=0

    @staticmethod
    def connected(adb:str='adb') -> list[str]:
        output=subprocess.run([adb,'devices'],capture_output=True,text=True,check=True,timeout=12).stdout
        return [line.split()[0] for line in output.splitlines()[1:] if line.strip().endswith('\tdevice')]

    def command(self,*args:str,timeout:float=15,check:bool=True) -> subprocess.CompletedProcess[bytes]:
        result=subprocess.run([self.adb,'-s',self.serial,*args],capture_output=True,timeout=timeout)
        if check and result.returncode:
            raise DeviceError(f'ADB command failed ({args[0]}): {result.stderr.decode(errors="replace")[:300]}')
        return result

    @contextmanager
    def suppress_credential_prompts(self):
        """Temporarily disable Android autofill and credential providers for a run."""
        keys=('autofill_service','credential_service','credential_service_primary')
        listing=self.command('shell','settings','list','secure').stdout.decode(errors='replace')
        original={}
        for line in listing.splitlines():
            key,separator,value=line.partition('=')
            if separator and key in keys:original[key]=value
        changed=[]
        try:
            for key in keys:
                # adb shell drops an empty argv item; quoted empty text survives remote parsing.
                self.command('shell','settings','put','secure',key,"''")
                changed.append(key)
                current=self.command('shell','settings','get','secure',key).stdout.decode(errors='replace').strip()
                if current:
                    raise DeviceError(f'Could not disable Android {key} for this run.')
            yield
        finally:
            errors=[]
            for key in reversed(changed):
                try:
                    current=self.command('shell','settings','get','secure',key).stdout.decode(errors='replace').strip()
                    if current:continue # Do not overwrite a setting changed during the run.
                    if key in original:self.command('shell','settings','put','secure',key,shlex.quote(original[key]))
                    else:self.command('shell','settings','delete','secure',key)
                    restored=self.command('shell','settings','get','secure',key).stdout.decode(errors='replace').strip()
                    if restored != original.get(key,'null'):
                        raise DeviceError(f'Android {key} restoration could not be verified.')
                except (DeviceError,subprocess.TimeoutExpired) as exc:
                    errors.append(f'{key}: {exc}')
            if errors:raise DeviceError('Could not restore Android credential settings: '+', '.join(errors))

    @contextmanager
    def suppress_notification_prompt(self, package:str):
        """Temporarily grant then silence Android 13+ notifications to avoid its runtime prompt."""
        if not package or not re.fullmatch(r'[A-Za-z0-9_.-]{3,240}',package):
            raise ValueError('A valid package is required to suppress notification prompts.')
        details=self.command('shell','dumpsys','package',package,timeout=20).stdout.decode(errors='replace')
        permission='android.permission.POST_NOTIFICATIONS'
        state=re.search(rf'{re.escape(permission)}: granted=(true|false)',details)
        if not state:
            # Older Android versions or apps that do not request notifications have no such prompt.
            yield
            return
        was_granted=state.group(1)=='true'
        appops=self.command('shell','cmd','appops','get',package,'POST_NOTIFICATION',check=False).stdout.decode(errors='replace')
        mode_match=re.search(r'POST_NOTIFICATION:\s*(\w+)',appops)
        original_mode=mode_match.group(1).lower() if mode_match else None
        permission_changed=False
        appop_changed=False
        try:
            if not was_granted:
                self.command('shell','pm','grant',package,permission,timeout=15)
                permission_changed=True
                updated=self.command('shell','dumpsys','package',package,timeout=20).stdout.decode(errors='replace')
                if not re.search(rf'{re.escape(permission)}: granted=true',updated):
                    raise DeviceError('Could not temporarily grant Android notification permission for this run.')
            if original_mode!='ignore':
                self.command('shell','cmd','appops','set',package,'POST_NOTIFICATION','ignore',timeout=15)
                appop_changed=True
            yield
        finally:
            errors=[]
            if appop_changed:
                try:
                    if original_mode:self.command('shell','cmd','appops','set',package,'POST_NOTIFICATION',original_mode,timeout=15)
                    else:self.command('shell','cmd','appops','set',package,'POST_NOTIFICATION','default',timeout=15)
                except (DeviceError,subprocess.TimeoutExpired) as exc:
                    errors.append(f'POST_NOTIFICATION app-op: {exc}')
            if permission_changed:
                try:
                    self.command('shell','pm','revoke',package,permission,timeout=15)
                except (DeviceError,subprocess.TimeoutExpired) as exc:
                    errors.append(f'{permission}: {exc}')
            if errors:raise DeviceError('Could not restore Android notification settings: '+', '.join(errors))

    def installed(self,package:str) -> bool:
        return bool(self.command('shell','pm','path',package,check=False).stdout.strip())

    def launch(self,package:str) -> None:
        if not self.installed(package):
            raise DeviceError(f'Package {package} is not installed on {self.serial}.')
        self.command('shell','monkey','-p',package,'-c','android.intent.category.LAUNCHER','1',timeout=20)

    def foreground(self) -> str:
        data=self.command('shell','dumpsys','activity','activities',timeout=15).stdout.decode(errors='replace')
        match=re.search(r'(?:mResumedActivity|topResumedActivity).*? ([\w.]+)/[\w.$]+',data)
        return match.group(1) if match else ''

    def size(self) -> tuple[int,int]:
        if self._screen_size is not None and time.monotonic()-self._screen_size_read_at<self.screen_size_cache_seconds:
            return self._screen_size
        data=self.command('shell','wm','size').stdout.decode(errors='replace')
        m=re.search(r'(?:Override|Physical) size: (\d+)x(\d+)',data)
        self._screen_size=(int(m.group(1)),int(m.group(2))) if m else (1080,1920)
        self._screen_size_read_at=time.monotonic()
        return self._screen_size

    def observe(self,retries:int=2) -> Screen:
        last=None
        total_started=time.perf_counter()
        timings={'uiautomator_dump_ms':0,'xml_transfer_ms':0,'parse_ms':0,'retries':0}
        # UiAutomator briefly reports "null root node" while a window is (re)attaching, e.g. right after launch.
        transient_budget=3
        attempt=0
        while attempt<retries:
            attempt+=1
            try:
                started=time.perf_counter()
                # `uiautomator dump` exits 0 even when it fails ("ERROR: could not get idle state" on animated
                # screens) and leaves the previous file behind; never read a dump from an earlier observation.
                self.command('shell','rm','-f','/sdcard/window.xml',timeout=10)
                dump=self.command('shell','uiautomator','dump','/sdcard/window.xml',timeout=18)
                timings['uiautomator_dump_ms']+=round((time.perf_counter()-started)*1000)
                message=(dump.stdout+dump.stderr).decode(errors='replace')
                if 'ERROR' in message:raise DeviceError('uiautomator dump failed: '+message.strip()[:200])
                started=time.perf_counter()
                raw=self.command('exec-out','cat','/sdcard/window.xml',timeout=12).stdout.decode('utf-8',errors='replace')
                timings['xml_transfer_ms']+=round((time.perf_counter()-started)*1000)
                started=time.perf_counter()
                root=ET.fromstring(raw)
                screen=self._parse(root,raw)
                timings['parse_ms']+=round((time.perf_counter()-started)*1000)
                timings['screen_size_lookup_ms']=self.last_size_lookup_ms
                timings['total_ms']=round((time.perf_counter()-total_started)*1000)
                self.last_observation_timings=timings
                return screen
            except (ET.ParseError,DeviceError,subprocess.TimeoutExpired) as exc:
                last=exc
                timings['retries']+=1
                if 'null root node' in str(exc) and transient_budget>0:
                    transient_budget-=1;attempt-=1;time.sleep(1.0);continue
                time.sleep(.3)
        timings['total_ms']=round((time.perf_counter()-total_started)*1000)
        self.last_observation_timings=timings
        raise DeviceError(f'Could not observe Android hierarchy: {last}')

    def _parse(self,root:ET.Element,raw:str) -> Screen:
        size_started=time.perf_counter()
        width,height=self.size()
        self.last_size_lookup_ms=round((time.perf_counter()-size_started)*1000)
        elements=[]
        texts=[]
        spatial_labels=[]
        for candidate in root.iter('node'):
            a=candidate.attrib
            label=a.get('text','').strip() or a.get('content-desc','').strip()
            bounds=BOUNDS.fullmatch(a.get('bounds',''))
            if label and label.casefold() not in GENERIC_LABELS and bounds and a.get('displayed','true')!='false':
                spatial_labels.append((label[:160],tuple(map(int,bounds.groups()))))
        def label_of(node:ET.Element) -> str:
            own=node.attrib.get('text','').strip() or node.attrib.get('content-desc','').strip()
            if own:return own[:160]
            for descendant in node.iter():
                if descendant is node:continue
                child=descendant.attrib.get('text','').strip() or descendant.attrib.get('content-desc','').strip()
                if child:return child[:160]
            return node.attrib.get('resource-id','').rsplit('/',1)[-1][:160]
        for node in root.iter('node'):
            a=node.attrib
            value=a.get('text','').strip()
            if value:texts.append(value)
            bounds=BOUNDS.fullmatch(a.get('bounds',''))
            if a.get('displayed','true')=='false' or not bounds:continue
            rect=tuple(map(int,bounds.groups()))
            if rect[2]<=rect[0] or rect[3]<=rect[1]:continue
            cls=a.get('class','')
            editable='EditText' in cls or a.get('editable')=='true'
            tappable=a.get('clickable')=='true' or a.get('checkable')=='true' or editable
            if not tappable:continue
            label=label_of(node)
            if label.casefold() in GENERIC_LABELS:
                label=''
            if not label:
                # Some apps expose a clickable container and its visible label as separate
                # accessibility nodes. Associate only text geometrically inside that control.
                x1,y1,x2,y2=rect
                contained=[(candidate,(cx1+cx2)//2,(cy1+cy2)//2) for candidate,(cx1,cy1,cx2,cy2) in spatial_labels if x1<=((cx1+cx2)//2)<=x2 and y1<=((cy1+cy2)//2)<=y2]
                if contained:
                    label=min(contained,key=lambda item:abs(item[1]-(x1+x2)//2)+abs(item[2]-(y1+y2)//2))[0]
                if not label:
                    # When the app omits a field's content-desc, a short heading aligned
                    # above a compact clickable surface can still ground its meaning.
                    cx=(x1+x2)//2;cy=(y1+y2)//2
                    headings=[(candidate,(cx1+cx2)//2,cy2) for candidate,(cx1,cy1,cx2,cy2) in spatial_labels if len(candidate)<=48 and cy2<=cy and abs(((cx1+cx2)//2)-cx)<=max(96,width//5)]
                    if headings:
                        label=min(headings,key=lambda item:(cy-item[2])+abs(item[1]-cx))[0]
            if not label:
                label=a.get('resource-id','').rsplit('/',1)[-1][:160]
            if editable and value:
                label=a.get('content-desc','').strip() or a.get('resource-id','').rsplit('/',1)[-1] or '<editable field>'
            sensitive=editable or a.get('password')=='true' or bool(SENSITIVE.search(f'{label} {a.get("resource-id","")}'))
            operations=[]
            # TYPE_TEXT focuses editable elements itself; exposing TAP as a separate
            # choice often leaves Jev looping on the focused field instead of typing.
            if tappable and not editable and a.get('enabled','true')!='false':operations.append('TAP')
            if editable:operations.append('TYPE_TEXT')
            role='textbox' if editable else 'button' if 'Button' in cls else 'control'
            password=a.get('password')=='true'
            checkable=a.get('checkable')=='true'
            elements.append(Element(str(len(elements)+1),role,'<credential field>' if password else label,a.get('resource-id',''),cls,value,rect,tuple(operations),sensitive,password,a.get('focused')=='true',a.get('checked')=='true',checkable))
            if len(elements)>=100:break
        joined_text=' '.join(texts)
        # Page text is sent to the selector; sensitive EditText values are removed later by Agent._public_screen.
        semantic=json.dumps({'text':texts,'elements':[(e.role,e.label,e.value,e.bounds,e.operations,e.checked,e.checkable,e.focused) for e in elements]},ensure_ascii=False)
        digest=hashlib.sha256(semantic.encode()).hexdigest()[:16]
        return Screen(raw,elements,' · '.join(texts)[:8000],digest,width,height)

    def screenshot(self,path:Path) -> None:
        data=self.command('exec-out','screencap','-p',timeout=15).stdout
        if not data.startswith(b'\x89PNG'):
            raise DeviceError('Screenshot was not a PNG.')
        path.write_bytes(data)

    @contextmanager
    def screen_recording(self, output:Path):
        """Capture a bounded, low-bitrate Android screen recording for one runner segment."""
        output.mkdir(parents=True, exist_ok=True)
        name=f"screen-recording-{time.time_ns()}.mp4"
        remote=f"/sdcard/Movies/jev-{uuid.uuid4().hex}.mp4"
        pid=None
        try:
            self.command('shell','mkdir','-p','/sdcard/Movies',timeout=10)
            started=self.command('shell',f'screenrecord --time-limit 180 --bit-rate 750000 {remote} >/dev/null 2>&1 & echo $!',timeout=10,check=False)
            match=re.search(rb'\b(\d+)\b',started.stdout)
            if started.returncode==0 and match:pid=match.group(1).decode()
            yield
        finally:
            if pid:
                try:
                    self.command('shell','kill','-INT',pid,timeout=10,check=False)
                    time.sleep(.8)
                    destination=output/name
                    pulled=self.command('pull',remote,str(destination),timeout=25,check=False)
                    if pulled.returncode or not destination.is_file() or destination.stat().st_size==0:
                        destination.unlink(missing_ok=True)
                except (DeviceError,subprocess.TimeoutExpired,OSError):
                    (output/name).unlink(missing_ok=True)
                finally:
                    self.command('shell','rm','-f',remote,timeout=10,check=False)

    def tap(self,element:Element) -> None:
        x,y=element.center
        self.command('shell','input','tap',str(x),str(y))

    def type_text(self,element:Element,value:str) -> None:
        if not value or len(value)>200:
            raise DeviceError('Input text must be 1–200 characters.')
        if not re.fullmatch(r'[A-Za-z0-9@._+!#$&*()=:/?\- ]+',value):
            raise DeviceError('ADB text input cannot safely type this value. Use a test account with supported ASCII characters.')
        if not element.focused:self.tap(element)
        if element.value:
            self.command('shell','input','keyevent','123') # MOVE_END
            for _ in range(min(len(element.value)+4,204)):
                self.command('shell','input','keyevent','67') # DEL
        self.command('shell','input','text',value.replace(' ','%s'))
        # Samsung's IME can finish committing characters after `input text` exits.
        time.sleep(1.2)
        if not element.password:
            deadline=time.monotonic()+5
            while True:
                current=self.observe()
                if any(e.role=='textbox' and e.value==value for e in current.elements):break
                if time.monotonic()>=deadline:
                    raise DeviceError('Text entry did not settle to the requested value.')
                time.sleep(.3)

    def swipe(self,direction:str,width:int,height:int) -> None:
        x=width//2
        y1,y2=(int(height*.75),int(height*.3)) if direction=='up' else (int(height*.3),int(height*.75))
        self.swipe_coordinates(x,y1,x,y2,320)

    def swipe_coordinates(self,x1:int,y1:int,x2:int,y2:int,duration_ms:int) -> None:
        self.command('shell','input','swipe',str(x1),str(y1),str(x2),str(y2),str(duration_ms))

    def drag_coordinates(self,x1:int,y1:int,x2:int,y2:int,duration_ms:int,hold_ms:int) -> None:
        raise DeviceError('Explicit drag hold requires the Appium adapter; no ADB fallback was attempted.')

    def swipe_scrollable_next_item(self,width:int,height:int,screen:Screen|None=None) -> dict:
        """Swipe through the largest accessible content viewport when available."""
        viewport=(0,0,width,int(height*.70))
        source='fallback_content_region'
        if screen and screen.xml:
            try:
                candidates=[]
                for node in ET.fromstring(screen.xml).iter('node'):
                    match=BOUNDS.fullmatch(node.get('bounds',''))
                    if node.get('scrollable')!='true' or node.get('enabled')=='false' or not match:continue
                    left,top,right,bottom=map(int,match.groups())
                    bounds=(max(0,left),max(0,top),min(width,right),min(height,bottom))
                    left,top,right,bottom=bounds
                    if right-left>=width*.5 and bottom-top>=height*.3:candidates.append(bounds)
                if candidates:
                    viewport=max(candidates,key=lambda b:(b[2]-b[0])*(b[3]-b[1]))
                    source='accessibility_scrollable_bounds'
            except ET.ParseError:
                pass
        left,top,right,bottom=viewport
        # Swipe through the content center so edge overlays or neighboring
        # gesture regions do not consume an instruction-driven gesture.
        x=left+(right-left)//2
        gesture={'start':[x,top+int((bottom-top)*.90)],'end':[x,top+int((bottom-top)*.10)],'duration_ms':300,'viewport':list(viewport),'source':source}
        self.swipe_coordinates(x,gesture['start'][1],x,gesture['end'][1],gesture['duration_ms'])
        return gesture

    def terminate(self, package: str) -> None:
        self.command('shell', 'am', 'force-stop', package)

    def hide_keyboard(self) -> None:
        self.back()

    def back(self) -> None:
        self.command('shell','input','keyevent','4')

    def wait_for_change(self,previous:Screen,timeout:float=4) -> Screen:
        deadline=time.monotonic()+timeout
        started=time.perf_counter()
        count=0
        observe_ms=0
        last=None
        while time.monotonic()<deadline:
            time.sleep(.25)
            last=self.observe()
            count+=1
            observe_ms+=self.last_observation_timings.get('total_ms',0)
            if last.fingerprint!=previous.fingerprint:break
        # The last poll is already a fresh observation; only observe again if no poll ran.
        if last is None:
            last=self.observe()
            count+=1
            observe_ms+=self.last_observation_timings.get('total_ms',0)
        self.last_wait_timings={'polls':count,'observe_total_ms':observe_ms,'total_ms':round((time.perf_counter()-started)*1000)}
        return last

    def wait_for_content(self,timeout:float=20) -> Screen:
        """Wait for content and a settled accessibility hierarchy after launch."""
        started=time.perf_counter()
        deadline=time.monotonic()+max(0,timeout)
        last=self.observe()
        observations=1
        observe_ms=self.last_observation_timings.get('total_ms',0)
        stable=0
        while time.monotonic()<deadline:
            time.sleep(.35)
            current=self.observe()
            observations+=1
            observe_ms+=self.last_observation_timings.get('total_ms',0)
            if current.fingerprint==last.fingerprint and (current.text.strip() or current.elements):
                stable+=1
                if stable>=1:
                    self.last_content_wait_timings={'observations':observations,'observe_total_ms':observe_ms,'total_ms':round((time.perf_counter()-started)*1000)}
                    return current
            else:stable=0
            last=current
        self.last_content_wait_timings={'observations':observations,'observe_total_ms':observe_ms,'total_ms':round((time.perf_counter()-started)*1000)}
        return last
