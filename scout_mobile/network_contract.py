"""Pure contract matching and structural assertions; observed values never leave memory."""
from __future__ import annotations
import json
import hashlib
import re
from urllib.parse import parse_qs, urlsplit

MISSING=object()

def pointer(value,path):
    if path=='':return value
    for token in path.split('/')[1:]:
        token=token.replace('~1','/').replace('~0','~')
        if isinstance(value,list) and re.fullmatch(r'0|[1-9][0-9]*',token):
            i=int(token)
            if i>=len(value):return MISSING
            value=value[i]
        elif isinstance(value,dict) and token in value:value=value[token]
        else:return MISSING
    return value

def path_parameters(template,path):
    expected=template.split('/');actual=path.split('/')
    if len(expected)!=len(actual):return None
    params={}
    for a,b in zip(expected,actual):
        if re.fullmatch(r'\{[A-Za-z][A-Za-z0-9_]*\}',a):
            if not b:return None
            params[a[1:-1]]=b
        elif a!=b:return None
    return params

class RequestView:
    def __init__(self,request,params=None):
        self.request=request;self.params=params or {};self.query=parse_qs(urlsplit(request.path).query,keep_blank_values=True)
        self.body=MISSING
        raw=getattr(request,'raw_content',None) or b''
        if len(raw)<=128000:
            try:self.body=json.loads(raw)
            except (ValueError,UnicodeError):pass
    def get(self,source,key):
        if source=='json':return pointer(self.body,key)
        if source=='header':return self.request.headers.get(key,MISSING)
        if source=='path':return self.params.get(key,MISSING)
        values=self.query.get(key,[])
        return values[0] if len(values)==1 else MISSING

def strict_equal(a,b):
    # JSON booleans are not interchangeable with integer 1/0.
    return a is not MISSING and type(a)==type(b) and a==b

def matches(rule,request):
    path=urlsplit(request.path).path
    if rule['host']!=request.host.lower() or ('method' in rule and rule['method']!=request.method):return None
    params=path_parameters(rule['path'],path) if rule.get('path_template') else {} if rule['path']==path else None
    if params is None:return None
    view=RequestView(request,params)
    for match in rule.get('match',[]):
        value=view.get(match['source'],match['key'])
        if match['operator']=='exists':
            if (value is not MISSING)!=match['value']:return None
        elif not strict_equal(value,match['value']):return None
    return view

def assert_structure(rule,view,previous):
    results=[]
    for assertion in rule.get('assertions',[]):
        value=view.get(assertion['source'],assertion['key']);kind=assertion['kind']
        available=value is not MISSING
        if kind=='exists':ok=available
        elif kind=='count':ok=available and isinstance(value,(list,dict)) and len(value)==assertion['expected']
        elif kind=='ordered':ok=available and isinstance(value,list) and strict_equal(value,assertion['expected'])
        elif kind=='duplicate':
            # In-memory history only; identifiers/payloads are never serialized in evidence.
            signature=hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest() if available else None
            ok=available and signature not in previous.setdefault(assertion['id'],[])
            if available:previous[assertion['id']].append(signature)
        else:ok=available and strict_equal(value,assertion['expected'])
        if kind=='duplicate' and len(previous.get(assertion['id'],[]))>5000:
            previous[assertion['id']]=previous[assertion['id']][:5000]
            results.append({'id':assertion['id'],'field':assertion['key'],'verdict':'not_observable','reason':'Duplicate history exceeded the bounded capture limit.'});continue
        results.append({'id':assertion['id'],'field':assertion['key'],'verdict':'satisfied' if ok else 'violated' if available or kind=='exists' else 'not_observable','reason':'Allowlisted structural predicate matched.' if ok else 'Allowlisted structural predicate missing or mismatched; observed values redacted.'})
    return results
