import { context, failure, jsonBody, HttpError } from '@/lib/server';
import { caseInput } from '@/lib/contracts';
import { z } from 'zod';
export async function GET(request: Request) { try {
    const { db, owner } = await context(request);
    const rows = await db.prepare('SELECT id,title,platform,suite,goal,preconditions,steps,expected,assertion_text,revision,updated FROM test_cases WHERE owner=? ORDER BY updated DESC').bind(owner).all();
    return Response.json(rows.results);
}
catch (e) {
    return failure(e);
} }
export async function POST(request: Request) { try {
    const { db, owner } = await context(request, true);
    const c = caseInput.parse(await jsonBody(request));
    const id = crypto.randomUUID(), updated = new Date().toISOString();
    await db.prepare('INSERT INTO test_cases (id,owner,title,platform,suite,goal,preconditions,steps,expected,assertion_text,revision,updated) VALUES (?,?,?,?,?,?,?,?,?,?,1,?)').bind(id, owner, c.title, c.platform, c.suite, c.goal, c.preconditions, c.steps, c.expected, c.assertion_text, updated).run();
    return Response.json({ ...c, id, revision: 1, updated }, { status: 201 });
}
catch (e) {
    return failure(e);
} }
export async function PUT(request: Request) { try {
    const { db, owner } = await context(request, true);
    const c = caseInput.extend({ id: z.string().uuid(), revision: z.number().int().positive() }).parse(await jsonBody(request));
    const updated = new Date().toISOString();
    const result = await db.prepare('UPDATE test_cases SET title=?,platform=?,suite=?,goal=?,preconditions=?,steps=?,expected=?,assertion_text=?,revision=revision+1,updated=? WHERE id=? AND owner=? AND revision=?').bind(c.title, c.platform, c.suite, c.goal, c.preconditions, c.steps, c.expected, c.assertion_text, updated, c.id, owner, c.revision).run();
    if (!result.meta.changes)
        throw new HttpError(409, 'This test changed elsewhere. Reload the library before editing again.');
    return Response.json({ ...c, revision: c.revision + 1, updated });
}
catch (e) {
    return failure(e);
} }
