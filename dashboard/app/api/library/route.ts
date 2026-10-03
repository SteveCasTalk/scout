import { z } from 'zod';
import { context, failure, HttpError, jsonBody } from '@/lib/server';
import { decodeCase, caseSnapshotInput, retainRevision } from '@/lib/case-record';
import { runInput, type TestCase } from '@/lib/contracts';
import { matrixReference, type MatrixSnapshot } from '@/lib/scenario-matrix';

const queryInput = z.object({
    action:z.enum(['workspaces','cases','case','suites','history','run']).default('cases'),
    workspace:z.string().uuid().optional(), case_id:z.string().uuid().optional(),
    project:z.string().max(100).optional(), suite:z.string().max(80).optional(),
    platform:z.enum(['Android','iOS']).optional(), ticket_key:z.string().max(40).optional(),
    q:z.string().max(160).optional(), limit:z.coerce.number().int().min(1).max(50).default(20),
    cursor:z.string().max(1024).optional(), revision:z.coerce.number().int().positive().optional(),
    run_id:z.string().uuid().optional(),
    kind:z.enum(['runs','revisions']).default('runs'), include_snapshots:z.enum(['true','false']).default('false'),
});
function cursor(value?:string): {stamp:string;id:string} | null {
    if (!value) return null;
    try { return z.object({stamp:z.string().max(50),id:z.string().uuid()}).parse(JSON.parse(atob(value))); }
    catch { throw new HttpError(400,'Invalid history cursor.'); }
}
function page<T extends Record<string,unknown>>(rows:T[],limit:number,time:string) {
    const items=rows.slice(0,limit),last=items.at(-1);
    return {items,next_cursor:rows.length>limit && last ? btoa(JSON.stringify({stamp:last[time],id:last.id})) : null};
}
export async function GET(request:Request) { try {
    const {db,owner}=await context(request),p=queryInput.parse(Object.fromEntries(new URL(request.url).searchParams));
    if(p.action==='workspaces') {
        const offset=z.coerce.number().int().nonnegative().max(1000000).parse(p.cursor||0);
        const rows=await db.prepare('SELECT id,name,created FROM workspaces WHERE owner=? ORDER BY name,id LIMIT ? OFFSET ?').bind(owner,p.limit+1,offset).all();
        return Response.json({items:rows.results.slice(0,p.limit),next_cursor:rows.results.length>p.limit?String(offset+p.limit):null});
    }
    if(!p.workspace) throw new HttpError(400,'Workspace ID is required.');
    if(!await db.prepare('SELECT id FROM workspaces WHERE owner=? AND id=?').bind(owner,p.workspace).first()) throw new HttpError(404,'Workspace not found.');
    if(p.action==='run') {
        if(!p.run_id)throw new HttpError(400,'Saved run ID is required.');
        const row=await db.prepare('SELECT * FROM runs WHERE owner=? AND workspace_id=? AND id=?').bind(owner,p.workspace,p.run_id).first();
        if(!row)throw new HttpError(404,'Run not found in this workspace.');
        const {owner:_owner,snapshot,trace_json,device_info_json,...fields}=row;
        const evidence=await db.prepare('SELECT id,name,mime,size,created FROM evidence WHERE owner=? AND run_id=? ORDER BY created,id').bind(owner,p.run_id).all();
        const reviews=await db.prepare('SELECT checkpoint_id,original_verdict,decision,explanation,created FROM checkpoint_reviews WHERE owner=? AND workspace_id=? AND run_id=? ORDER BY created DESC').bind(owner,p.workspace,p.run_id).all();
        const notes=await db.prepare("SELECT id,body,created,updated FROM review_notes WHERE owner=? AND workspace_id=? AND target_type='run' AND target_id=? ORDER BY created DESC").bind(owner,p.workspace,p.run_id).all();
        return Response.json({run:{...fields,snapshot:JSON.parse(String(snapshot)),trace:JSON.parse(String(trace_json)),device_info:JSON.parse(String(device_info_json||'{}'))},evidence:evidence.results,checkpoint_reviews:reviews.results,notes:notes.results});
    }
    if(p.action==='case'||p.action==='history') {
        if(!p.case_id) throw new HttpError(400,'Case ID is required.');
        const row=await db.prepare('SELECT * FROM test_cases WHERE owner=? AND workspace_id=? AND id=?').bind(owner,p.workspace,p.case_id).first();
        if(!row) throw new HttpError(404,'Test case not found in this workspace.');
        const current=decodeCase(row);
        if(p.action==='case') {
            if(!p.revision||p.revision===current.revision) return Response.json({case:current,source:'current'});
            const retained=await db.prepare('SELECT snapshot_json FROM case_revisions WHERE owner=? AND workspace_id=? AND case_id=? AND revision=?').bind(owner,p.workspace,p.case_id,p.revision).first<{snapshot_json:string}>();
            const executed=retained?null:await db.prepare("SELECT snapshot FROM runs WHERE owner=? AND workspace_id=? AND case_id=? AND json_extract(snapshot,'$.revision')=? ORDER BY created DESC LIMIT 1").bind(owner,p.workspace,p.case_id,p.revision).first<{snapshot:string}>();
            if(!retained&&!executed) throw new HttpError(404,'Revision not retained. Older unexecuted edits cannot be recovered.');
            return Response.json({case:caseSnapshotInput.parse(JSON.parse(retained?.snapshot_json||executed!.snapshot)),source:retained?'retained_revision':'run_snapshot'});
        }
        if(p.kind==='revisions') {
            const before=p.cursor?z.coerce.number().int().positive().parse(p.cursor):2147483647;
            const rows=await db.prepare("SELECT revision FROM (SELECT revision FROM case_revisions WHERE owner=? AND workspace_id=? AND case_id=? UNION SELECT CAST(json_extract(snapshot,'$.revision') AS INTEGER) FROM runs WHERE owner=? AND workspace_id=? AND case_id=? UNION SELECT ?) WHERE revision<? ORDER BY revision DESC LIMIT ?").bind(owner,p.workspace,p.case_id,owner,p.workspace,p.case_id,current.revision,before,p.limit+1).all<{revision:number}>();
            const items=rows.results.slice(0,p.limit);
            return Response.json({items,next_cursor:rows.results.length>p.limit?String(items.at(-1)!.revision):null,current_revision:current.revision,history_note:'Retained edits and executed snapshots are available. Unexecuted edits made before revision retention are unavailable.'});
        }
        const after=cursor(p.cursor),where=after?' AND (created<? OR (created=? AND id<?))':'';
        const values: (string|number)[]=[owner,p.workspace,p.case_id];
        if(after) values.push(after.stamp,after.stamp,after.id);
        values.push(p.limit+1);
        const rows=await db.prepare('SELECT id,external_run_id,status,build,device,created,source,notes,snapshot FROM runs WHERE owner=? AND workspace_id=? AND case_id=?'+where+' ORDER BY created DESC,id DESC LIMIT ?').bind(...values).all();
        const result=page(rows.results,p.limit,'created');
        return Response.json({...result,items:result.items.map(({snapshot,...r})=>({...r,revision:JSON.parse(String(snapshot)).revision,matrix:JSON.parse(String(snapshot)).matrix,...(p.include_snapshots==='true'?{snapshot:JSON.parse(String(snapshot))}:{})})),current_revision:current.revision});
    }
    const clauses=['owner=?','workspace_id=?'],values:(string|number)[]=[owner,p.workspace];
    for(const key of ['project','suite','platform','ticket_key'] as const) if(p[key]!==undefined){clauses.push(key+'=?');values.push(p[key]!);}
    if(p.q){clauses.push("(instr(lower(title),lower(?))>0 OR instr(lower(goal),lower(?))>0)");values.push(p.q,p.q);}
    if(p.action==='suites') {
        const offset=z.coerce.number().int().nonnegative().max(1000000).parse(p.cursor||0);
        const rows=await db.prepare('SELECT project,suite,platform,COUNT(*) AS case_count FROM test_cases WHERE '+clauses.join(' AND ')+' GROUP BY project,suite,platform ORDER BY project,suite,platform LIMIT ? OFFSET ?').bind(...values,p.limit+1,offset).all();
        return Response.json({items:rows.results.slice(0,p.limit),next_cursor:rows.results.length>p.limit?String(offset+p.limit):null});
    }
    const after=cursor(p.cursor);
    if(after){clauses.push('(updated<? OR (updated=? AND id<?))');values.push(after.stamp,after.stamp,after.id);}
    const latest=" FROM runs r WHERE r.owner=test_cases.owner AND r.workspace_id=test_cases.workspace_id AND r.case_id=test_cases.id ORDER BY r.created DESC,r.id DESC LIMIT 1";
    const rows=await db.prepare('SELECT id,title,project,suite,platform,ticket_key,app_id,revision,updated,(SELECT status'+latest+') AS latest_run_status,(SELECT id'+latest+') AS latest_run_id FROM test_cases WHERE '+clauses.join(' AND ')+' ORDER BY updated DESC,id DESC LIMIT ?').bind(...values,p.limit+1).all();
    return Response.json(page(rows.results,p.limit,'updated'));
} catch(error){return failure(error);} }

