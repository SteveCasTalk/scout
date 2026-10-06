import { executionInput } from './execution-contract';
import { sandboxScenario } from './sandbox-contract';
import { z } from 'zod';
export const checkpointInput = z.object({ id: z.string().regex(/^[A-Za-z0-9_-]{1,40}$/), expected: z.string().trim().min(1).max(1000), scope: z.enum(['during_run', 'final']), required: z.boolean(), method: z.enum(['classification', 'text_present', 'text_absent']) });
export const checkpointsInput = z.array(checkpointInput).max(12).refine(items => new Set(items.map(item => item.id)).size === items.length, 'Checkpoint IDs must be unique').refine(items => !items.length || items.some(item => item.required), 'At least one checkpoint must be required');
export const checkpointResult = checkpointInput.extend({ verdict: z.enum(['satisfied','violated','not_observable','not_reached']), confidence: z.number().min(0).max(1), reason: z.string().max(4000), evidence_steps: z.array(z.number().int().nonnegative()).max(100), observed: z.string().max(8000), investigation: z.object({ captured_at: z.string().max(50), elapsed_ms: z.number().int().nonnegative(), foreground: z.string().max(240), app_process_running: z.boolean(), app_logs: z.string().max(6000) }).optional(), model: z.string().optional(), probabilities: z.record(z.string(), z.number()).optional() });
export type Checkpoint = z.infer<typeof checkpointInput>;
export type CheckpointResult = z.infer<typeof checkpointResult>;
export const startingConditionsInput = z.object({ account: z.string().trim().max(160).default(''), login_state: z.enum(['any','signed_in','signed_out']).default('any'), app_version: z.string().trim().max(120).default(''), required_data: z.array(z.string().trim().max(160)).max(8).transform(items => items.filter(Boolean)).default([]) });
export const startingConditionResult = z.object({ kind: z.enum(['app_installed','app_version','account','login_state','required_data']), expected: z.string().max(240), actual: z.string().max(240), status: z.enum(['met','missing','unknown']), reason: z.string().max(1000), observed_step: z.number().int().nonnegative() });
export type StartingConditions = z.infer<typeof startingConditionsInput>;
export type StartingConditionResult = z.infer<typeof startingConditionResult>;
export const caseInput = z.object({ execution: executionInput.nullable().optional(), sandbox: sandboxScenario.nullable().default(null), comparison_key: z.string().trim().regex(/^[A-Za-z0-9_-]*$/).max(80).default(''), starting_conditions: startingConditionsInput.default({}), workspace_id: z.string().min(1).max(80), checkpoints: checkpointsInput.default([]), project: z.string().trim().min(1).max(100).default('General'), ticket_key: z.string().trim().max(40).default(''), app_id: z.string().trim().max(240).default(''), title: z.string().trim().min(1).max(160), platform: z.enum(['Android', 'iOS']), suite: z.string().trim().min(1).max(80), goal: z.string().trim().min(1).max(4000), preconditions: z.string().max(4000), steps: z.string().trim().min(1).max(8000), expected: z.string().trim().min(1).max(4000), assertion_text: z.string().trim().max(240).default('') });
export const statuses = ['Passed', 'Failed', 'Inconclusive', 'Blocked', 'Execution error'] as const;
export const jevAudit = z.object({
    request: z.object({ model: z.string(), state: z.unknown().optional(), questions: z.record(z.string(), z.object({ type: z.string(), criteria: z.record(z.string(), z.unknown()), instructions: z.unknown().optional() })) }),
    response: z.object({ model: z.string().nullable().optional(), answers: z.record(z.string(), z.object({ choice: z.string(), confidence: z.number().min(0).max(1), probabilities: z.record(z.string(), z.number().min(0).max(1)) })), usage: z.unknown().optional() }),
    latency_ms: z.number().int().nonnegative(),
});
export const deviceInfoInput = z.object({ automation_backend: z.enum(['adb','appium']).optional(), session_start_ms: z.string().max(20).optional(), manufacturer: z.string().max(120).optional(), model: z.string().max(120).optional(), ios_version: z.string().max(80).optional(), android_version: z.string().max(80).optional(), api_level: z.string().max(20).optional(), screen_size: z.string().max(80).optional(), package: z.string().max(240).optional(), app_version: z.string().max(120).optional() }).strict();
export const runInput = z.object({ caseId: z.string().uuid(), revision: z.number().int().positive(), externalRunId: z.string().max(80).optional(), status: z.enum(statuses), build: z.string().trim().min(1).max(120), device: z.string().trim().min(1).max(160), device_info: deviceInfoInput.default({}), app_logs: z.string().max(20000).default(''), notes: z.string().trim().min(1).max(8000), source: z.enum(['Manual','Scout import','Jev import','Prompt run']).default('Manual'), trace: z.array(z.object({step:z.number().int().nonnegative(),starting_condition_results:z.array(startingConditionResult).max(11).optional(),checkpoint_results:z.array(checkpointResult).max(12).optional(),operation:z.string().max(40),label:z.string().max(200).nullable().optional(),elapsed_ms:z.number().int().nonnegative().optional(),screenshot:z.string().max(100).nullable().optional(),verification:z.object({status:z.enum(['passed','failed','inconclusive','not_run']),method:z.string().max(80),expected_text:z.string().max(8000),observed_text:z.string().max(8000)}).optional(),jev:jevAudit.optional()})).max(204).default([]) });
export type TestCase = z.infer<typeof caseInput> & {
    id: string;
    revision: number;
    updated: string;
};
export type Run = {
    id: string;
    workspace_id: string;
    case_id: string;
    snapshot: TestCase & { matrix?: { batch_id: string; matrix_id: string; matrix_revision: number; variant_id: string; variant_label: string } };
    status: typeof statuses[number];
    build: string;
    device: string;
    device_info: z.infer<typeof deviceInfoInput>;
    app_logs: string;
    notes: string;
    created: string;
    source: 'Manual' | 'Scout import' | 'Jev import' | 'Prompt run';
    external_run_id?: string | null;
    trace: {step:number;starting_condition_results?:StartingConditionResult[];checkpoint_results?:CheckpointResult[];operation:string;label?:string|null;elapsed_ms?:number;screenshot?:string|null;verification?:{status:'passed'|'failed'|'inconclusive'|'not_run';method:string;expected_text:string;observed_text:string};jev?:z.infer<typeof jevAudit>}[];
};
export type Evidence = {
    id: string;
    run_id: string;
    workspace_id: string;
    name: string;
    mime: string;
    size: number;
    created: string;
};

export type ReviewNote = { id: string; workspace_id: string; target_type: 'case' | 'run'; target_id: string; body: string; created: string; updated: string };

export type CheckpointReview = { id: string; workspace_id: string; run_id: string; checkpoint_id: string; original_verdict: CheckpointResult['verdict']; decision: 'accept' | 'dispute'; explanation: string; created: string };
