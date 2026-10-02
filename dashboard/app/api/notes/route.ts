import { z } from 'zod';
import { context, failure, HttpError, jsonBody } from '@/lib/server';
const bodyInput = z.object({ body: z.string().trim().min(1).max(4000) });
const createInput = bodyInput.extend({ target_type: z.enum(['case', 'run']), target_id: z.string().uuid() });
const editInput = bodyInput.extend({ id: z.string().uuid() });
const deleteInput = z.object({ id: z.string().uuid() });
export async function GET(request: Request) { try {
    const { db, owner } = await context(request);
    const workspace = new URL(request.url).searchParams.get('workspace');
    if (!workspace) throw new HttpError(400, 'Workspace is required.');
    const found = await db.prepare('SELECT id FROM workspaces WHERE id=? AND owner=?').bind(workspace, owner).first();
    if (!found) throw new HttpError(404, 'Workspace not found.');
    const { results } = await db.prepare('SELECT id,workspace_id,target_type,target_id,body,created,updated FROM review_notes WHERE owner=? AND workspace_id=? ORDER BY created DESC').bind(owner, workspace).all();
    return Response.json(results);
} catch (error) { return failure(error); } }
export async function POST(request: Request) { try {
    const { db, owner } = await context(request, true);
    const value = createInput.parse(await jsonBody(request));
    const table = value.target_type === 'case' ? 'test_cases' : 'runs';
    const target = await db.prepare(`SELECT workspace_id FROM ${table} WHERE id=? AND owner=?`).bind(value.target_id, owner).first<{workspace_id:string}>();
    if (!target) throw new HttpError(404, 'Case or run not found.');
    const id = crypto.randomUUID(), now = new Date().toISOString();
    await db.prepare('INSERT INTO review_notes (id,owner,workspace_id,target_type,target_id,body,created,updated) VALUES (?,?,?,?,?,?,?,?)').bind(id, owner, target.workspace_id, value.target_type, value.target_id, value.body, now, now).run();
    return Response.json({ id, workspace_id: target.workspace_id, target_type: value.target_type, target_id: value.target_id, body: value.body, created: now, updated: now }, { status: 201 });
} catch (error) { return failure(error); } }
export async function PUT(request: Request) { try {
    const { db, owner } = await context(request, true);
    const value = editInput.parse(await jsonBody(request));
    const now = new Date().toISOString();
    const changed = await db.prepare('UPDATE review_notes SET body=?,updated=? WHERE id=? AND owner=?').bind(value.body, now, value.id, owner).run();
    if (!changed.meta.changes) throw new HttpError(404, 'Note not found.');
    return Response.json({ id: value.id, body: value.body, updated: now });
} catch (error) { return failure(error); } }
export async function DELETE(request: Request) { try {
    const { db, owner } = await context(request, true);
    const value = deleteInput.parse(await jsonBody(request));
    const changed = await db.prepare('DELETE FROM review_notes WHERE id=? AND owner=?').bind(value.id, owner).run();
    if (!changed.meta.changes) throw new HttpError(404, 'Note not found.');
    return Response.json({ deleted: true });
} catch (error) { return failure(error); } }
