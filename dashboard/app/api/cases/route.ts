import { context, failure, jsonBody, HttpError, bucket } from '@/lib/server';
import { caseInput, startingConditionsInput } from '@/lib/contracts';
import { z } from 'zod';
import { decodeCase, retainRevision } from '@/lib/case-record';
import { caseDeletionPlan } from '@/lib/case-delete';
export async function GET(request: Request) { try {
    const { db, owner } = await context(request);
    const rows = await db.prepare('SELECT id,workspace_id,project,ticket_key,comparison_key,sandbox_json,execution_json,app_id,title,platform,suite,goal,preconditions,steps,expected,assertion_text,checkpoints_json,starting_conditions_json,revision,updated FROM test_cases WHERE owner=? ORDER BY updated DESC').bind(owner).all();
    return Response.json(rows.results.map(({ sandbox_json, checkpoints_json, starting_conditions_json, execution_json, ...row }) => ({ ...row, execution: JSON.parse(String(execution_json || 'null')), sandbox: JSON.parse(String(sandbox_json || 'null')), checkpoints: JSON.parse(String(checkpoints_json || '[]')), starting_conditions: startingConditionsInput.parse(JSON.parse(String(starting_conditions_json || '{}'))) })));
}
catch (e) {
    return failure(e);
} }
export async function POST(request: Request) { try {
    const { db, owner } = await context(request, true);
    const c = caseInput.parse(await jsonBody(request));
    if((c.execution || c.sandbox?.schema_version===2) && request.headers.get('X-Scout-Contract') !== '2') throw new HttpError(409, 'Use a capability-aware client to author this case.');
    const workspace = await db.prepare('SELECT id FROM workspaces WHERE id=? AND owner=?').bind(c.workspace_id, owner).first();
    if (!workspace) throw new HttpError(404, 'Workspace not found.');
    const id = crypto.randomUUID(), updated = new Date().toISOString();
    await db.batch([db.prepare('INSERT INTO test_cases (id,owner,workspace_id,project,ticket_key,comparison_key,sandbox_json,execution_json,app_id,title,platform,suite,goal,preconditions,steps,expected,assertion_text,checkpoints_json,starting_conditions_json,revision,updated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)').bind(id, owner, c.workspace_id, c.project, c.ticket_key, c.comparison_key, JSON.stringify(c.sandbox), JSON.stringify(c.execution || null), c.app_id, c.title, c.platform, c.suite, c.goal, c.preconditions, c.steps, c.expected, c.assertion_text, JSON.stringify(c.checkpoints), JSON.stringify(c.starting_conditions), updated),retainRevision(db,owner,{...c,id,revision:1,updated})]);
    return Response.json({ ...c, id, revision: 1, updated }, { status: 201 });
}
catch (e) {
    return failure(e);
} }
export async function PUT(request: Request) { try {
    const { db, owner } = await context(request, true);
    const raw = await jsonBody(request);
    const c = caseInput.extend({ id: z.string().uuid(), revision: z.number().int().positive() }).parse(raw);
    const workspace = await db.prepare('SELECT id FROM workspaces WHERE id=? AND owner=?').bind(c.workspace_id, owner).first();
    if (!workspace) throw new HttpError(404, 'Workspace not found.');
    const updated = new Date().toISOString();
    const previous = await db.prepare('SELECT * FROM test_cases WHERE id=? AND owner=? AND workspace_id=? AND revision=?').bind(c.id,owner,c.workspace_id,c.revision).first();
    if ((c.execution || (previous && decodeCase(previous).execution)) && (request.headers.get('X-Scout-Contract') !== '2' || !Object.prototype.hasOwnProperty.call(raw,'execution'))) throw new HttpError(409,'Reload a capability-aware editor; execution settings cannot be silently dropped.');
    if (!previous) throw new HttpError(409, 'This test changed elsewhere. Reload the library before editing again.');
    if ((c.sandbox?.schema_version===2 || decodeCase(previous).sandbox?.schema_version===2) && (request.headers.get('X-Scout-Contract') !== '2' || !Object.prototype.hasOwnProperty.call(raw,'sandbox'))) throw new HttpError(409,'Reload a capability-aware editor; sandbox settings cannot be silently dropped.');
    const [,result] = await db.batch([retainRevision(db,owner,decodeCase(previous)), db.prepare('UPDATE test_cases SET project=?,ticket_key=?,comparison_key=?,sandbox_json=?,execution_json=?,app_id=?,title=?,platform=?,suite=?,goal=?,preconditions=?,steps=?,expected=?,assertion_text=?,checkpoints_json=?,starting_conditions_json=?,revision=revision+1,updated=? WHERE id=? AND owner=? AND workspace_id=? AND revision=?').bind(c.project, c.ticket_key, c.comparison_key, JSON.stringify(c.sandbox), JSON.stringify(c.execution || null), c.app_id, c.title, c.platform, c.suite, c.goal, c.preconditions, c.steps, c.expected, c.assertion_text, JSON.stringify(c.checkpoints), JSON.stringify(c.starting_conditions), updated, c.id, owner, c.workspace_id, c.revision), retainRevision(db,owner,{...c,revision:c.revision+1,updated})]);
    if (!result.meta.changes)
        throw new HttpError(409, 'This test changed elsewhere. Reload the library before editing again.');
    return Response.json({ ...c, revision: c.revision + 1, updated });
}
catch (e) {
    return failure(e);
} }
const deleteInput = z.object({ id: z.string().uuid(), workspace_id: z.string().uuid(), revision: z.number().int().positive() });
// Permanently removes a case with its revisions, runs, evidence, notes, reviews,
// platform comparisons, scenario matrices, matrix batches and authoring records.
export async function DELETE(request: Request) { try {
    const { db, owner } = await context(request, true);
    const p = deleteInput.parse(await jsonBody(request));
    const current = await db.prepare('SELECT revision FROM test_cases WHERE id=? AND owner=? AND workspace_id=?').bind(p.id, owner, p.workspace_id).first<{ revision: number }>();
    if (!current) throw new HttpError(404, 'Test case not found.');
    if (Number(current.revision) !== p.revision) throw new HttpError(409, 'This test changed elsewhere. Reload the library before deleting it.');
    // Refuse before touching D1 when evidence blobs exist but storage is unbound, so a
    // delete never strands unreferenced R2 objects because of missing configuration.
    const files = await db.prepare('SELECT COUNT(*) AS n FROM evidence WHERE owner=? AND run_id IN (SELECT id FROM runs WHERE owner=? AND case_id=?)').bind(owner, owner, p.id).first<{ n: number }>();
    const storage = Number(files?.n) > 0 ? bucket() : null;
    const results = await db.batch(caseDeletionPlan({ owner, workspaceId: p.workspace_id, caseId: p.id, revision: p.revision }).map(s => db.prepare(s.sql).bind(...s.binds)));
    if (!results.at(-1)?.meta.changes) throw new HttpError(409, 'This test changed elsewhere. Reload the library before deleting it.');
    const keys = (results[0].results as { object_key: string }[]).map(row => String(row.object_key));
    if (keys.length) {
        // R2 is not part of the D1 transaction; the rows are already gone, so a failed blob
        // delete only leaves unreferenced objects. Report it without failing the request.
        try { const store = storage || bucket(); for (let i = 0; i < keys.length; i += 1000) await store.delete(keys.slice(i, i + 1000)); }
        catch (error) { console.error('Deleted test case evidence objects could not be removed', { caseId: p.id, count: keys.length }, error); }
    }
    return Response.json({ deleted: true, id: p.id });
}
catch (e) {
    return failure(e);
} }
