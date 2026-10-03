import { z } from 'zod';
import { context, failure, HttpError, jsonBody } from '@/lib/server';
import { decodeCase, retainRevision } from '@/lib/case-record';
import { applyVariant, decodeMatrix, matrixInput, type MatrixSnapshot } from '@/lib/scenario-matrix';
import { statuses, type Run } from '@/lib/contracts';

const freezeInput = z.object({ action: z.literal('freeze'), workspace_id: z.string().uuid(), matrix_id: z.string().uuid(), batch_id: z.string().uuid(), request_signature: z.string().regex(/^[a-f0-9]{64}$/),
    expected_revision: z.number().int().positive(), expected_case_revision: z.number().int().positive(), variant_ids: z.array(z.string().regex(/^[A-Za-z0-9_-]{1,40}$/)).min(1).max(20).optional(),
    settings: z.object({ serial: z.string().min(1).max(160), max_steps: z.number().int().min(1).max(100), start_mode: z.literal('relaunch'), allow_consent: z.boolean(), continue_on_failure: z.boolean(), conditions_confirmed: z.literal(true) }) });
const outcomeInput = z.object({ entry_id: z.string().max(40), case_id: z.string().uuid(), revision: z.number().int().positive(), run_id: z.string().max(80), status: z.enum(statuses), dashboard_run_id: z.string().uuid().optional(), runner_error: z.string().max(500).optional(), sync_error: z.string().max(500).optional(), evidence_failures: z.array(z.string().max(100)).max(300).optional() });
const progressInput = z.object({ action: z.literal('progress'), workspace_id: z.string().uuid(), batch_id: z.string().uuid(), summary: z.object({
    status: z.enum(['prepared','running','awaiting_input','stopping','completed','stopped','error','interrupted']), current_case_index: z.number().int().min(0).max(19), active_run_id: z.string().max(80).nullable(),
    outcomes: z.array(outcomeInput).max(20), skipped_entry_ids: z.array(z.string().max(40)).max(20), stop_reason: z.string().max(80).optional(), error: z.string().max(500).optional(), finished_at: z.string().max(50).optional(),
}) });

async function ownedWorkspace(db: D1Database, owner: string, workspace: string) {
    if (!await db.prepare('SELECT id FROM workspaces WHERE owner=? AND id=?').bind(owner, workspace).first()) throw new HttpError(404, 'Workspace not found.');
}
async function report(db: D1Database, owner: string, workspace: string, id: string) {
    const batch = await db.prepare('SELECT * FROM matrix_batches WHERE owner=? AND workspace_id=? AND id=?').bind(owner, workspace, id).first();
    if (!batch) throw new HttpError(404, 'Matrix batch not found.');
    const entries = JSON.parse(String(batch.entries_json)) as MatrixSnapshot[], summary = JSON.parse(String(batch.summary_json));
    const saved = await db.prepare("SELECT id,external_run_id,status,build,device,trace_json,snapshot FROM runs WHERE owner=? AND workspace_id=? AND matrix_batch_id=? ORDER BY created DESC,id DESC").bind(owner, workspace, id).all();
    const artifacts = await db.prepare('SELECT run_id,name FROM evidence WHERE owner=? AND run_id IN (SELECT id FROM runs WHERE owner=? AND workspace_id=? AND matrix_batch_id=?)').bind(owner,owner,workspace,id).all();
    const rows = entries.map(entry => {
        const run = saved.results.find(r => JSON.parse(String(r.snapshot)).matrix?.variant_id === entry.matrix.variant_id);
        const local = summary.outcomes?.find((r: {entry_id:string}) => r.entry_id === entry.matrix.variant_id);
        const skipped = summary.skipped_entry_ids?.includes(entry.matrix.variant_id);
        const trace = run ? JSON.parse(String(run.trace_json)) as Run['trace'] : [];
        return { variant_id: entry.matrix.variant_id, label: entry.matrix.variant_label, expected: entry.expected, checkpoints: entry.checkpoints, scenario: { id: entry.sandbox!.id, name: entry.sandbox!.name },
            status: run?.status || local?.status || (skipped ? 'Skipped' : ['error','interrupted','stopped'].includes(summary.status) ? 'Not run' : 'Pending'),
            run_id: run?.id, external_run_id: run?.external_run_id || local?.run_id, build: run?.build, device: run?.device,
            checkpoint_results: [...trace].reverse().find(s => s.checkpoint_results)?.checkpoint_results || [],
            runner_error: local?.runner_error, sync_error: run ? undefined : local?.sync_error, evidence_failures: (local?.evidence_failures || []).filter((name:string)=>!artifacts.results.some(e=>e.run_id===run?.id&&e.name===name)) };
    });
    return { batch_id: id, workspace_id: workspace, matrix_id: batch.matrix_id, matrix_revision: batch.matrix_revision, matrix_name: batch.matrix_name,
        case_id: batch.case_id, case_revision: entries[0].revision, created: batch.created, status: summary.status, rows, summary };
}

