import { context, failure, jsonBody, HttpError } from '@/lib/server';
import { runInput, startingConditionsInput } from '@/lib/contracts';
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
