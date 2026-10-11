// Executes the DELETE /api/runs clear against an in-memory SQLite database built from
// the real migrations. Touches no local D1 state. Run: node checks/run-delete.mjs
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';
import { runClearEvidenceCount, runClearPlan, runClearTables } from '../lib/run-delete.ts';

const owner = 'owner-a', other = 'owner-b', ws = 'ws-1', ws2 = 'ws-2', now = '2026-01-01T00:00:00Z';

function fresh() {
    const migrations = new URL('../drizzle/', import.meta.url);
    const db = new DatabaseSync(':memory:');
    for (const file of readdirSync(migrations).filter(name => name.endsWith('.sql')).sort())
        for (const statement of readFileSync(new URL(file, migrations), 'utf8').split('--> statement-breakpoint'))
            if (statement.trim()) db.exec(statement);
    const insert = (table, row) => db.prepare(`INSERT INTO ${table} (${Object.keys(row).join(',')}) VALUES (${Object.keys(row).map(() => '?').join(',')})`).run(...Object.values(row));
    function seedCase(id, who = owner, workspace = ws, tag = id) { // tag keeps row IDs unique across owners
        if (tag === id) insert('test_cases', { id, owner: who, workspace_id: workspace, title: id, platform: 'Android', suite: 's', goal: 'g', preconditions: '', steps: 'x', expected: 'y', revision: 2, updated: now });
        insert('case_revisions', { owner: who, workspace_id: workspace, case_id: id, revision: 1, snapshot_json: '{}', created: now });
        insert('case_revisions', { owner: who, workspace_id: workspace, case_id: id, revision: 2, snapshot_json: '{}', created: now });
        insert('scenario_matrices', { id: `${tag}-matrix`, owner: who, workspace_id: workspace, case_id: id, name: 'm', revision: 1, definition_json: '{}', updated: now });
        insert('matrix_batches', { id: `${tag}-batch`, owner: who, workspace_id: workspace, matrix_id: `${tag}-matrix`, matrix_revision: 1, matrix_name: 'm', case_id: id, entries_json: '[]', settings_json: '{}', request_signature: 'sig', summary_json: '{}', created: now });
        for (const [run, batch] of [[`${tag}-run`, null], [`${tag}-matrix-run`, `${tag}-batch`]]) {
            insert('runs', { id: run, owner: who, workspace_id: workspace, case_id: id, matrix_batch_id: batch, matrix_variant_id: batch && 'v1', snapshot: '{}', status: 'Passed', build: 'b', device: 'd', notes: '', created: now });
            insert('evidence', { id: `${run}-file`, owner: who, run_id: run, name: 'f.png', mime: 'image/png', size: 1, object_key: `${who}/${run}/file`, created: now });
            insert('checkpoint_reviews', { id: `${run}-review`, owner: who, workspace_id: workspace, run_id: run, checkpoint_id: 'c1', original_verdict: 'Failed', decision: 'accept', explanation: 'e', created: now });
            insert('review_notes', { id: `${run}-note`, owner: who, workspace_id: workspace, target_type: 'run', target_id: run, body: 'b', created: now, updated: now });
        }
        insert('review_notes', { id: `${tag}-note`, owner: who, workspace_id: workspace, target_type: 'case', target_id: id, body: 'b', created: now, updated: now });
        insert('case_authoring_requests', { owner: who, workspace_id: workspace, request_id: `${tag}-request`, payload_hash: 'h', claim: 'c', response_json: JSON.stringify({ case: { id, revision: 1 } }), created: now });
    }
    for (const [who, workspace] of [[owner, ws], [owner, ws2], [other, ws]]) insert('workspaces', { id: `${who}-${workspace}`, owner: who, name: workspace, created: now });
    seedCase('case-a');
    seedCase('case-b');
    seedCase('case-c', owner, ws2); // same owner, another workspace
    seedCase('case-a', other, ws, 'other'); // another owner reusing the case ID and workspace ID
    // Legacy run of case A that never got its workspace_id backfilled.
    insert('runs', { id: 'case-a-legacy-run', owner, workspace_id: '', case_id: 'case-a', snapshot: '{}', status: 'Passed', build: 'b', device: 'd', notes: '', created: now });
    // cmp-ab pairs case A with case B; cmp-b only case B; cmp-c only the other workspace.
    insert('platform_comparisons', { id: 'cmp-ab', owner, workspace_id: ws, android_run_id: 'case-a-run', ios_run_id: 'case-b-run', report_json: '{}', created: now });
    insert('platform_comparisons', { id: 'cmp-b', owner, workspace_id: ws, android_run_id: 'case-b-run', ios_run_id: 'case-b-matrix-run', report_json: '{}', created: now });
    insert('platform_comparisons', { id: 'cmp-c', owner, workspace_id: ws2, android_run_id: 'case-c-run', ios_run_id: 'case-c-matrix-run', report_json: '{}', created: now });
    for (const id of ['cmp-ab', 'cmp-b', 'cmp-c'])
        insert('comparison_reviews', { id: `${id}-review`, owner, comparison_id: id, checkpoint_id: 'c1', conclusion: 'x', explanation: 'e', created: now });
    return db;
}

