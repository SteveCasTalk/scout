'use client';
import { readStoredItem } from '@/lib/browser-storage';
import { useEffect, useRef, useState } from 'react';
import { FlaskConical, Plus, Play, RefreshCw, Square } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { CheckpointEditor, CheckpointReport } from './checkpoints';
import { StartingConditionsReport } from './starting-conditions';
import { matrixInput, type ScenarioMatrix, type MatrixVariant, type MatrixReport } from '@/lib/scenario-matrix';
import type { TestCase, Run, CheckpointResult, StartingConditionResult } from '@/lib/contracts';
import type { SandboxScenario } from '@/lib/sandbox-contract';

const BRIDGE = 'http://127.0.0.1:8765';
async function request<T>(path: string, data?: unknown, method?: string) {
    const response = await fetch(path, data === undefined ? {} : {method:method || 'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    const result = await response.json();
    if (!response.ok) {const error = new Error((result as {error?:string}).error || 'Request failed.') as Error & {status:number}; error.status=response.status; throw error;}
    return result as T;
}
type MatrixSummary = Pick<ScenarioMatrix,'id'|'name'|'revision'> & {variant_count:number};
type BatchSummary = {id:string; matrix_name:string; created:string; summary:{status:string}};
type Progress = {session_id:string; status:string; current_case_index:number; total_cases:number; active_run_id:string|null; text_request?:{field:{label:string};instruction:string}|null; latest_screenshot?:{run_id:string;filename:string}|null; checkpoint_results?:CheckpointResult[]; starting_condition_results?:StartingConditionResult[]; error?:string; report_sync_error?:string; stop_reason?:string; skipped_entry_ids?:string[]; cases?:{variant_label:string}[]};
type Active = {sessionId:string;batchId:string;workspaceId:string;caseId:string};
type StartAttempt = {id:string;caseId:string;packet:Record<string,unknown>};

export function ScenarioMatrixPanel({test,onClose,onOpenRun,onRefresh,onBusy,disabled}:{test:TestCase|null;onClose:()=>void;onOpenRun:(run:Run)=>void;onRefresh:()=>Promise<void>;onBusy:(id:string|null)=>void;disabled:boolean}) {
    const [matrices,setMatrices]=useState<MatrixSummary[]>([]),[matrixId,setMatrixId]=useState(''),[revision,setRevision]=useState<number|null>(null),[name,setName]=useState(''),[variants,setVariants]=useState<MatrixVariant[]>([]),[base,setBase]=useState<TestCase|null>(null);
    const [selectedVariants,setSelectedVariants]=useState<string[]|null>(null);
    const [fixtures,setFixtures]=useState<SandboxScenario[]>([]),[fixtureId,setFixtureId]=useState(''),[batches,setBatches]=useState<BatchSummary[]>([]),[report,setReport]=useState<MatrixReport|null>(null);
    const [devices,setDevices]=useState<string[]>([]),[serial,setSerial]=useState(''),[limit,setLimit]=useState(40),[confirmed,setConfirmed]=useState(false),[allowConsent,setAllowConsent]=useState(false),[keepGoing,setKeepGoing]=useState(false);
    const [busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState(''),[dirty,setDirty]=useState(false),[text,setText]=useState(''),[progress,setProgress]=useState<Progress|null>(null),[active,setActive]=useState<Active|null>(null),[startAttempt,setStartAttempt]=useState<StartAttempt|null>(null);
    const refreshRef=useRef(onRefresh),busyRef=useRef(onBusy); refreshRef.current=onRefresh;busyRef.current=onBusy;
    useEffect(()=>{try {const saved=readStoredItem(sessionStorage, 'scout-matrix-session');if(saved)setActive(JSON.parse(saved));const pending=readStoredItem(sessionStorage, 'scout-matrix-start');if(pending){const attempt=JSON.parse(pending) as StartAttempt;setStartAttempt(attempt);if(!saved)setActive({sessionId:'session-'+attempt.id.replaceAll('-',''),batchId:attempt.id,workspaceId:String(attempt.packet.workspace_id),caseId:attempt.caseId});}}catch{sessionStorage.removeItem('scout-matrix-session');sessionStorage.removeItem('scout-matrix-start');}},[]);
    useEffect(()=>{if(startAttempt)sessionStorage.setItem('scout-matrix-start',JSON.stringify(startAttempt));else sessionStorage.removeItem('scout-matrix-start');},[startAttempt]);
    useEffect(()=>{if(active)sessionStorage.setItem('scout-matrix-session',JSON.stringify(active));else sessionStorage.removeItem('scout-matrix-session');busyRef.current(active?.caseId||null);},[active]);
    async function refreshLibrary(current:TestCase) {
        const query=`workspace=${encodeURIComponent(current.workspace_id)}&case_id=${encodeURIComponent(current.id)}`;
        const [definitions,history]=await Promise.all([request<{items:MatrixSummary[]}>(`/api/scenario-matrices?${query}`),request<{items:BatchSummary[]}>(`/api/scenario-matrices?${query}&action=batches`)]);
        setMatrices(definitions.items);setBatches(history.items);
    }
    async function refreshDevices(current:TestCase) {const data=await request<{devices:string[]}>(`${BRIDGE}/devices?platform=${current.platform}`);setDevices(data.devices);setSerial('');}
    useEffect(()=>{if(!test)return;if(startAttempt){setError('Resolve the pending start before changing settings. Retry uses the original request.');return;}let disposed=false;
        setBase(test);setMatrixId('');setRevision(null);setName(`${test.title} scenarios`.slice(0,120));setVariants([]);setReport(null);setConfirmed(false);setAllowConsent(false);setKeepGoing(false);setDirty(false);setSelectedVariants(null);setError('');setNotice('');setStartAttempt(null);setMatrices([]);setBatches([]);setDevices([]);setSerial('');setFixtures([]);
        void refreshLibrary(test).catch(e=>{if(!disposed)setError(e.message);});
        void refreshDevices(test).catch(e=>{if(!disposed)setError(e.message);});
        void request<{scenarios:SandboxScenario[]}>(`${BRIDGE}/sandbox`).then(data=>{if(!disposed)setFixtures(data.scenarios.filter(s=>s.project===test.project));}).catch(e=>{if(!disposed)setError(e.message);});
        if(active?.caseId===test.id)void request<MatrixReport>(`/api/scenario-matrices?workspace=${active.workspaceId}&batch_id=${active.batchId}`).then(data=>{if(!disposed)setReport(data);}).catch(e=>{if(!disposed)setError(e.message);});
        return()=>{disposed=true;};
    },[test]);
    function edited() {setSelectedVariants(null);setDirty(true);setConfirmed(false);setNotice('');setStartAttempt(null);}
    async function choose(id:string) {
        if(!test)return;
        if(!id){setMatrixId('');setRevision(null);setName(`${test.title} scenarios`.slice(0,120));setVariants([]);setSelectedVariants(null);setDirty(false);setStartAttempt(null);return;}
        setBusy(true);setError('');try {const data=await request<{matrix:ScenarioMatrix;case:TestCase}>(`/api/scenario-matrices?workspace=${test.workspace_id}&id=${id}`);setMatrixId(id);setRevision(data.matrix.revision);setName(data.matrix.name);setVariants(data.matrix.variants);setSelectedVariants(null);setBase(data.case);setDirty(false);setConfirmed(false);setStartAttempt(null);}catch(e){setError((e as Error).message);}finally{setBusy(false);}
    }
    function add() {
        const fixture=fixtures.find(s=>s.id===fixtureId);if(!fixture||!base)return;
        const expected=base.expected;
        setVariants(old=>[...old,{id:crypto.randomUUID(),label:fixture.name,sandbox:fixture,expected,checkpoints:base.checkpoints?.length?structuredClone(base.checkpoints):[{id:'matrix_goal',scope:'final',method:'classification',required:true,expected:expected.slice(0,1000)}]}]);edited();setFixtureId('');
    }
    function update(index:number,patch:Partial<MatrixVariant>) {setVariants(old=>old.map((v,i)=>i===index?{...v,...patch}:v));edited();}
    async function save() {
        if(!base)return;setBusy(true);setError('');try {
            const definition=matrixInput.parse({workspace_id:base.workspace_id,case_id:base.id,name,variants});
            const saved=await request<ScenarioMatrix>('/api/scenario-matrices',{...definition,...(matrixId?{id:matrixId,revision}:{})},matrixId?'PUT':'POST');
            setMatrixId(saved.id);setRevision(saved.revision);setVariants(saved.variants);setDirty(false);setConfirmed(false);setStartAttempt(null);setNotice('Matrix saved. Review each variant’s expected checkpoints before running.');await refreshLibrary(base);
        }catch(e){setError((e as Error).message);}finally{setBusy(false);}
    }
    async function sendAttempt(attempt:StartAttempt) {
        if(active?.batchId!==attempt.id)setProgress(null);
        setBusy(true);setError('');setStartAttempt(attempt);setActive({sessionId:'session-'+attempt.id.replaceAll('-',''),batchId:attempt.id,workspaceId:String(attempt.packet.workspace_id),caseId:attempt.caseId});
        try {const session=await request<Progress>(`${BRIDGE}/library-sessions`,attempt.packet);setProgress(session);setStartAttempt(null);setNotice('Matrix started. You can close this panel; execution continues in the local bridge.');}
        catch(e){const status=(e as Error & {status?:number}).status;if(status&&status<500){setStartAttempt(null);setActive(null);}setError(`${(e as Error).message}${!status||status>=500?' Retry uses the same start request to avoid duplicate runs.':''}`);}finally{setBusy(false);}
    }
    async function start() {
        if(!base||!matrixId||!revision||!serial||!confirmed||dirty||active)return;
        const id=crypto.randomUUID();await sendAttempt({id,caseId:base.id,packet:{request_id:id,dashboard_url:window.location.origin,workspace_id:base.workspace_id,matrix_id:matrixId,expected_matrix_revision:revision,expected_case_revision:base.revision,...(selectedVariants?{variant_ids:variants.filter(v=>selectedVariants.includes(v.id)).map(v=>v.id)}:{}),serial,start_mode:'relaunch',max_steps:limit,allow_consent:allowConsent,continue_on_failure:keepGoing,conditions_confirmed:true}});
    }
    useEffect(()=>{if(!active)return;let disposed=false,timer:ReturnType<typeof setTimeout>;
        async function poll(){try {
            const current=await request<Progress>(`${BRIDGE}/library-sessions/${active!.sessionId}`);if(disposed)return;setProgress(current);setStartAttempt(null);setError('');
            if(!['running','awaiting_input','stopping'].includes(current.status)){
                const saved=await request<MatrixReport>(`/api/scenario-matrices?workspace=${active!.workspaceId}&batch_id=${active!.batchId}`);if(disposed)return;setReport(saved);setActive(null);toast.info(`Scenario matrix ${current.status} · ${saved.rows.filter(r=>r.status==='Passed').length} / ${saved.rows.length} passed`);await refreshRef.current();if(base)await refreshLibrary(base);return;
            }
        }catch(e){if(!disposed)setError((e as Error).message);}if(!disposed)timer=setTimeout(poll,2000);}
        void poll();return()=>{disposed=true;clearTimeout(timer);};
    },[active,base]);
    async function respond(stop=false) {if(!active)return;setBusy(true);setError('');try {await request(`${BRIDGE}/library-sessions/${active.sessionId}/${stop?'stop':'input'}`,stop?{}:{text});setText('');}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
    async function openBatch(id:string) {if(!base)return;setBusy(true);setError('');try {setReport(await request<MatrixReport>(`/api/scenario-matrices?workspace=${base.workspace_id}&batch_id=${id}`));}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
    async function openRun(id:string) {if(!report)return;setBusy(true);try {const data=await request<{run:Run}>(`/api/library?action=run&workspace=${report.workspace_id}&run_id=${id}`);onOpenRun(data.run);onClose();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
    const selectedCount=selectedVariants?selectedVariants.length:variants.length;
    const locked=busy||!!active, valid=selectedCount>0&&!!matrixId&&!dirty&&!!serial&&confirmed&&!disabled&&Number.isInteger(limit)&&limit>=1&&limit<=100;
    return <>
        {active&&!test&&<section className="matrix-live-banner"><FlaskConical size={18}/><div><b>Scenario matrix · {(progress?.current_case_index||0)+1} / {progress?.total_cases||'…'}</b><p>{progress?.cases?.[progress.current_case_index]?.variant_label} · {progress?.status.replaceAll('_',' ')||'Starting'}</p>{error&&<p role="alert">{error}</p>}{progress?.error&&<p role="alert">{progress.error}</p>}{progress?.report_sync_error&&<p role="alert">{progress.report_sync_error}</p>}</div>{startAttempt?<Button size="sm" disabled={busy} onClick={()=>void sendAttempt(startAttempt)}>Retry start</Button>:<Button size="sm" variant="outline" disabled={busy} onClick={()=>void respond(true)}><Square size={12}/>Stop</Button>}{progress?.status==='awaiting_input'&&<div className="live-input"><label>{progress.text_request?.field.label}<input maxLength={200} value={text} onChange={e=>setText(e.target.value)}/></label><Button size="sm" disabled={busy||!text.trim()} onClick={()=>void respond()}>Enter text & resume</Button></div>}</section>}
        <Dialog open={!!test} onOpenChange={open=>{if(!open&&!busy)onClose();}}><DialogContent className="matrix-dialog"><DialogHeader><DialogTitle><FlaskConical size={20}/>Scenario matrix · {test?.title}</DialogTitle><DialogDescription>Run the same case against several frozen fixtures. Give each variant its own expected behavior and observable checkpoints.</DialogDescription></DialogHeader>
            {error&&<p role="alert" className="form-error">{error}</p>}{notice&&<p role="status" className="sandbox-notice">{notice}</p>}
            {startAttempt&&<Button disabled={busy} onClick={()=>void sendAttempt(startAttempt)}>Retry original start request</Button>}
            <div className="matrix-layout"><section className="matrix-editor"><div className="matrix-heading"><label>Saved matrix<select value={matrixId} disabled={locked} onChange={e=>void choose(e.target.value)}><option value="">New matrix</option>{matrices.map(m=><option value={m.id} key={m.id}>{m.name} · {m.variant_count} variants · v{m.revision}</option>)}</select></label><Button size="sm" variant="outline" disabled={locked} onClick={()=>base&&void refreshLibrary(base).catch(e=>setError(e.message))}><RefreshCw size={13}/>Refresh</Button></div>
                <label>Matrix name<input maxLength={120} disabled={locked} value={name} onChange={e=>{setName(e.target.value);edited();}}/></label><div className="matrix-heading"><label>Add a fixture<select disabled={locked} value={fixtureId} onChange={e=>setFixtureId(e.target.value)}><option value="">Choose a scenario</option>{fixtures.map(f=><option value={f.id} key={f.id}>{f.name}</option>)}</select></label><Button size="sm" variant="outline" disabled={locked||!fixtureId||variants.length>=20} onClick={add}><Plus size={13}/>Add variant</Button></div>
                {!fixtures.length&&<p>Save fixtures for {test?.project} in Settings → Sandbox, then reopen this panel.</p>}
                {!variants.length&&<div className="matrix-empty">Add at least two scenarios. Each variant keeps a copy of its selected fixture; library edits do not change it.</div>}
                {variants.map((variant,index)=><fieldset className="matrix-variant" key={variant.id} disabled={locked}><legend>{index+1}. {variant.label}</legend><label className="setup-confirm"><input type="checkbox" checked={selectedVariants===null||selectedVariants.includes(variant.id)} onChange={e=>{setSelectedVariants(old=>{const ids=old||variants.map(v=>v.id);return e.target.checked?[...ids,variant.id]:ids.filter(id=>id!==variant.id);});setConfirmed(false);}}/>Include in next run</label><label>Label<input maxLength={120} value={variant.label} onChange={e=>update(index,{label:e.target.value})}/></label><small>{variant.sandbox.name} · {variant.sandbox.http.length} HTTP · {variant.sandbox.websocket.length} WS</small><p>Review checkpoints when changing the expected outcome; they are not rewritten automatically.</p><label>Expected outcome<textarea rows={2} maxLength={4000} value={variant.expected} onChange={e=>update(index,{expected:e.target.value})}/></label><details open={!variant.checkpoints.length}><summary>Checkpoints · {variant.checkpoints.length} · review for this scenario</summary><CheckpointEditor value={variant.checkpoints} onChange={checkpoints=>update(index,{checkpoints})}/></details><details><summary>Frozen fixture definition</summary><pre>{JSON.stringify(variant.sandbox,null,2)}</pre></details><div className="row-actions"><Button size="sm" variant="outline" onClick={()=>{setSelectedVariants([variant.id]);setConfirmed(false);setNotice('One variant selected. Confirm its starting conditions, then run.');}}>Select only this variant</Button><Button size="sm" variant="ghost" disabled={index===0} onClick={()=>{setVariants(old=>{const next=[...old];[next[index-1],next[index]]=[next[index],next[index-1]];return next;});edited();}}>Move up</Button><Button size="sm" variant="ghost" onClick={()=>{setVariants(old=>old.filter(v=>v.id!==variant.id));edited();}}>Remove</Button></div></fieldset>)}
                <Button disabled={locked||variants.length<2||!name.trim()} onClick={()=>void save()}>{dirty?'Save changes':'Save matrix'}</Button>
            </section><section className="matrix-run-setup"><h3>Run variants in order · {selectedCount} selected</h3><Button size="sm" variant="ghost" disabled={locked} onClick={()=>{setSelectedVariants(null);setConfirmed(false);}}>Select all variants</Button><p>Same device and base case v{base?.revision}. The app relaunches and prerequisites are checked before every variant. Relaunch keeps account and app data.</p><details><summary>Shared case steps · v{base?.revision}</summary><p className="preserve">{base?.steps}</p><p>{base?.preconditions}</p></details><StartingConditionsReport defined={base?.starting_conditions}/><p>Prepare the device proxy and test CA. Each fixture starts with fresh response counters.</p>
                <label>Device<select value={serial} disabled={locked} onChange={e=>{setSerial(e.target.value);setStartAttempt(null);}}><option value="">Choose a connected device</option>{devices.map(d=><option key={d}>{d}</option>)}</select></label><Button size="sm" variant="ghost" disabled={locked} onClick={()=>base&&void refreshDevices(base).catch(e=>setError(e.message))}>Refresh devices</Button>
                <label>Maximum actions per variant<input type="number" min={1} max={100} disabled={locked} value={limit} onChange={e=>{setLimit(Number(e.target.value));setStartAttempt(null);}}/></label>
                <label className="setup-confirm"><input type="checkbox" disabled={locked} checked={keepGoing} onChange={e=>{setKeepGoing(e.target.checked);setConfirmed(false);setStartAttempt(null);}}/>Continue after Failed or Inconclusive UI checks. Blocked prerequisites, runner/proxy problems and failed result sync always stop the matrix.</label>
                <label className="setup-confirm"><input type="checkbox" disabled={locked} checked={allowConsent} onChange={e=>{setAllowConsent(e.target.checked);setStartAttempt(null);}}/>Allow required permission and Terms/Privacy prompts.</label>
                <label className="setup-confirm"><input type="checkbox" disabled={locked} checked={confirmed} onChange={e=>{setConfirmed(e.target.checked);setStartAttempt(null);}}/>I reviewed the selected variants’ checkpoints, prepared proxy routing and starting conditions, and confirmed variants can safely run in this order.</label>
                <Button disabled={locked||!valid} onClick={()=>void start()}><Play size={14}/>{selectedCount===1?'Run variant':`Run matrix · ${selectedCount} variants`}</Button>{dirty&&<p>Save changes before running.</p>}
                {active&&<section className="matrix-progress"><h3>Variant {(progress?.current_case_index||0)+1} / {progress?.total_cases}</h3><p>{progress?.cases?.[progress.current_case_index]?.variant_label} · {progress?.status.replaceAll('_',' ')}</p><Button variant="outline" size="sm" disabled={busy} onClick={()=>void respond(true)}><Square size={12}/>Stop matrix</Button>{progress?.latest_screenshot&&<img src={`${BRIDGE}/runs/${progress.latest_screenshot.run_id}/artifacts/${progress.latest_screenshot.filename}`} alt="Latest guarded matrix capture"/>}{progress?.status==='awaiting_input'&&<div className="live-input"><p>{progress.text_request?.instruction}</p><label>{progress.text_request?.field.label}<input maxLength={200} value={text} onChange={e=>setText(e.target.value)}/></label><Button disabled={busy||!text.trim()} onClick={()=>void respond()}>Enter text & resume</Button></div>}<StartingConditionsReport results={progress?.starting_condition_results||[]}/><CheckpointReport results={progress?.checkpoint_results||[]}/>{progress?.report_sync_error&&<p role="alert">{progress.report_sync_error}</p>}</section>}
            </section></div>
            <section className="matrix-results"><div className="matrix-heading"><h3>Matrix results</h3><select aria-label="Matrix execution history" disabled={busy} value={report?.batch_id||''} onChange={e=>void openBatch(e.target.value)}><option value="">Choose a previous batch</option>{batches.map(b=><option key={b.id} value={b.id}>{b.matrix_name} · {new Date(b.created).toLocaleString()} · {b.summary.status}</option>)}</select></div>
                {report?<><p>{report.matrix_name} v{report.matrix_revision} · Case v{report.case_revision} · {report.status}{report.summary.stop_reason&&` · ${report.summary.stop_reason.replaceAll('_',' ')}`}</p>{report.summary.error&&<p role="alert" className="form-error">{report.summary.error}</p>}<div className="matrix-table"><table><thead><tr><th>Scenario</th><th>Expected</th><th>Outcome</th><th>Checkpoints</th><th>Evidence</th></tr></thead><tbody>{report.rows.map(row=><tr key={row.variant_id}><td><b>{row.label}</b><small>{row.scenario.name}</small></td><td>{row.expected}</td><td><span className={`status status-${row.status.toLowerCase().replaceAll(' ','-')}`}>{row.status}</span>{row.runner_error&&<p>{row.runner_error}</p>}{row.sync_error&&<p>{row.sync_error}</p>}{!!row.evidence_failures?.length&&<p>{row.evidence_failures.length} evidence uploads need retry.</p>}</td><td>{row.run_id?`${row.checkpoint_results?.filter(c=>c.verdict==='satisfied').length||0} / ${row.checkpoints.length}`:'—'}{row.checkpoint_results?.filter(c=>c.verdict!=='satisfied').map(c=><small key={c.id}>{c.id}: {c.reason}</small>)}</td><td>{row.run_id?<Button size="sm" variant="outline" disabled={busy} onClick={()=>void openRun(row.run_id!)}>Open run</Button>:row.external_run_id?<small>Saved locally · {row.external_run_id}</small>:'Not available'}</td></tr>)}</tbody></table></div><p>Outcomes belong to each variant’s own expected behavior. A correctly handled server error can pass. Open a run for screenshots, recording and network coverage.</p></>:<p>Run the matrix to compare outcomes and evidence here.</p>}
            </section>
        </DialogContent></Dialog>
    </>;
}
