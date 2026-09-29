import { context, failure, jsonBody, HttpError } from '@/lib/server';
import { runInput } from '@/lib/contracts';
export async function GET(request: Request) { try {
    const { db, owner } = await context(request);
    const { results } = await db.prepare('SELECT id,workspace_id,case_id,external_run_id,snapshot,status,build,device,notes,source,trace_json,created FROM runs WHERE owner=? ORDER BY created DESC').bind(owner).all();
    return Response.json(results.map(r => ({ ...r, snapshot: JSON.parse(String(r.snapshot)), trace: JSON.parse(String(r.trace_json)) })));
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
    const c = await db.prepare('SELECT id,workspace_id,project,app_id,title,platform,suite,goal,preconditions,steps,expected,assertion_text,revision,updated FROM test_cases WHERE id=? AND owner=?').bind(r.caseId, owner).first<{workspace_id:string; revision:number}>();
    if (!c)
        throw new HttpError(404, 'Test case not found.');
    if (c.revision !== r.revision)
        throw new HttpError(409, 'The test changed. Reload it before recording this run.');
    if (JSON.stringify(r.trace).length > 200000) throw new HttpError(413, 'Runner trace is too large.');
    const id = crypto.randomUUID(), created = new Date().toISOString();
    await db.prepare('INSERT INTO runs (id,owner,workspace_id,case_id,external_run_id,snapshot,status,build,device,notes,source,trace_json,created) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)').bind(id, owner, c.workspace_id, r.caseId, r.externalRunId || null, JSON.stringify(c), r.status, r.build, r.device, r.notes, r.source, JSON.stringify(r.trace), created).run();
    return Response.json({ ...r, id, workspace_id: c.workspace_id, case_id: r.caseId, snapshot: c, created }, { status: 201 });
}
catch (e) {
    return failure(e);
} }