function clear(db, target) { // Mirrors one D1 batch: a single transaction.
    const count = runClearEvidenceCount(target);
    const expectedFiles = db.prepare(count.sql).get(...count.binds).n;
    db.exec('BEGIN');
    try {
        const results = runClearPlan(target).map(s => s.sql.includes('RETURNING') ? { rows: db.prepare(s.sql).all(...s.binds) } : db.prepare(s.sql).run(...s.binds));
        db.exec('COMMIT');
        assert.equal(results.length, runClearTables.length);
        const keys = results[runClearTables.indexOf('evidence')].rows.map(row => row.object_key).sort();
        assert.equal(keys.length, expectedFiles, 'the pre-check must count exactly the evidence that is removed');
        return { keys, runs: Number(results[runClearTables.indexOf('runs')].changes), batches: Number(results[runClearTables.indexOf('matrix_batches')].changes) };
    } catch (error) { db.exec('ROLLBACK'); throw error; }
}
const ids = (db, table, column = 'id') => db.prepare(`SELECT ${column} AS v FROM ${table} ORDER BY v`).all().map(row => row.v);
const n = (db, sql, ...binds) => db.prepare(sql).get(...binds).n;
// Definitions are never removed by a clear.
function assertDefinitionsKept(db) {
    assert.deepEqual(ids(db, 'test_cases'), ['case-a', 'case-b', 'case-c']);
    assert.equal(n(db, 'SELECT COUNT(*) AS n FROM case_revisions'), 8);
    assert.deepEqual(ids(db, 'scenario_matrices'), ['case-a-matrix', 'case-b-matrix', 'case-c-matrix', 'other-matrix']);
    assert.equal(n(db, 'SELECT COUNT(*) AS n FROM case_authoring_requests'), 4);
    assert.deepEqual(ids(db, 'review_notes').filter(id => !id.includes('run')), ['case-a-note', 'case-b-note', 'case-c-note', 'other-note']);
    assert.equal(n(db, 'SELECT COUNT(*) AS n FROM workspaces'), 3);
}
// Rows of the given owner/tag stay complete.
function assertRunsIntact(db, who, tag) {
    assert.equal(n(db, 'SELECT COUNT(*) AS n FROM runs WHERE owner=? AND id IN (?,?)', who, `${tag}-run`, `${tag}-matrix-run`), 2, `${tag} runs`);
    assert.equal(n(db, 'SELECT COUNT(*) AS n FROM evidence WHERE owner=? AND run_id LIKE ?', who, `${tag}-%`), 2, `${tag} evidence`);
    assert.equal(n(db, 'SELECT COUNT(*) AS n FROM checkpoint_reviews WHERE owner=? AND run_id LIKE ?', who, `${tag}-%`), 2, `${tag} checkpoint reviews`);
    assert.equal(n(db, "SELECT COUNT(*) AS n FROM review_notes WHERE owner=? AND target_type='run' AND target_id LIKE ?", who, `${tag}-%`), 2, `${tag} run notes`);
    assert.equal(n(db, 'SELECT COUNT(*) AS n FROM matrix_batches WHERE owner=? AND id=?', who, `${tag}-batch`), 1, `${tag} batch`);
}
function assertRunsGone(db, tag) {
    const left = db.prepare(`SELECT 'runs' FROM runs WHERE owner=?1 AND id LIKE ?2
      UNION ALL SELECT 'evidence' FROM evidence WHERE owner=?1 AND run_id LIKE ?2
      UNION ALL SELECT 'checkpoint_reviews' FROM checkpoint_reviews WHERE owner=?1 AND run_id LIKE ?2
      UNION ALL SELECT 'review_notes' FROM review_notes WHERE owner=?1 AND target_type='run' AND target_id LIKE ?2
      UNION ALL SELECT 'matrix_batches' FROM matrix_batches WHERE owner=?1 AND id LIKE ?2`).all(owner, `${tag}-%`);
    assert.deepEqual(left, [], `${tag} run history must be gone`);
}

