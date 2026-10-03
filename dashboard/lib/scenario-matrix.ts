import { z } from 'zod';
import { checkpointsInput, type TestCase } from './contracts';
import { sandboxScenario } from './sandbox-contract';

export const matrixReference = z.object({ batch_id: z.string().uuid(), matrix_id: z.string().uuid(), matrix_revision: z.number().int().positive(), variant_id: z.string().regex(/^[A-Za-z0-9_-]{1,40}$/), variant_label: z.string().trim().min(1).max(120) });
export const matrixVariant = z.object({
    id: z.string().regex(/^[A-Za-z0-9_-]{1,40}$/), label: z.string().trim().min(1).max(120),
    sandbox: sandboxScenario, expected: z.string().trim().min(1).max(4000),
    checkpoints: checkpointsInput.refine(items => items.length > 0, 'Define at least one observable checkpoint for this variant.'),
});
export const matrixInput = z.object({ workspace_id: z.string().uuid(), case_id: z.string().uuid(), name: z.string().trim().min(1).max(120),
    variants: z.array(matrixVariant).min(2).max(20).refine(items => new Set(items.map(v => v.id)).size === items.length, 'Variant IDs must be unique.').refine(items => new Set(items.map(v => v.label.toLowerCase())).size === items.length, 'Variant labels must be unique.'),
}).refine(value => new TextEncoder().encode(JSON.stringify(value)).length <= 1000000, 'Matrix definition exceeds 1 MB.');
export type MatrixVariant = z.infer<typeof matrixVariant>;
export type ScenarioMatrix = z.infer<typeof matrixInput> & { id: string; revision: number; updated: string };
export type MatrixSnapshot = TestCase & { matrix: z.infer<typeof matrixReference> };
export function applyVariant(base: TestCase, matrix: ScenarioMatrix, variant: MatrixVariant, batch: string): MatrixSnapshot {
    return { ...base, goal: `Execute the saved steps for "${base.title}" using scenario "${variant.label}" while applicable. Judge completion against this variant's expected result and checkpoints. When its expected outcome is observed, finish there instead of continuing steps that require a different outcome.`, sandbox: variant.sandbox, expected: variant.expected, checkpoints: variant.checkpoints, assertion_text: '',
        matrix: { batch_id: batch, matrix_id: matrix.id, matrix_revision: matrix.revision, variant_id: variant.id, variant_label: variant.label } };
}
export function decodeMatrix(row: Record<string, unknown>): ScenarioMatrix {
    return { ...matrixInput.parse(JSON.parse(String(row.definition_json))), id: String(row.id), revision: Number(row.revision), updated: String(row.updated) };
}
export type MatrixRow = { variant_id: string; label: string; expected: string; checkpoints: MatrixVariant['checkpoints']; scenario: { id: string; name: string }; status: string; run_id?: string; external_run_id?: string; build?: string; device?: string; checkpoint_results?: import('./contracts').CheckpointResult[]; runner_error?: string; sync_error?: string; evidence_failures?: string[] };
export type MatrixReport = { batch_id: string; workspace_id: string; matrix_id: string; matrix_revision: number; matrix_name: string; case_id: string; case_revision: number; status: string; created: string; rows: MatrixRow[]; summary: { status: string; stop_reason?: string; error?: string; active_run_id?: string | null; current_case_index?: number } };
