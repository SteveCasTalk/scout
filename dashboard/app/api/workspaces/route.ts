import { context, failure, jsonBody, HttpError } from '@/lib/server';
import { z } from 'zod';

export async function GET(request: Request) {
  try {
    const { db, owner } = await context(request);
    const { results } = await db.prepare('SELECT id,name,created FROM workspaces WHERE owner=? ORDER BY name COLLATE NOCASE').bind(owner).all();
    return Response.json(results);
  } catch (error) { return failure(error); }
}

export async function POST(request: Request) {
  try {
    const { db, owner } = await context(request, true);
    const { name } = z.object({ name: z.string().trim().min(1).max(100) }).parse(await jsonBody(request));
    const existing = await db.prepare('SELECT id FROM workspaces WHERE owner=? AND name=? COLLATE NOCASE').bind(owner, name).first<{ id: string }>();
    if (existing) throw new HttpError(409, 'A workspace with this name already exists.');
    const id = crypto.randomUUID(), created = new Date().toISOString();
    await db.prepare('INSERT INTO workspaces (id,owner,name,created) VALUES (?,?,?,?)').bind(id, owner, name, created).run();
    return Response.json({ id, name, created }, { status: 201 });
  } catch (error) { return failure(error); }
}