const freezeInput=z.object({action:z.literal('freeze'),workspace:z.string().uuid(),cases:z.array(z.object({id:z.string().uuid(),revision:z.number().int().positive()})).min(1).max(100)});
const saveInput=z.object({action:z.literal('save_run'),workspace:z.string().uuid(),run:runInput.extend({externalRunId:z.string().regex(/^[A-Za-z0-9_-]{1,80}$/),matrix:matrixReference.optional()})});
export async function POST(request:Request) {try {
    const {db,owner}=await context(request,true),packet=z.discriminatedUnion('action',[freezeInput,saveInput]).parse(await jsonBody(request));
    if(packet.action==='freeze') {
        if(new Set(packet.cases.map(c=>c.id)).size!==packet.cases.length)throw new HttpError(400,'Choose each case once.');
        const cases:TestCase[]=[];
        for(const selected of packet.cases){
            const row=await db.prepare('SELECT * FROM test_cases WHERE owner=? AND workspace_id=? AND id=? AND revision=?').bind(owner,packet.workspace,selected.id,selected.revision).first();
            if(!row)throw new HttpError(409,'A case changed or is outside this workspace. Reload before running.');
            cases.push(decodeCase(row));
        }
        await db.batch(cases.map(c=>retainRevision(db,owner,c)));
        // Confirm every requested version has an authoritative retained definition.
        for(const c of cases)if(!await db.prepare('SELECT revision FROM case_revisions WHERE owner=? AND workspace_id=? AND case_id=? AND revision=?').bind(owner,packet.workspace,c.id,c.revision).first())throw new HttpError(409,'A case changed while freezing. Reload before running.');
        return Response.json({cases});
    }
    const r=packet.run;
    if(JSON.stringify(r.trace).length>200000)throw new HttpError(413,'Runner trace is too large.');
    const existing=await db.prepare('SELECT id,workspace_id,case_id,snapshot FROM runs WHERE owner=? AND external_run_id=?').bind(owner,r.externalRunId).first<{id:string;workspace_id:string;case_id:string;snapshot:string}>();
    if(existing){if(existing.workspace_id!==packet.workspace||existing.case_id!==r.caseId||JSON.stringify(JSON.parse(existing.snapshot).matrix)!==JSON.stringify(r.matrix))throw new HttpError(409,'Run ID already belongs to another case or variant.');return Response.json({id:existing.id,duplicate:true});}
    const retained=await db.prepare('SELECT snapshot_json FROM case_revisions WHERE owner=? AND workspace_id=? AND case_id=? AND revision=?').bind(owner,packet.workspace,r.caseId,r.revision).first<{snapshot_json:string}>();
    if(!retained)throw new HttpError(409,'Freeze the saved case revision before running.');
    let snapshot: TestCase | MatrixSnapshot = caseSnapshotInput.parse(JSON.parse(retained.snapshot_json));
    if(r.matrix) {
        const batch=await db.prepare('SELECT entries_json FROM matrix_batches WHERE id=? AND owner=? AND workspace_id=? AND matrix_id=? AND matrix_revision=? AND case_id=?').bind(r.matrix.batch_id,owner,packet.workspace,r.matrix.matrix_id,r.matrix.matrix_revision,r.caseId).first<{entries_json:string}>();
        const entry=batch ? (JSON.parse(batch.entries_json) as MatrixSnapshot[]).find(e=>e.matrix.variant_id===r.matrix!.variant_id) : undefined;
        if(!entry||entry.revision!==r.revision||entry.matrix.variant_label!==r.matrix.variant_label)throw new HttpError(409,'Matrix variant is not part of the frozen batch.');
        snapshot=entry;
        const prior=await db.prepare("SELECT id FROM runs WHERE owner=? AND workspace_id=? AND matrix_batch_id=? AND matrix_variant_id=?").bind(owner,packet.workspace,r.matrix.batch_id,r.matrix.variant_id).first();
        if(prior)throw new HttpError(409,'This batch variant already has a different run. Start a new batch to rerun it.');
    }
    const id=crypto.randomUUID(),created=new Date().toISOString();
    await db.prepare('INSERT INTO runs (id,owner,workspace_id,case_id,external_run_id,snapshot,status,build,device,device_info_json,app_logs,notes,source,trace_json,created,matrix_batch_id,matrix_variant_id) SELECT ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,? WHERE NOT EXISTS (SELECT 1 FROM runs WHERE owner=? AND external_run_id=?)').bind(id,owner,packet.workspace,r.caseId,r.externalRunId,JSON.stringify(snapshot),r.status,r.build,r.device,JSON.stringify(r.device_info),r.app_logs,r.notes,r.source,JSON.stringify(r.trace),created,r.matrix?.batch_id||null,r.matrix?.variant_id||null,owner,r.externalRunId).run();
    const stored=await db.prepare('SELECT id,workspace_id,case_id FROM runs WHERE owner=? AND external_run_id=?').bind(owner,r.externalRunId).first<{id:string;workspace_id:string;case_id:string}>();
    if(!stored||stored.workspace_id!==packet.workspace||stored.case_id!==r.caseId)throw new HttpError(409,'Run sync conflicted with another case.');
    return Response.json({id:stored.id,duplicate:stored.id!==id,created,snapshot},{status:stored.id===id?201:200});
}catch(error){return failure(error);} }
