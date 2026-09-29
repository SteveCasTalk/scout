import { z } from 'zod';
export const caseInput = z.object({ workspace_id: z.string().min(1).max(80), project: z.string().trim().min(1).max(100).default('General'), ticket_key: z.string().trim().max(40).default(''), app_id: z.string().trim().max(240).default(''), title: z.string().trim().min(1).max(160), platform: z.enum(['Android', 'iOS']), suite: z.string().trim().min(1).max(80), goal: z.string().trim().min(1).max(4000), preconditions: z.string().max(4000), steps: z.string().trim().min(1).max(8000), expected: z.string().trim().min(1).max(4000), assertion_text: z.string().trim().max(240).default('') });
export const statuses = ['Passed', 'Failed', 'Inconclusive', 'Execution error'] as const;
export const jevAudit = z.object({
    request: z.object({ model: z.string(), state: z.unknown().optional(), questions: z.record(z.string(), z.object({ type: z.string(), criteria: z.record(z.string(), z.unknown()), instructions: z.unknown().optional() })) }),
    response: z.object({ model: z.string().nullable().optional(), answers: z.record(z.string(), z.object({ choice: z.string(), confidence: z.number().min(0).max(1), probabilities: z.record(z.string(), z.number().min(0).max(1)) })), usage: z.unknown().optional() }),
    latency_ms: z.number().int().nonnegative(),
});
export const runInput = z.object({ caseId: z.string().uuid(), revision: z.number().int().positive(), externalRunId: z.string().max(80).optional(), status: z.enum(statuses), build: z.string().trim().min(1).max(120), device: z.string().trim().min(1).max(160), notes: z.string().trim().min(1).max(8000), source: z.enum(['Manual','Jev import','Prompt run']).default('Manual'), trace: z.array(z.object({step:z.number().int().nonnegative(),operation:z.string().max(40),label:z.string().max(200).nullable().optional(),elapsed_ms:z.number().int().nonnegative().optional(),screenshot:z.string().max(100).nullable().optional(),verification:z.object({status:z.enum(['passed','failed','inconclusive','not_run']),method:z.string().max(80),expected_text:z.string().max(8000),observed_text:z.string().max(8000)}).optional(),jev:jevAudit.optional()})).max(102).default([]) });
export type TestCase = z.infer<typeof caseInput> & {
    id: string;
    revision: number;
    updated: string;
};
export type Run = {
    id: string;
    workspace_id: string;
    case_id: string;
    snapshot: TestCase;
    status: typeof statuses[number];
    build: string;
    device: string;
    notes: string;
    created: string;
    source: 'Manual' | 'Jev import' | 'Prompt run';
    external_run_id?: string | null;
    trace: {step:number;operation:string;label?:string|null;elapsed_ms?:number;screenshot?:string|null;verification?:{status:'passed'|'failed'|'inconclusive'|'not_run';method:string;expected_text:string;observed_text:string};jev?:z.infer<typeof jevAudit>}[];
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
