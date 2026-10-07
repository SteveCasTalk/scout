import { context, failure, jsonBody, HttpError, bucket } from '@/lib/server';
import { runInput, startingConditionsInput } from '@/lib/contracts';
import { z } from 'zod';
import { runClearEvidenceCount, runClearPlan, runClearTables } from '@/lib/run-delete';
export async function GET(request: Request) { try {
    const { db, owner } = await context(request);
    const { results } = await db.prepare('SELECT id,workspace_id,case_id,external_run_id,snapshot,status,build,device,device_info_json,app_logs,notes,source,trace_json,created FROM runs WHERE owner=? ORDER BY created DESC').bind(owner).all();
    return Response.json(results.map(r => { const { device_info_json, trace_json, ...fields } = r; const snapshot = JSON.parse(String(r.snapshot)); return { ...fields, device_info: JSON.parse(String(device_info_json || '{}')), snapshot: { ...snapshot, starting_conditions: startingConditionsInput.parse(snapshot.starting_conditions || {}) }, trace: JSON.parse(String(trace_json)) }; }));
}
catch (e) {
    return failure(e);
} }
export async function POST(request: Request) { try {
    const { db, owner } = await context(request, true);
    const r = runInput.parse(await jsonBody(request));
    if (r.externalRunId) {
        const previous = await db.prepare('SELECT id FROM runs WHERE owner=? AND external_run_id=?').bind(owner, r.externalRunId).first<{id:string}>();
        if (previous) return Response.json({ id: previous.id, duplicate: true }, { status: 200 });
    }
    const c = await db.prepare('SELECT id,workspace_id,project,ticket_key,comparison_key,sandbox_json,execution_json,app_id,title,platform,suite,goal,preconditions,steps,expected,assertion_text,checkpoints_json,starting_conditions_json,revision,updated FROM test_cases WHERE id=? AND owner=?').bind(r.caseId, owner).first<{workspace_id:string; revision:number; checkpoints_json:string; starting_conditions_json:string; sandbox_json:string; execution_json:string}>();
    if (!c)
        throw new HttpError(404, 'Test case not found.');
    if (c.revision !== r.revision)
        throw new HttpError(409, 'The test changed. Reload it before recording this run.');
    if (JSON.stringify(r.trace).length > 200000) throw new HttpError(413, 'Runner trace is too large.');
    const { sandbox_json, execution_json, checkpoints_json, starting_conditions_json, ...fields } = c;
    const snapshot = { ...fields, execution: JSON.parse(execution_json || 'null'), sandbox: JSON.parse(sandbox_json || 'null'), checkpoints: JSON.parse(checkpoints_json || '[]'), starting_conditions: startingConditionsInput.parse(JSON.parse(starting_conditions_json || '{}')) };
    const id = crypto.randomUUID(), created = new Date().toISOString();
    await db.prepare('INSERT INTO runs (id,owner,workspace_id,case_id,external_run_id,snapshot,status,build,device,device_info_json,app_logs,notes,source,trace_json,created) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)').bind(id, owner, c.workspace_id, r.caseId, r.externalRunId || null, JSON.stringify(snapshot), r.status, r.build, r.device, JSON.stringify(r.device_info), r.app_logs, r.notes, r.source, JSON.stringify(r.trace), created).run();
    return Response.json({ ...r, id, workspace_id: c.workspace_id, case_id: r.caseId, snapshot, created }, { status: 201 });
}
catch (e) {
    return failure(e);
} }
const clearInput = z.object({ workspace_id: z.string().uuid(), case_id: z.string().uuid().nullish() });
// Permanently clears run history for a workspace, or for one case when case_id is given:
// runs (including scenario-matrix runs), their evidence rows and R2 objects, run notes,
// checkpoint reviews, platform comparisons using them, and matrix batches. Test cases,
// revisions, scenario matrices, case notes and authoring records are kept.
export async function DELETE(request: Request) { try {
    const { db, owner } = await context(request, true);
    const p = clearInput.parse(await jsonBody(request));
    const workspace = await db.prepare('SELECT id FROM workspaces WHERE id=? AND owner=?').bind(p.workspace_id, owner).first();
    if (!workspace) throw new HttpError(404, 'Workspace not found.');
    if (p.case_id && !await db.prepare('SELECT id FROM test_cases WHERE id=? AND owner=? AND workspace_id=?').bind(p.case_id, owner, p.workspace_id).first())
        throw new HttpError(404, 'Test case not found.');
    const target = { owner, workspaceId: p.workspace_id, caseId: p.case_id };
    // Refuse before touching D1 when evidence blobs exist but storage is unbound, so a
    // clear never strands unreferenced R2 objects because of missing configuration.
    const count = runClearEvidenceCount(target);
    const files = await db.prepare(count.sql).bind(...count.binds).first<{ n: number }>();
    const storage = Number(files?.n) > 0 ? bucket() : null;
    const results = await db.batch(runClearPlan(target).map(s => db.prepare(s.sql).bind(...s.binds)));
    const keys = (results[runClearTables.indexOf('evidence')].results as { object_key: string }[]).map(row => String(row.object_key));
    if (keys.length) {
        // R2 is not part of the D1 transaction; the rows are already gone, so a failed blob
        // delete only leaves unreferenced objects. Report it without failing the request.
        try { const store = storage || bucket(); for (let i = 0; i < keys.length; i += 1000) await store.delete(keys.slice(i, i + 1000)); }
        catch (error) { console.error('Cleared run evidence objects could not be removed', { workspaceId: p.workspace_id, caseId: p.case_id, count: keys.length }, error); }
    }
    return Response.json({
        deleted_runs: Number(results[runClearTables.indexOf('runs')].meta.changes) || 0,
        deleted_evidence: keys.length,
        deleted_batches: Number(results[runClearTables.indexOf('matrix_batches')].meta.changes) || 0,
    });
}
catch (e) {
    return failure(e);
} }
