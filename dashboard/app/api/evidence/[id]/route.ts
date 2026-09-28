import { context, failure, HttpError, bucket } from '@/lib/server';
export async function GET(request: Request, { params }: {
    params: Promise<{
        id: string;
    }>;
}) { try {
    const { db, owner } = await context(request);
    const { id } = await params;
    const file = await db.prepare('SELECT object_key,name,mime FROM evidence WHERE id=? AND owner=?').bind(id, owner).first();
    if (!file)
        throw new HttpError(404, 'Evidence not found.');
    const obj = await bucket().get(String(file.object_key), { range: request.headers });
    if (!obj)
        throw new HttpError(404, 'Evidence file is unavailable.');
    const headers = new Headers({ 'Content-Type': String(file.mime), 'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff', 'Accept-Ranges': 'bytes' });
    const inline = String(file.mime).startsWith('image/') || String(file.mime).startsWith('video/');
    headers.set('Content-Disposition', `${inline ? 'inline' : 'attachment'}; filename*=UTF-8''${encodeURIComponent(String(file.name))}`);
    let status = 200;
    if (request.headers.has('range') && obj.range && 'offset' in obj.range && obj.range.offset !== undefined) {
        const offset = obj.range.offset, length = obj.range.length ?? (obj.size - offset);
        headers.set('Content-Range', `bytes ${offset}-${offset + length - 1}/${obj.size}`);
        headers.set('Content-Length', String(length));
        status = 206;
    }
    else
        headers.set('Content-Length', String(obj.size));
    return new Response(obj.body, { status, headers });
}
catch (e) {
    return failure(e);
} }
