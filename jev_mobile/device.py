"""Android UI hierarchy observation and bounded device actions through ADB."""
from __future__ import annotations
from dataclasses import dataclass
from contextlib import contextmanager
import hashlib
import json
import re
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
    def __init__(self,serial:str,adb:str='adb'):
        self.serial=serial
        self.adb=adb

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
                    if key in original:self.command('shell','settings','put','secure',key,original[key])
                    else:self.command('shell','settings','delete','secure',key)
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
        data=self.command('shell','wm','size').stdout.decode(errors='replace')
        m=re.search(r'(?:Override|Physical) size: (\d+)x(\d+)',data)
        return (int(m.group(1)),int(m.group(2))) if m else (1080,1920)

    def observe(self,retries:int=2) -> Screen:
        last=None
        for _ in range(retries):
            try:
                self.command('shell','uiautomator','dump','/sdcard/window.xml',timeout=18)
                raw=self.command('exec-out','cat','/sdcard/window.xml',timeout=12).stdout.decode('utf-8',errors='replace')
                root=ET.fromstring(raw)
                return self._parse(root,raw)
            except (ET.ParseError,DeviceError,subprocess.TimeoutExpired) as exc:
                last=exc
                time.sleep(.3)
        raise DeviceError(f'Could not observe Android hierarchy: {last}')

    def _parse(self,root:ET.Element,raw:str) -> Screen:
        width,height=self.size()
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
            if tappable and not editable:operations.append('TAP')
            if editable:operations.append('TYPE_TEXT')
            role='textbox' if editable else 'button' if 'Button' in cls else 'control'
            password=a.get('password')=='true'
            checkable=a.get('checkable')=='true'
            elements.append(Element(str(len(elements)+1),role,'<credential field>' if password else label,a.get('resource-id',''),cls,value,rect,tuple(operations),sensitive,password,a.get('focused')=='true',a.get('checked')=='true',checkable))
            if len(elements)>=100:break
        joined_text=' '.join(texts)
        # Twomi's feed bottom navigation renders the profile avatar without an
        # accessibility action. Add a screenshot-verified relative-coordinate fallback.
        if re.search(r'swipe\s+up\s+to\s+select\s+your\s+companion',joined_text,re.I) and not any(e.label.casefold() in {'profile','me','account'} for e in elements):
            bounds=(round(width*.80),round(height*.84),round(width*.91),round(height*.91))
            elements.append(Element(str(len(elements)+1),'button','Profile','jev:visual-fallback:twomi-profile-tab','coordinate-fallback','',bounds,('TAP',),False))
        # Page text is sent to the selector; sensitive EditText values are removed later by Agent._public_screen.
        semantic=json.dumps({'text':texts,'elements':[(e.role,e.label,e.value,e.bounds,e.operations,e.checked,e.checkable,e.focused) for e in elements]},ensure_ascii=False)
        digest=hashlib.sha256(semantic.encode()).hexdigest()[:16]
        return Screen(raw,elements,' · '.join(texts)[:8000],digest,width,height)

    def screenshot(self,path:Path) -> None:
        data=self.command('exec-out','screencap','-p',timeout=15).stdout
        if not data.startswith(b'\x89PNG'):
            raise DeviceError('Screenshot was not a PNG.')
        path.write_bytes(data)

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
        self.command('shell','input','swipe',str(x),str(y1),str(x),str(y2),'320')

    def swipe_companion_next_item(self,width:int,height:int,screen:Screen|None=None) -> dict:
        """Start inside the feed's scrollable viewport, not the controls below it."""
        viewport=(0,0,width,int(height*.70))
        source='fallback_video_region'
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
        x=left+(right-left)//4
        gesture={'start':[x,top+int((bottom-top)*.90)],'end':[x,top+int((bottom-top)*.10)],'duration_ms':300,'viewport':list(viewport),'source':source}
        self.command('shell','input','swipe',str(x),str(gesture['start'][1]),str(x),str(gesture['end'][1]),str(gesture['duration_ms']))
        return gesture

    def back(self) -> None:
        self.command('shell','input','keyevent','4')

    def wait_for_change(self,previous:Screen,timeout:float=4) -> Screen:
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            time.sleep(.25)
            next_screen=self.observe()
            if next_screen.fingerprint!=previous.fingerprint:
                return next_screen
        return self.observe()

    def wait_for_content(self,timeout:float=20) -> Screen:
        """Wait for an app splash screen to expose its first accessible content."""
        deadline=time.monotonic()+max(0,timeout)
        last=self.observe()
        while not last.text.strip() and not last.elements and time.monotonic()<deadline:
            time.sleep(.25)
            last=self.observe()
        return last
