import { z } from 'zod';
import { context, failure, HttpError, jsonBody } from '@/lib/server';
import { checkpointResult } from '@/lib/contracts';
const input = z.object({ run_id: z.string().uuid(), checkpoint_id: z.string().regex(/^[A-Za-z0-9_-]{1,40}$/), decision: z.enum(['accept', 'dispute']), explanation: z.string().trim().min(1).max(2000) });
export async function GET(request: Request) { try {
    const { db, owner } = await context(request);
    const workspace = new URL(request.url).searchParams.get('workspace');
    if (!workspace) throw new HttpError(400, 'Workspace is required.');
    const found = await db.prepare('SELECT id FROM workspaces WHERE id=? AND owner=?').bind(workspace, owner).first();
    if (!found) throw new HttpError(404, 'Workspace not found.');
    const { results } = await db.prepare('SELECT id,workspace_id,run_id,checkpoint_id,original_verdict,decision,explanation,created FROM checkpoint_reviews WHERE owner=? AND workspace_id=? ORDER BY created DESC').bind(owner, workspace).all();
    return Response.json(results);
} catch (error) { return failure(error); } }
export async function POST(request: Request) { try {
    const { db, owner } = await context(request, true);
    const value = input.parse(await jsonBody(request));
    const run = await db.prepare('SELECT workspace_id,trace_json FROM runs WHERE id=? AND owner=?').bind(value.run_id, owner).first<{workspace_id:string;trace_json:string}>();
    if (!run) throw new HttpError(404, 'Run not found.');
    const trace: unknown = JSON.parse(run.trace_json);
    if (!Array.isArray(trace)) throw new HttpError(409, 'Run trace is unavailable.');
    const report = [...trace].reverse().find(step => step && typeof step === 'object' && Array.isArray(step.checkpoint_results));
    if (!report) throw new HttpError(404, 'This run has no checkpoint report.');
    const original = checkpointResult.array().parse(report?.checkpoint_results).find(item => item.id === value.checkpoint_id);
    if (!original) throw new HttpError(404, 'Checkpoint decision not found in this run.');
    const id = crypto.randomUUID(), created = new Date().toISOString();
    await db.prepare('INSERT INTO checkpoint_reviews (id,owner,workspace_id,run_id,checkpoint_id,original_verdict,decision,explanation,created) VALUES (?,?,?,?,?,?,?,?,?)').bind(id, owner, run.workspace_id, value.run_id, value.checkpoint_id, original.verdict, value.decision, value.explanation, created).run();
    return Response.json({ id, workspace_id: run.workspace_id, run_id: value.run_id, checkpoint_id: value.checkpoint_id, original_verdict: original.verdict, decision: value.decision, explanation: value.explanation, created }, { status: 201 });
} catch (error) { return failure(error); } }
