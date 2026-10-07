"""Local dashboard API verification, not mobile app test execution.
Run against a local preview with initialized storage: python3 checks/api-smoke.py
Creates labeled verification records in the local development database.
"""
import json, urllib.request, urllib.error, http.cookiejar, uuid
BASE='http://localhost:5173'
jar=http.cookiejar.CookieJar()
client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
client.open(BASE+'/signin-with-chatgpt?return_to=/').read()
def call(path,body=None,method=None,expected=200,headers=None,raw=None):
    h=headers or {}
    if body is not None:h={**h,'Content-Type':'application/json'}
    req=urllib.request.Request(BASE+path,data=raw if raw is not None else json.dumps(body).encode() if body is not None else None,method=method,headers=h)
    try:r=client.open(req)
    except urllib.error.HTTPError as e:r=e
    data=r.read()
    assert r.status==expected,(path,r.status,data)
    return json.loads(data) if 'application/json' in r.headers.get('Content-Type','') else data
workspace=call('/api/workspaces',{'name':'[Dashboard verification] '+uuid.uuid4().hex[:8]},'POST',201)
c={'workspace_id':workspace['id'],'project':'Arcana','app_id':'com.example.arcana','title':'[Dashboard verification] Invalid sign-in','platform':'Android','suite':'Dashboard verification','goal':'Verify a rejected login','preconditions':'Synthetic dashboard data only; no device execution','steps':'Open sign in\nEnter invalid credentials\nSubmit','expected':'Error appears'}
created=call('/api/cases',c,'POST',201)
assert created['project']=='Arcana' and created['app_id']=='com.example.arcana' and created['workspace_id']==workspace['id']
call('/api/cases',{**c,'title':' '},'POST',400)
r=call('/api/runs',{'caseId':created['id'],'revision':1,'status':'Inconclusive','build':'synthetic-1','device':'No device — dashboard check','notes':'Synthetic API verification. This is not a mobile test result.'},'POST',201)
updated=call('/api/cases',{**created,'expected':'Revised expectation'},'PUT')
assert updated['revision']==2
call('/api/cases',created,'PUT',409)
call('/api/runs',{'caseId':created['id'],'revision':1,'status':'Passed','build':'x','device':'x','notes':'x'},'POST',409)
stored=next(x for x in call('/api/runs') if x['id']==r['id'])
assert stored['snapshot']['revision']==1 and stored['snapshot']['expected']=='Error appears'
boundary='jev-evidence-check'
payload=(f'--{boundary}\r\nContent-Disposition: form-data; name="runId"\r\n\r\n{r["id"]}\r\n--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="dashboard-check.txt"\r\nContent-Type: text/plain\r\n\r\nSynthetic evidence: dashboard storage verified.\r\n--{boundary}--\r\n').encode()
e=call('/api/evidence',method='POST',expected=201,headers={'Content-Type':f'multipart/form-data; boundary={boundary}'},raw=payload)
assert call('/api/evidence/'+e['id'])==b'Synthetic evidence: dashboard storage verified.'
assert call('/api/evidence/'+e['id'],headers={'Range':'bytes=0-8'},expected=206)==b'Synthetic'
call('/api/cases',c,'POST',403,headers={'Origin':'https://unrelated.example'})
try:urllib.request.urlopen(BASE+'/api/cases')
except urllib.error.HTTPError as auth_error:assert auth_error.code==401
else:raise AssertionError('Anonymous access was not rejected')
assert any(x['id']==created['id'] for x in call('/api/cases'))
assert any(x['id']==e['id'] for x in call('/api/evidence'))
external_run_id='prompt-smoke-'+uuid.uuid4().hex
prompt_run={'caseId':created['id'],'revision':2,'externalRunId':external_run_id,'status':'Execution error','build':'3.34.0','device':'emulator-5554','notes':'Synthetic prompt-run dashboard smoke check.','source':'Prompt run','trace':[{'step':0,'operation':'OBSERVE','elapsed_ms':100,'label':None,'screenshot':'000.png'}]}
imported=call('/api/runs', prompt_run, 'POST', 201)
duplicate=call('/api/runs', prompt_run, 'POST', 200)
assert duplicate['duplicate'] and duplicate['id']==imported['id']
assert imported['source']=='Prompt run' and imported['trace'][0]['operation']=='OBSERVE'
assert next(x for x in call('/api/runs') if x['id']==imported['id'])['trace'][0]['screenshot']=='000.png'
stored_prompt=next(x for x in call('/api/runs') if x['id']==imported['id'])
assert stored_prompt['snapshot']['project']=='Arcana' and stored_prompt['snapshot']['app_id']=='com.example.arcana' and stored_prompt['external_run_id']==external_run_id
doomed=call('/api/cases',{**c,'title':'[Dashboard verification] Delete me'},'POST',201)
doomed_run=call('/api/runs',{'caseId':doomed['id'],'revision':1,'status':'Inconclusive','build':'synthetic-1','device':'No device — dashboard check','notes':'Synthetic delete check.'},'POST',201)
call('/api/notes',{'target_type':'case','target_id':doomed['id'],'body':'Synthetic delete check.'},'POST',201)
deletion={'id':doomed['id'],'workspace_id':workspace['id'],'revision':1}
call('/api/cases',{**deletion,'revision':2},'DELETE',409)
call('/api/cases',deletion,'DELETE',403,headers={'Origin':'https://unrelated.example'})
assert call('/api/cases',deletion,'DELETE')=={'deleted':True,'id':doomed['id']}
call('/api/cases',deletion,'DELETE',404)
assert not any(x['id']==doomed['id'] for x in call('/api/cases')) and not any(x['id']==doomed_run['id'] for x in call('/api/runs'))
assert not any(x['target_id']==doomed['id'] for x in call('/api/notes?workspace='+workspace['id']))
print('PASS: create/project grouping, validation, revision conflict, immutable run snapshot, stale-run rejection, evidence upload/read/range, list persistence, cross-origin rejection, anonymous rejection, prompt-run trace and deduplication, case deletion (stale revision, cross-origin, cascade, repeat 404).')
print(json.dumps({'caseId':created['id'],'runId':r['id'],'evidenceId':e['id']}))
