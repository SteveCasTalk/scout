// Statements that permanently remove a saved test case and every row that only
// exists because of it. Kept free of runtime imports so checks/case-delete.mjs
// can execute the exact SQL against an in-memory SQLite copy of the migrations.
//
// Every statement is guarded by the expected case revision, and the case row is
// deleted last. D1 runs a batch as one transaction, so a concurrent edit either
// lands before the batch (nothing is deleted; the final statement reports zero
// changes and the route answers 409) or after it (the case is already gone).
export type DeletionStatement = { sql: string; binds: unknown[] };
export type CaseDeletionTarget = { owner: string; workspaceId: string; caseId: string; revision: number };

export const caseDeletionTables = [
    'evidence', 'checkpoint_reviews', 'review_notes', 'comparison_reviews', 'platform_comparisons',
    'runs', 'matrix_batches', 'scenario_matrices', 'case_revisions', 'case_authoring_requests', 'test_cases',
] as const;

export function caseDeletionPlan({ owner, workspaceId, caseId, revision }: CaseDeletionTarget): DeletionStatement[] {
    const guard = 'EXISTS (SELECT 1 FROM test_cases WHERE id=? AND owner=? AND workspace_id=? AND revision=?)';
    const guardBinds = [caseId, owner, workspaceId, revision];
    // Runs saved against the case, including scenario-matrix runs of its batches.
    // Case IDs are owner-scoped random UUIDs, so legacy runs without a workspace ID are included.
    const batchIds = 'SELECT id FROM matrix_batches WHERE owner=? AND (case_id=? OR matrix_id IN (SELECT id FROM scenario_matrices WHERE owner=? AND case_id=?))';
    const batchBinds = [owner, caseId, owner, caseId];
    const runIds = `SELECT id FROM runs WHERE owner=? AND (case_id=? OR matrix_batch_id IN (${batchIds}))`;
    const runBinds = [owner, caseId, ...batchBinds];
    const comparisonIds = `SELECT id FROM platform_comparisons WHERE owner=? AND (android_run_id IN (${runIds}) OR ios_run_id IN (${runIds}))`;
    const comparisonBinds = [owner, ...runBinds, ...runBinds];
    return [
        // RETURNING lists the R2 object keys of exactly the evidence rows removed.
        { sql: `DELETE FROM evidence WHERE owner=? AND run_id IN (${runIds}) AND ${guard} RETURNING object_key`, binds: [owner, ...runBinds, ...guardBinds] },
        { sql: `DELETE FROM checkpoint_reviews WHERE owner=? AND run_id IN (${runIds}) AND ${guard}`, binds: [owner, ...runBinds, ...guardBinds] },
        { sql: `DELETE FROM review_notes WHERE owner=? AND ((target_type='case' AND target_id=?) OR (target_type='run' AND target_id IN (${runIds}))) AND ${guard}`, binds: [owner, caseId, ...runBinds, ...guardBinds] },
        // A comparison pairs an Android and an iOS run; it cannot stand once either run is gone.
        { sql: `DELETE FROM comparison_reviews WHERE owner=? AND comparison_id IN (${comparisonIds}) AND ${guard}`, binds: [owner, ...comparisonBinds, ...guardBinds] },
        { sql: `DELETE FROM platform_comparisons WHERE id IN (${comparisonIds}) AND ${guard}`, binds: [...comparisonBinds, ...guardBinds] },
        { sql: `DELETE FROM runs WHERE id IN (${runIds}) AND ${guard}`, binds: [...runBinds, ...guardBinds] },
        { sql: `DELETE FROM matrix_batches WHERE id IN (${batchIds}) AND ${guard}`, binds: [...batchBinds, ...guardBinds] },
        { sql: `DELETE FROM scenario_matrices WHERE owner=? AND case_id=? AND ${guard}`, binds: [owner, caseId, ...guardBinds] },
        { sql: `DELETE FROM case_revisions WHERE owner=? AND case_id=? AND ${guard}`, binds: [owner, caseId, ...guardBinds] },
        // Idempotency records whose saved response is this case. CASE keeps json_extract
        // away from malformed rows so one bad record cannot abort the whole batch.
        { sql: `DELETE FROM case_authoring_requests WHERE owner=? AND workspace_id=? AND (CASE WHEN json_valid(response_json) THEN json_extract(response_json,'$.case.id') END)=? AND ${guard}`, binds: [owner, workspaceId, caseId, ...guardBinds] },
        { sql: 'DELETE FROM test_cases WHERE id=? AND owner=? AND workspace_id=? AND revision=?', binds: guardBinds },
    ];
}
