"""Owner-scoped local dashboard APIs using the normal development sign-in flow."""
from __future__ import annotations
from http.cookiejar import CookieJar
import json
import mimetypes
from pathlib import Path
import re
import threading
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPCookieProcessor, HTTPRedirectHandler
from urllib.error import HTTPError
import uuid

from .config import ROOT


def local_url(value: str) -> str:
    if not isinstance(value,str):
        raise ValueError('A local dashboard URL is required.')
    url = urlsplit(value)
    if (url.scheme != 'http' or url.hostname not in {'localhost', '127.0.0.1', '::1'}
            or url.username or url.password or url.path not in {'', '/'} or url.query or url.fragment
            or url.port not in range(5173, 5190)):
        raise ValueError('Saved-library MCP tools require the local dashboard on port 5173–5189. Hosted authentication is not supported.')
    return value.rstrip('/')


class LocalRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).netloc != urlsplit(req.full_url).netloc or urlsplit(newurl).scheme != 'http':
            raise ValueError('The local dashboard redirected outside its origin. Sign in through the dashboard instead.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class DashboardClient:
    def __init__(self, base_url: str):
        self.url = local_url(base_url)
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()), LocalRedirect())
        self.lock = threading.RLock()

    def request(self, path, packet=None, *, data=None, content_type='application/json', method=None):
        if not path.startswith('/api/'):
            raise ValueError('Dashboard request must target an API route.')
        if packet is not None:
            data = json.dumps(packet, ensure_ascii=False).encode()
        headers = {'Origin': self.url, 'Content-Type': content_type}
        with self.lock:
            for attempt in range(2):
                try:
                    with self.opener.open(Request(self.url+path, data=data, headers=headers, method=method), timeout=30) as response:
                        body = response.read(8_000_001)
                    if len(body) > 8_000_000:
                        raise ValueError('Dashboard response too large. Request a smaller page.')
                    return json.loads(body)
                except HTTPError as exc:
                    if exc.code == 401 and attempt == 0:
                        # Obtain the normal localhost development cookie, never inject
                        # owner headers or bypass a hosted authentication provider.
                        try:
                            with self.opener.open(self.url+'/signin-with-chatgpt?return_to=/api/health', timeout=10) as response:
                                response.read(4096)
                        except (OSError, ValueError):
                            raise ValueError('Local dashboard sign-in unavailable. These tools use local development authentication only.') from None
                        continue
                    try:
                        message = json.loads(exc.read(4096)).get('error', 'Dashboard request failed.')
                    except ValueError:
                        message = 'Dashboard request failed.'
                    raise ValueError(str(message)[:500]) from None
                except (OSError, UnicodeError):
                    raise ValueError('Local dashboard unavailable. Keep it running and retry.') from None
        raise ValueError('Sign in to the local dashboard to access the saved library.')

    def library(self, **params):
        return self.request('/api/library?'+urlencode({k:v for k,v in params.items() if v is not None}))

    def delete_test_case(self, workspace_id: str, case_id: str, expected_revision: int) -> dict:
        """Permanently delete a saved case and everything that belongs only to it.

        Removes its revisions, runs, evidence files, notes, checkpoint reviews, platform
        comparisons, scenario matrices, matrix batches and authoring records. The
        dashboard answers 409 when the case revision changed and 404 when not found.
        """
        workspace_id, case_id = str(uuid.UUID(workspace_id)), str(uuid.UUID(case_id))
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 1:
            raise ValueError('expected_revision must be the positive revision you last read.')
        return self.request('/api/cases', {'id': case_id, 'workspace_id': workspace_id, 'revision': expected_revision}, method='DELETE')

    def upload(self, run_id: str, path: Path):
        if not path.stat().st_size or path.stat().st_size > 25*1024*1024:
            raise ValueError('Evidence files must be nonempty and at most 25 MB.')
        boundary = 'scout'+uuid.uuid4().hex
        mime = mimetypes.guess_type(path.name)[0] or 'application/json'
        data = (f'--{boundary}\r\nContent-Disposition: form-data; name="runId"\r\n\r\n{run_id}\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\nContent-Type: {mime}\r\n\r\n').encode()
        return self.request('/api/evidence', data=data+path.read_bytes()+f'\r\n--{boundary}--\r\n'.encode(), content_type='multipart/form-data; boundary='+boundary)


def sync_run(client: DashboardClient, run_id: str, workspace_id: str) -> dict:
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', run_id):
        raise ValueError('Invalid local run ID.')
    folder = ROOT/'runner-output'/run_id
    if not (folder/'.saved-case.json').is_file() or not (folder/'result.json').is_file():
        raise ValueError('A completed saved-library run with its pinned definition is required.')
    result = json.loads((folder/'result.json').read_text())
    pinned = json.loads((folder/'.saved-case.json').read_text())
    if pinned['workspace_id'] != workspace_id or pinned['id'] != result['case_id'] or pinned['revision'] != result['revision']:
        raise ValueError('Run does not belong to this workspace and pinned revision.')
    trace=[]
    for step in result['steps']:
        entry={key:step[key] for key in ('step','operation','label','elapsed_ms','screenshot','verification','checkpoint_results','starting_condition_results') if key in step}
        if step.get('jev'):
            audit=step['jev']
            entry['jev']={'request':{'model':audit['request'].get('model',''),'questions':audit['request'].get('questions',{})},'response':audit['response'],'latency_ms':audit['latency_ms']}
        trace.append(entry)
    body={'caseId':pinned['id'],'revision':pinned['revision'],'externalRunId':run_id,
          'status':result['status'],'build':result.get('build') or 'unknown','device':result.get('device') or 'unknown',
          'device_info':result.get('device_info',{}),'app_logs':result.get('app_logs',''),
          'notes':result.get('notes') or 'No runner notes.','source':'Scout import','trace':trace}
    if pinned.get('matrix'):
        body['matrix']=pinned['matrix']
    saved=client.request('/api/library',{'action':'save_run','workspace':workspace_id,'run':body})
    evidence=client.request('/api/evidence?'+urlencode({'run_id':saved['id']}))
    existing={e['name'] for e in evidence}
    uploaded,failed=[],[]
    for file in sorted(folder.iterdir()):
        from .evidence import allowed
        if not allowed(folder,file.name):
            continue
        if file.name in existing:
            continue
        try:
            client.upload(saved['id'],file)
            uploaded.append(file.name)
        except (OSError, ValueError):
            failed.append(file.name)
    return {'dashboard_run_id':saved['id'],'uploaded_evidence':uploaded,'evidence_failures':failed,
            'dashboard_url':client.url+'/?'+urlencode({'workspace':workspace_id,'run':saved['id']})}
