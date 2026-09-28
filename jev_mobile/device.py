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

    @property
    def signature(self) -> tuple[str,str,str,tuple[int,int,int,int]]:
        return self.resource_id,self.class_name,self.label,self.bounds

    @property
    def center(self) -> tuple[int,int]:
        x1,y1,x2,y2=self.bounds
        return (x1+x2)//2,(y1+y2)//2

    def public(self) -> dict:
        return dict(index=self.index,role=self.role,label=self.label,resource_id=self.resource_id,value='<redacted>' if self.sensitive and self.value else self.value,operations=list(self.operations))

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
            if editable and value:
                label=a.get('content-desc','').strip() or a.get('resource-id','').rsplit('/',1)[-1] or '<editable field>'
            sensitive=editable or a.get('password')=='true' or bool(SENSITIVE.search(f'{label} {a.get("resource-id","")}'))
            operations=[]
            if tappable:operations.append('TAP')
            if editable:operations.append('TYPE_TEXT')
            role='textbox' if editable else 'button' if 'Button' in cls else 'control'
            password=a.get('password')=='true'
            elements.append(Element(str(len(elements)+1),role,'<credential field>' if password else label,a.get('resource-id',''),cls,value,rect,tuple(operations),sensitive,password,a.get('focused')=='true'))
            if len(elements)>=100:break
        # Page text is sent to the selector; sensitive EditText values are removed later by Agent._public_screen.
        semantic=json.dumps({'text':texts,'elements':[(e.role,e.label,e.value,e.bounds) for e in elements]},ensure_ascii=False)
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
