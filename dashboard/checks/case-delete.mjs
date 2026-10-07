// Executes the DELETE /api/cases cascade against an in-memory SQLite database built
// from the real migrations. Touches no local D1 state. Run: node checks/case-delete.mjs
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';
import { caseDeletionPlan, caseDeletionTables } from '../lib/case-delete.ts';

const migrations = new URL('../drizzle/', import.meta.url);
const db = new DatabaseSync(':memory:');
for (const file of readdirSync(migrations).filter(name => name.endsWith('.sql')).sort())
    for (const statement of readFileSync(new URL(file, migrations), 'utf8').split('--> statement-breakpoint'))
        if (statement.trim()) db.exec(statement);

const owner = 'owner-a', other = 'owner-b', ws = 'ws-1', now = '2026-01-01T00:00:00Z';
const insert = (table, row) => db.prepare(`INSERT INTO ${table} (${Object.keys(row).join(',')}) VALUES (${Object.keys(row).map(() => '?').join(',')})`).run(...Object.values(row));
function seedCase(id, who = owner, tag = id) { // tag keeps row IDs unique across owners
    if (tag === id) insert('test_cases', { id, owner: who, workspace_id: ws, title: id, platform: 'Android', suite: 's', goal: 'g', preconditions: '', steps: 'x', expected: 'y', revision: 2, updated: now });
    insert('case_revisions', { owner: who, workspace_id: ws, case_id: id, revision: 1, snapshot_json: '{}', created: now });
    insert('case_revisions', { owner: who, workspace_id: ws, case_id: id, revision: 2, snapshot_json: '{}', created: now });
    insert('scenario_matrices', { id: `${tag}-matrix`, owner: who, workspace_id: ws, case_id: id, name: 'm', revision: 1, definition_json: '{}', updated: now });
    insert('matrix_batches', { id: `${tag}-batch`, owner: who, workspace_id: ws, matrix_id: `${tag}-matrix`, matrix_revision: 1, matrix_name: 'm', case_id: id, entries_json: '[]', settings_json: '{}', request_signature: 'sig', summary_json: '{}', created: now });
    for (const [run, batch] of [[`${tag}-run`, null], [`${tag}-matrix-run`, `${tag}-batch`]]) {
        insert('runs', { id: run, owner: who, workspace_id: ws, case_id: id, matrix_batch_id: batch, matrix_variant_id: batch && 'v1', snapshot: '{}', status: 'Passed', build: 'b', device: 'd', notes: '', created: now });
        insert('evidence', { id: `${run}-file`, owner: who, run_id: run, name: 'f.png', mime: 'image/png', size: 1, object_key: `${who}/${run}/file`, created: now });
        insert('checkpoint_reviews', { id: `${run}-review`, owner: who, workspace_id: ws, run_id: run, checkpoint_id: 'c1', original_verdict: 'Failed', decision: 'accept', explanation: 'e', created: now });
        insert('review_notes', { id: `${run}-note`, owner: who, workspace_id: ws, target_type: 'run', target_id: run, body: 'b', created: now, updated: now });
    }
    insert('review_notes', { id: `${tag}-note`, owner: who, workspace_id: ws, target_type: 'case', target_id: id, body: 'b', created: now, updated: now });
    insert('case_authoring_requests', { owner: who, workspace_id: ws, request_id: `${tag}-request`, payload_hash: 'h', claim: 'c', response_json: JSON.stringify({ case: { id, revision: 1 } }), created: now });
}
seedCase('case-a');
seedCase('case-b');
// Another owner's rows that reference the same case ID must survive.
seedCase('case-a', other, 'other');
// Malformed and unrelated authoring records must not abort or be swept by the batch.
insert('case_authoring_requests', { owner, workspace_id: ws, request_id: 'broken', payload_hash: 'h', claim: 'c', response_json: 'not json', created: now });
insert('case_authoring_requests', { owner, workspace_id: ws, request_id: 'error', payload_hash: 'h', claim: 'c', response_json: '{"error":"x","status":409}', created: now });
// One comparison involves case A; the other only case B.
insert('platform_comparisons', { id: 'cmp-a', owner, workspace_id: ws, android_run_id: 'case-a-run', ios_run_id: 'case-b-run', report_json: '{}', created: now });
insert('platform_comparisons', { id: 'cmp-b', owner, workspace_id: ws, android_run_id: 'case-b-run', ios_run_id: 'case-b-matrix-run', report_json: '{}', created: now });
insert('comparison_reviews', { id: 'cmp-a-review', owner, comparison_id: 'cmp-a', checkpoint_id: 'c1', conclusion: 'x', explanation: 'e', created: now });
insert('comparison_reviews', { id: 'cmp-b-review', owner, comparison_id: 'cmp-b', checkpoint_id: 'c1', conclusion: 'x', explanation: 'e', created: now });