// Per-case clear: case A only (its direct, matrix and legacy runs).
{
    const db = fresh();
    const done = clear(db, { owner, workspaceId: ws, caseId: 'case-a' });
    assert.deepEqual(done.keys, ['owner-a/case-a-matrix-run/file', 'owner-a/case-a-run/file']);
    assert.equal(done.runs, 3);
    assert.equal(done.batches, 1);
    assertRunsGone(db, 'case-a');
    assertDefinitionsKept(db);
    assertRunsIntact(db, owner, 'case-b');
    assertRunsIntact(db, owner, 'case-c');
    assertRunsIntact(db, other, 'other');
    assert.deepEqual(ids(db, 'platform_comparisons'), ['cmp-b', 'cmp-c']);
    assert.deepEqual(ids(db, 'comparison_reviews'), ['cmp-b-review', 'cmp-c-review']);
    // Clearing again is a no-op.
    assert.deepEqual(clear(db, { owner, workspaceId: ws, caseId: 'case-a' }), { keys: [], runs: 0, batches: 0 });
}

// Workspace-wide clear: cases A and B in ws-1; ws-2 and the other owner untouched.
{
    const db = fresh();
    const done = clear(db, { owner, workspaceId: ws });
    assert.deepEqual(done.keys, ['owner-a/case-a-matrix-run/file', 'owner-a/case-a-run/file', 'owner-a/case-b-matrix-run/file', 'owner-a/case-b-run/file']);
    assert.equal(done.runs, 5);
    assert.equal(done.batches, 2);
    assertRunsGone(db, 'case-a');
    assertRunsGone(db, 'case-b');
    assertDefinitionsKept(db);
    assertRunsIntact(db, owner, 'case-c');
    assertRunsIntact(db, other, 'other');
    assert.deepEqual(ids(db, 'platform_comparisons'), ['cmp-c']);
    assert.deepEqual(ids(db, 'comparison_reviews'), ['cmp-c-review']);
    assert.deepEqual(clear(db, { owner, workspaceId: ws, caseId: null }), { keys: [], runs: 0, batches: 0 });
}

// A workspace the owner does not have selects nothing (the route answers 404 before this).
{
    const db = fresh();
    assert.deepEqual(clear(db, { owner: 'nobody', workspaceId: ws }), { keys: [], runs: 0, batches: 0 });
    assert.equal(n(db, 'SELECT COUNT(*) AS n FROM runs'), 9);
}
console.log('PASS: run history clear (per-case and workspace-wide; matrix/legacy runs, evidence keys, run notes, checkpoint reviews, comparisons, batches removed; cases, revisions, matrices, case notes, authoring records, other workspace and other owner kept).');
