import { z } from 'zod';
import { context, failure, HttpError, jsonBody } from '@/lib/server';
import { comparePlatforms, comparisonPacket, assessmentInput, conclusions } from '@/lib/platform-comparison';
import type { Run, TestCase } from '@/lib/contracts';
const pairInput = z.object({ workspace_id: z.string().uuid().optional(), android_run_id: z.string().uuid(), ios_run_id: z.string().uuid(), expected_differences: z.string().trim().max(2000).default(''), assessments: z.array(assessmentInput).max(24).default([]), model: z.string().trim().min(1).max(100).optional(), action: z.enum(['prepare','preview','save']).default('save') });
export async function GET(request: Request) { try {
    const { db, owner } = await context(request);
    const workspace = new URL(request.url).searchParams.get('workspace');
    if (!workspace) throw new HttpError(400, 'Workspace is required.');
    const reports = await db.prepare('SELECT id,android_run_id,ios_run_id,report_json,created FROM platform_comparisons WHERE owner=? AND workspace_id=? ORDER BY created DESC').bind(owner, workspace).all();
    const reviews = await db.prepare('SELECT id,comparison_id,checkpoint_id,conclusion,explanation,created FROM comparison_reviews WHERE owner=? AND comparison_id IN (SELECT id FROM platform_comparisons WHERE owner=? AND workspace_id=?) ORDER BY created DESC').bind(owner, owner, workspace).all();
    return Response.json({ reports: reports.results.map(({report_json,...row}) => ({...row, report: JSON.parse(String(report_json))})), reviews: reviews.results });
} catch(error) { return failure(error); } }
export async function POST(request: Request) { try {
    const { db, owner } = await context(request, true);
    const value = pairInput.parse(await jsonBody(request));
    async function read(id: string): Promise<Run> {
        const row = await db.prepare('SELECT * FROM runs WHERE id=? AND owner=?').bind(id, owner).first();
        if (!row) throw new HttpError(404, 'Run not found.');
        return { ...row, snapshot: JSON.parse(String(row.snapshot)), trace: JSON.parse(String(row.trace_json)) } as unknown as Run;
    }
    const android = await read(value.android_run_id), ios = await read(value.ios_run_id);
    if (value.workspace_id && (android.workspace_id !== value.workspace_id || ios.workspace_id !== value.workspace_id)) throw new HttpError(404, 'Runs not found in this workspace.');
    if (android.workspace_id !== ios.workspace_id || android.snapshot.project !== ios.snapshot.project || android.snapshot.platform !== 'Android' || ios.snapshot.platform !== 'iOS') throw new HttpError(400, 'Choose Android and iOS runs from the same workspace and project.');
    async function key(run: Run) { const current = await db.prepare('SELECT comparison_key FROM test_cases WHERE id=? AND owner=?').bind(run.case_id, owner).first<Pick<TestCase,'comparison_key'>>(); return run.snapshot.comparison_key || current?.comparison_key || ''; }
    const aKey = await key(android), bKey = await key(ios);
    if (!aKey || aKey !== bKey) throw new HttpError(400, 'Link the case definitions with the same cross-platform scenario key first.');
    const baseline = comparePlatforms(android, ios, value.expected_differences);
    if (value.action === 'prepare') return Response.json({ report: baseline, packet: comparisonPacket(android, ios, baseline) });
    if (value.assessments.length && (!value.model || new Set(value.assessments.map(item => item.checkpoint_id)).size !== value.assessments.length || value.assessments.some(item => !baseline.rows.some(row => row.checkpoint_id === item.checkpoint_id && row.eligible)))) throw new HttpError(400, 'Invalid assessment checkpoint IDs or model.');
    const report = comparePlatforms(android, ios, value.expected_differences, value.assessments, value.assessments.length ? value.model : undefined);
    if (value.action === 'preview') return Response.json({ android_run_id: android.id, ios_run_id: ios.id, report, saved: false });
    const id = crypto.randomUUID(), created = new Date().toISOString();
    await db.prepare('INSERT INTO platform_comparisons (id,owner,workspace_id,android_run_id,ios_run_id,report_json,created) VALUES (?,?,?,?,?,?,?)').bind(id, owner, android.workspace_id, android.id, ios.id, JSON.stringify(report), created).run();
    return Response.json({ id, android_run_id: android.id, ios_run_id: ios.id, created, report }, { status:201 });
} catch(error) { return failure(error); } }
export async function PUT(request: Request) { try {
    const { db, owner } = await context(request, true);
    const value = z.object({ comparison_id: z.string().uuid(), checkpoint_id: z.string().max(40), conclusion: z.enum(conclusions), explanation: z.string().trim().min(1).max(2000) }).parse(await jsonBody(request));
    const saved = await db.prepare('SELECT report_json FROM platform_comparisons WHERE id=? AND owner=?').bind(value.comparison_id, owner).first<{report_json:string}>();
    if (!saved) throw new HttpError(404, 'Comparison not found.');
    if (!JSON.parse(saved.report_json).rows.some((row: {checkpoint_id:string}) => row.checkpoint_id === value.checkpoint_id)) throw new HttpError(400, 'Checkpoint not found in this comparison.');
    const id = crypto.randomUUID(), created = new Date().toISOString();
    await db.prepare('INSERT INTO comparison_reviews (id,owner,comparison_id,checkpoint_id,conclusion,explanation,created) VALUES (?,?,?,?,?,?,?)').bind(id, owner, value.comparison_id, value.checkpoint_id, value.conclusion, value.explanation, created).run();
    return Response.json({ ...value, id, created }, {status:201});
} catch(error) { return failure(error); } }