const count = () => Object.fromEntries(caseDeletionTables.map(table => [table, db.prepare(`SELECT COUNT(*) AS n FROM ${table}`).get().n]));
function run(revision) { // Mirrors one D1 batch: a single transaction.
    db.exec('BEGIN');
    try {
        const results = caseDeletionPlan({ owner, workspaceId: ws, caseId: 'case-a', revision }).map(s => s.sql.includes('RETURNING') ? { rows: db.prepare(s.sql).all(...s.binds) } : db.prepare(s.sql).run(...s.binds));
        db.exec('COMMIT');
        return results;
    } catch (error) { db.exec('ROLLBACK'); throw error; }
}

const before = count();
const stale = run(1);
assert.equal(stale.at(-1).changes, 0, 'stale revision must not delete the case');
assert.deepEqual(stale[0].rows, [], 'stale revision must not return evidence keys');
assert.deepEqual(count(), before, 'stale revision must delete nothing');

const done = run(2);
assert.equal(done.at(-1).changes, 1);
assert.deepEqual(done[0].rows.map(row => row.object_key).sort(), ['owner-a/case-a-matrix-run/file', 'owner-a/case-a-run/file']);
const ids = (table, column = 'id') => db.prepare(`SELECT ${column} AS v FROM ${table}`).all().map(row => row.v);
const leftover = db.prepare(`SELECT 'test_cases' FROM test_cases WHERE owner=? AND id='case-a'
  UNION ALL SELECT 'case_revisions' FROM case_revisions WHERE owner=? AND case_id='case-a'
  UNION ALL SELECT 'runs' FROM runs WHERE owner=? AND case_id='case-a'
  UNION ALL SELECT 'evidence' FROM evidence WHERE owner=? AND run_id LIKE 'case-a-%'
  UNION ALL SELECT 'checkpoint_reviews' FROM checkpoint_reviews WHERE owner=? AND run_id LIKE 'case-a-%'
  UNION ALL SELECT 'review_notes' FROM review_notes WHERE owner=? AND target_id LIKE 'case-a%'
  UNION ALL SELECT 'scenario_matrices' FROM scenario_matrices WHERE owner=? AND case_id='case-a'
  UNION ALL SELECT 'matrix_batches' FROM matrix_batches WHERE owner=? AND case_id='case-a'
  UNION ALL SELECT 'case_authoring_requests' FROM case_authoring_requests WHERE owner=? AND request_id='case-a-request'`).all(...Array(9).fill(owner));
assert.deepEqual(leftover, [], 'case A rows must be gone');
assert.deepEqual(ids('platform_comparisons'), ['cmp-b']);
assert.deepEqual(ids('comparison_reviews'), ['cmp-b-review']);
// Case B and the other owner's same-ID case stay intact.
for (const [who, id, tag] of [[owner, 'case-b', 'case-b'], [other, 'case-a', 'other']]) {
    assert.equal(db.prepare('SELECT COUNT(*) AS n FROM runs WHERE owner=? AND case_id=?').get(who, id).n, 2);
    assert.equal(db.prepare('SELECT COUNT(*) AS n FROM evidence WHERE owner=? AND run_id LIKE ?').get(who, `${tag}-%`).n, 2);
    assert.equal(db.prepare('SELECT COUNT(*) AS n FROM review_notes WHERE owner=? AND (target_id=? OR target_id LIKE ?)').get(who, id, `${tag}-%`).n, 3);
    assert.equal(db.prepare('SELECT COUNT(*) AS n FROM case_revisions WHERE owner=? AND case_id=?').get(who, id).n, 2);
    assert.equal(db.prepare('SELECT COUNT(*) AS n FROM matrix_batches WHERE owner=? AND case_id=?').get(who, id).n, 1);
}
assert.deepEqual(ids('case_authoring_requests', 'request_id').sort(), ['broken', 'case-b-request', 'error', 'other-request']);
console.log('PASS: case delete cascade (stale revision no-op, owner scoping, runs/evidence/notes/reviews/comparisons/matrices/batches/revisions/authoring records).');