export async function GET(request: Request) { try {
    const {db, owner} = await context(request);
    const p = z.object({workspace:z.string().uuid(), id:z.string().uuid().optional(), case_id:z.string().uuid().optional(), batch_id:z.string().uuid().optional(), action:z.enum(['matrices','batches']).default('matrices'), limit:z.coerce.number().int().min(1).max(50).default(20), cursor:z.coerce.number().int().min(0).max(1000000).default(0)}).parse(Object.fromEntries(new URL(request.url).searchParams));
    await ownedWorkspace(db, owner, p.workspace);
    if (p.batch_id) return Response.json(await report(db, owner, p.workspace, p.batch_id));
    if (p.id) {
        const row = await db.prepare('SELECT * FROM scenario_matrices WHERE id=? AND owner=? AND workspace_id=?').bind(p.id,owner,p.workspace).first();
        if (!row) throw new HttpError(404,'Matrix not found.');
        const matrix = decodeMatrix(row);
        const base = await db.prepare('SELECT * FROM test_cases WHERE id=? AND owner=? AND workspace_id=?').bind(matrix.case_id,owner,p.workspace).first();
        if (!base) throw new HttpError(404,'Base case not found.');
        return Response.json({matrix,case:decodeCase(base)});
    }
    const table = p.action === 'batches' ? 'matrix_batches' : 'scenario_matrices';
    const fields = p.action === 'batches' ? 'id,matrix_id,matrix_revision,matrix_name,case_id,created,summary_json' : 'id,case_id,name,revision,updated,definition_json';
    const order = p.action === 'batches' ? 'created' : 'updated';
    const rows = await db.prepare(`SELECT ${fields} FROM ${table} WHERE owner=? AND workspace_id=?${p.case_id?' AND case_id=?':''} ORDER BY ${order} DESC,id DESC LIMIT ? OFFSET ?`).bind(owner,p.workspace,...(p.case_id?[p.case_id]:[]),p.limit+1,p.cursor).all();
    return Response.json({items:rows.results.slice(0,p.limit).map(({definition_json,summary_json,...row}) => ({...row,...(definition_json?{variant_count:JSON.parse(String(definition_json)).variants.length}:{}),...(summary_json?{summary:JSON.parse(String(summary_json))}:{})})), next_cursor:rows.results.length>p.limit?String(p.cursor+p.limit):null});
} catch(error) {return failure(error);} }

