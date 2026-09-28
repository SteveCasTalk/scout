import { context, failure, HttpError, bucket } from '@/lib/server';
const allowed = new Set(['image/png', 'image/jpeg', 'image/webp', 'video/mp4', 'video/webm', 'text/plain', 'application/json']);
export async function GET(request: Request) { try {
    const { db, owner } = await context(request);
    const { results } = await db.prepare('SELECT id,run_id,name,mime,size,created FROM evidence WHERE owner=? ORDER BY created DESC').bind(owner).all();
    return Response.json(results);
}
catch (e) {
    return failure(e);
} }
export async function POST(request: Request) { try {
    const { db, owner } = await context(request, true);
    const storage = bucket();
    if (Number(request.headers.get('content-length') || 0) > 26 * 1024 * 1024)
        throw new HttpError(413, 'Files must be 25 MB or smaller.');
    const form = await request.formData();
    const file = form.get('file'), runId = form.get('runId');
    if (!(file instanceof File) || typeof runId !== 'string')
        throw new HttpError(400, 'Choose a file and run.');
    if (!allowed.has(file.type))
        throw new HttpError(400, 'Use PNG, JPEG, WebP, MP4, WebM, TXT, or JSON.');
    if (!file.size || file.size > 25 * 1024 * 1024)
        throw new HttpError(413, 'Files must be nonempty and 25 MB or smaller.');
    const run = await db.prepare('SELECT id FROM runs WHERE id=? AND owner=?').bind(runId, owner).first();
    if (!run)
        throw new HttpError(404, 'Run not found.');
    const id = crypto.randomUUID(), key = `${owner}/${runId}/${id}`, created = new Date().toISOString();
    await storage.put(key, file.stream(), { httpMetadata: { contentType: file.type } });
    try {
        await db.prepare('INSERT INTO evidence (id,owner,run_id,name,mime,size,object_key,created) VALUES (?,?,?,?,?,?,?,?)').bind(id, owner, runId, file.name.slice(0, 240), file.type, file.size, key, created).run();
    }
    catch (e) {
        await storage.delete(key);
        throw e;
    }
    return Response.json({ id, run_id: runId, name: file.name.slice(0, 240), mime: file.type, size: file.size, created }, { status: 201 });
}
catch (e) {
    return failure(e);
} }
