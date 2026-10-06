import { env } from 'cloudflare:workers';
import { getChatGPTUser } from '@/app/chatgpt-auth';
import { ZodError } from 'zod';
import { HttpError } from './errors';
export { HttpError } from './errors';
export async function context(request: Request, write = false) {
    if (write && request.headers.get('origin') && request.headers.get('origin') !== new URL(request.url).origin)
        throw new HttpError(403, 'Cross-origin requests are not allowed.');
    const user = await getChatGPTUser();
    if (!user)
        throw new HttpError(401, 'Sign in to save and view your workspace.');
    if (!env.DB)
        throw new HttpError(503, 'The workspace database is unavailable. Please try again.');
    return { db: env.DB, owner: user.userId };
}
export async function jsonBody(request: Request) { try {
    return await request.json();
}
catch {
    throw new HttpError(400, 'Invalid JSON.');
} }
export function failure(error: unknown) {
    if (error instanceof HttpError)
        return Response.json({ error: error.message }, { status: error.status });
    if (error instanceof ZodError)
        return Response.json({ error: error.issues.map(x => `${x.path.join('.')}: ${x.message}`).join('; ') }, { status: 400 });
    console.error('Workspace request failed', error);
    return Response.json({ error: 'Could not access the workspace. Your changes have not been confirmed. Please try again.' }, { status: 503 });
}
export function bucket() { if (!env.BUCKET)
    throw new HttpError(503, 'Evidence storage is unavailable.'); return env.BUCKET; }