export async function POST(request: Request) { try {
    const {db,owner} = await context(request,true), raw = await jsonBody(request);
    const action = z.object({action:z.string().optional()}).parse(raw).action;
    if (action === 'progress') {
        const p = progressInput.parse(raw);
        const batch = await db.prepare('SELECT entries_json FROM matrix_batches WHERE id=? AND owner=? AND workspace_id=?').bind(p.batch_id,owner,p.workspace_id).first();
        if (!batch) throw new HttpError(404,'Matrix batch not found.');
        const entries = JSON.parse(String(batch.entries_json)) as MatrixSnapshot[], ids = entries.map(e => e.matrix.variant_id);
        if (p.summary.current_case_index >= ids.length || new Set(p.summary.outcomes.map(r => r.entry_id)).size !== p.summary.outcomes.length || p.summary.outcomes.some(r => !entries.some(e => e.matrix.variant_id === r.entry_id && e.id === r.case_id && e.revision === r.revision)) || p.summary.skipped_entry_ids.some(id => !ids.includes(id))) throw new HttpError(400,'Progress does not match the frozen matrix entries.');
        await db.prepare('UPDATE matrix_batches SET summary_json=? WHERE id=? AND owner=? AND workspace_id=?').bind(JSON.stringify(p.summary),p.batch_id,owner,p.workspace_id).run();
        return Response.json({accepted:true});
    }
    if (action === 'freeze') {
        const p = freezeInput.parse(raw);
        const existing = await db.prepare('SELECT request_signature,entries_json,matrix_name,matrix_revision,summary_json FROM matrix_batches WHERE id=? AND owner=? AND workspace_id=?').bind(p.batch_id,owner,p.workspace_id).first();
        if (existing) {
            if (existing.request_signature !== p.request_signature) throw new HttpError(409,'Batch ID already has different settings.');
            const executed=await db.prepare('SELECT id FROM runs WHERE owner=? AND workspace_id=? AND matrix_batch_id=? LIMIT 1').bind(owner,p.workspace_id,p.batch_id).first();
            if (executed || JSON.parse(String(existing.summary_json)).status !== 'prepared') throw new HttpError(409,'This batch was already accepted. Inspect its report; use a new request ID for an intentional rerun.');
            return Response.json({cases:JSON.parse(String(existing.entries_json)),matrix_name:existing.matrix_name,matrix_revision:existing.matrix_revision});
        }
        const row = await db.prepare('SELECT * FROM scenario_matrices WHERE id=? AND owner=? AND workspace_id=? AND revision=?').bind(p.matrix_id,owner,p.workspace_id,p.expected_revision).first();
        if (!row) throw new HttpError(409,'The matrix changed. Reload before running.');
        const matrix = decodeMatrix(row);
        const baseRow = await db.prepare('SELECT * FROM test_cases WHERE id=? AND owner=? AND workspace_id=? AND revision=?').bind(matrix.case_id,owner,p.workspace_id,p.expected_case_revision).first();
        if (!baseRow) throw new HttpError(409,'The base case changed. Reload before running.');
        const base = decodeCase(baseRow), ids = p.variant_ids || matrix.variants.map(v => v.id);
        if (new Set(ids).size !== ids.length || ids.some(id => !matrix.variants.some(v => v.id === id))) throw new HttpError(400,'Select unique variants from this matrix.');
        if (matrix.variants.some(v => v.sandbox.project !== base.project)) throw new HttpError(409,'Fixture projects must match the base case.');
        const entries = ids.map(id => applyVariant(base,matrix,matrix.variants.find(v => v.id===id)!,p.batch_id)), created = new Date().toISOString();
        await db.batch([retainRevision(db,owner,base),db.prepare('INSERT INTO matrix_batches (id,owner,workspace_id,matrix_id,matrix_revision,matrix_name,case_id,entries_json,settings_json,request_signature,summary_json,created) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)').bind(p.batch_id,owner,p.workspace_id,matrix.id,matrix.revision,matrix.name,base.id,JSON.stringify(entries),JSON.stringify(p.settings),p.request_signature,JSON.stringify({status:'prepared',outcomes:[],skipped_entry_ids:[]}),created)]);
        return Response.json({cases:entries,matrix_name:matrix.name,matrix_revision:matrix.revision},{status:201});
    }
    const p = matrixInput.parse(raw);
    await ownedWorkspace(db,owner,p.workspace_id);
    const base = await db.prepare('SELECT project FROM test_cases WHERE owner=? AND workspace_id=? AND id=?').bind(owner,p.workspace_id,p.case_id).first();
    if (!base) throw new HttpError(404,'Base case not found.');
    if (p.variants.some(v => v.sandbox.project !== base.project)) throw new HttpError(400,'Choose fixtures from the case project.');
    const id = crypto.randomUUID(), updated = new Date().toISOString();
    await db.prepare('INSERT INTO scenario_matrices (id,owner,workspace_id,case_id,name,revision,definition_json,updated) VALUES (?,?,?,?,?,1,?,?)').bind(id,owner,p.workspace_id,p.case_id,p.name,JSON.stringify(p),updated).run();
    return Response.json({...p,id,revision:1,updated},{status:201});
} catch(error) {return failure(error);} }

export async function PUT(request: Request) { try {
    const {db,owner} = await context(request,true), raw = await jsonBody(request), p = matrixInput.parse(raw);
    const {id,revision} = z.object({id:z.string().uuid(),revision:z.number().int().positive()}).parse(raw);
    const base = await db.prepare('SELECT project FROM test_cases WHERE owner=? AND workspace_id=? AND id=?').bind(owner,p.workspace_id,p.case_id).first();
    if (!base || p.variants.some(v => v.sandbox.project !== base.project)) throw new HttpError(400,'Base case or fixture project is invalid.');
    const updated = new Date().toISOString();
    const result = await db.prepare('UPDATE scenario_matrices SET name=?,revision=revision+1,definition_json=?,updated=? WHERE id=? AND owner=? AND workspace_id=? AND case_id=? AND revision=?').bind(p.name,JSON.stringify(p),updated,id,owner,p.workspace_id,p.case_id,revision).run();
    if (!result.meta.changes) throw new HttpError(409,'The matrix changed. Reload before saving.');
    return Response.json({...p,id,revision:revision+1,updated});
} catch(error) {return failure(error);} }
