'use client';
import { useEffect, useState } from 'react';
import { z } from 'zod';
import type { Evidence } from '@/lib/contracts';
import type { Execution } from '@/lib/execution-contract';
const reportInput=z.object({schema_version:z.literal(2),truncated:z.boolean(),samples:z.array(z.unknown()).max(5000),events:z.array(z.unknown()).max(500),assertions:z.array(z.object({id:z.string(),verdict:z.string(),reason:z.string().optional(),evidence_source:z.string().optional(),verifier:z.string().optional(),evidence:z.string().optional(),trigger_ms:z.number().optional(),deadline_ms:z.number().optional(),coverage_complete:z.boolean().optional()})).max(24)});
export function ExecutionEvidence({definition,files}:{definition:Execution|null|undefined;files:Evidence[]}){
 const file=files.find(f=>f.name==='execution-evidence.json');
 const fileId=file?.id;
 const [loaded,setLoaded]=useState<{fileId:string;report?:z.infer<typeof reportInput>;error?:string}|null>(null);
 const report=loaded?.fileId===fileId?loaded?.report:null,error=loaded?.fileId===fileId?loaded?.error:'';
 useEffect(()=>{let active=true;if(fileId)fetch('/api/evidence/'+fileId).then(r=>{if(!r.ok)throw new Error('Could not load execution evidence.');return r.json();}).then(r=>{const parsed=reportInput.parse(r);if(active)setLoaded({fileId,report:parsed});}).catch(e=>{if(active)setLoaded({fileId,error:e.message});});return()=>{active=false;};},[fileId]);
 if(!definition&&!file)return null;
 return <section className="panel"><h2>Execution evidence</h2>{error&&<p role="alert">{error}</p>}{!report&&<p>{file?'Loading evidence…':'Execution evidence has not been attached. This view cannot establish the result.'}</p>}{report&&<><p>{report.samples.length} UI samples · {report.events.length} recorded events{report.truncated?' · capture truncated':''}</p>{report.assertions.map((r,i)=><div key={`${r.id}-${i}`}><b>{r.id} · {r.verdict.replaceAll('_',' ')}</b><p>{r.reason}</p><small>{r.verifier||r.evidence_source}{r.trigger_ms!==undefined?` · window ${r.trigger_ms}–${r.deadline_ms} ms`:''}{r.coverage_complete===false?' · observation coverage incomplete':''}</small>{r.evidence&&<p>Source: {r.evidence}</p>}</div>)}<p>Sampled UI cannot prove continuous absence. Media checks establish only their declared file measurements. Purchase-entry evidence covers reaching checkout.</p><details><summary>Recorded execution events</summary><pre>{JSON.stringify(report.events,null,2)}</pre></details></>}</section>;
}
