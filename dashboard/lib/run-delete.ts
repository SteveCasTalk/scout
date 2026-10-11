// Statements that permanently clear run history while keeping the test cases, their
// revisions, scenario matrices and authoring records. Kept free of runtime imports so
// checks/run-delete.mjs can execute the exact SQL against an in-memory SQLite copy of
// the migrations.
//
// Statement order matters: every run-ID subquery reads runs and matrix_batches, so the
// dependent rows go first, then the runs, then the batches. D1 runs a batch as one
// transaction, so later statements see the earlier deletions consistently.
import type { DeletionStatement } from './case-delete';

export type RunClearTarget = { owner: string; workspaceId: string; caseId?: string | null };

// One statement per table, in execution order; the route reads results by this index.
export const runClearTables = [
    'evidence', 'checkpoint_reviews', 'review_notes', 'comparison_reviews', 'platform_comparisons', 'runs', 'matrix_batches',
] as const;

function selection({ owner, workspaceId, caseId }: RunClearTarget) {
    if (caseId) {
        // Same selection as DELETE /api/cases: runs saved against the case, including
        // scenario-matrix runs of its batches. Case IDs are owner-scoped random UUIDs.
        const batchIds = 'SELECT id FROM matrix_batches WHERE owner=? AND (case_id=? OR matrix_id IN (SELECT id FROM scenario_matrices WHERE owner=? AND case_id=?))';
        const batchBinds = [owner, caseId, owner, caseId];
        return {
            batchIds, batchBinds,
            runIds: `SELECT id FROM runs WHERE owner=? AND (case_id=? OR matrix_batch_id IN (${batchIds}))`,
            runBinds: [owner, caseId, ...batchBinds],
        };
    }
    // Whole workspace: anything stamped with the workspace, or attached to one of its cases
    // or matrices (covers legacy rows whose workspace_id was never backfilled).
    const caseIds = 'SELECT id FROM test_cases WHERE owner=? AND workspace_id=?';
    const caseBinds = [owner, workspaceId];
    const matrixIds = `SELECT id FROM scenario_matrices WHERE owner=? AND (workspace_id=? OR case_id IN (${caseIds}))`;
    const matrixBinds = [owner, workspaceId, ...caseBinds];
    const batchIds = `SELECT id FROM matrix_batches WHERE owner=? AND (workspace_id=? OR case_id IN (${caseIds}) OR matrix_id IN (${matrixIds}))`;
    const batchBinds = [owner, workspaceId, ...caseBinds, ...matrixBinds];
    return {
        batchIds, batchBinds,
        runIds: `SELECT id FROM runs WHERE owner=? AND (workspace_id=? OR case_id IN (${caseIds}) OR matrix_batch_id IN (${batchIds}))`,
        runBinds: [owner, workspaceId, ...caseBinds, ...batchBinds],
    };
}

// Counts the evidence rows the plan would remove, so the route can refuse before touching
// D1 when blobs exist but storage is unbound.
export function runClearEvidenceCount(target: RunClearTarget): DeletionStatement {
    const { runIds, runBinds } = selection(target);
    return { sql: `SELECT COUNT(*) AS n FROM evidence WHERE owner=? AND run_id IN (${runIds})`, binds: [target.owner, ...runBinds] };
}

export function runClearPlan(target: RunClearTarget): DeletionStatement[] {
    const { owner } = target;
    const { runIds, runBinds, batchIds, batchBinds } = selection(target);
    const comparisonIds = `SELECT id FROM platform_comparisons WHERE owner=? AND (android_run_id IN (${runIds}) OR ios_run_id IN (${runIds}))`;
    const comparisonBinds = [owner, ...runBinds, ...runBinds];
    return [
        // RETURNING lists the R2 object keys of exactly the evidence rows removed.
        { sql: `DELETE FROM evidence WHERE owner=? AND run_id IN (${runIds}) RETURNING object_key`, binds: [owner, ...runBinds] },
        { sql: `DELETE FROM checkpoint_reviews WHERE owner=? AND run_id IN (${runIds})`, binds: [owner, ...runBinds] },
        // Only notes on the runs; case-level notes belong to the case and are kept.
        { sql: `DELETE FROM review_notes WHERE owner=? AND target_type='run' AND target_id IN (${runIds})`, binds: [owner, ...runBinds] },
        // A comparison pairs an Android and an iOS run; it cannot stand once either run is gone.
        { sql: `DELETE FROM comparison_reviews WHERE owner=? AND comparison_id IN (${comparisonIds})`, binds: [owner, ...comparisonBinds] },
        { sql: `DELETE FROM platform_comparisons WHERE id IN (${comparisonIds})`, binds: comparisonBinds },
        { sql: `DELETE FROM runs WHERE id IN (${runIds})`, binds: runBinds },
        // Matrix batches are run history; the matrices that define them are kept.
        { sql: `DELETE FROM matrix_batches WHERE id IN (${batchIds})`, binds: batchBinds },
    ];
}
