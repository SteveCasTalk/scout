import { z } from 'zod';
const id = z.string().regex(/^[A-Za-z0-9_-]{1,60}$/);
const host = z.string().max(253).regex(/^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$/).refine(s => !s.includes('..'));
const path = z.string().max(500).regex(/^\/[^?#\r\n]*$/);
const reply = z.object({ status: z.number().int().min(200).max(599).default(200), body: z.string().max(64000).default('{}'), delay_ms: z.number().int().min(0).max(30000).default(0), headers: z.record(z.string(), z.string()).default({'Content-Type':'application/json'}).refine(h => Object.keys(h).length <= 20 && Object.entries(h).every(([k,v]) => /^[A-Za-z0-9-]{1,80}$/.test(k) && v.length <= 1000 && !/[\r\n]/.test(v) && !['content-length','transfer-encoding','connection','content-encoding'].includes(k.toLowerCase())), 'Invalid response headers') }).strict();
const match = { id, host, path, required_hits: z.number().int().min(0).max(100).default(1) };
export const sandboxScenario = z.object({
    schema_version: z.literal(1).default(1), id, name: z.string().min(1).max(120), project: z.string().min(1).max(100), description: z.string().max(2000).default(''), hosts: z.array(host).min(1).max(20), unmatched: z.enum(['block','passthrough']).default('block'),
    http: z.array(z.object({ ...match, method: z.enum(['GET','POST','PUT','PATCH','DELETE','HEAD','OPTIONS']).default('GET'), responses: z.array(reply).min(1).max(20), exhaustion: z.enum(['repeat_last','block']).default('repeat_last') }).strict()).max(40).default([]),
    websocket: z.array(z.object({ ...match, frames: z.array(z.object({ direction: z.enum(['client','server']).default('server'), contains: z.string().max(1000).default(''), action: z.enum(['replace','drop']).default('replace'), body: z.string().max(64000).default('{}') }).strict()).max(20).default([]), pushes: z.array(z.object({ after_ms: z.number().int().min(0).max(60000).default(0), body: z.string().max(64000).default('{}') }).strict()).max(20).default([]) }).strict()).max(20).default([]),
}).strict().superRefine((s, ctx) => {
    const rules = [...s.http,...s.websocket];
    if (!rules.length || !rules.some(r => r.required_hits > 0)) ctx.addIssue({ code: z.ZodIssueCode.custom, message: 'At least one rule must require a hit.' });
    if (new Set(s.hosts).size !== s.hosts.length || new Set(rules.map(r => r.id)).size !== rules.length) ctx.addIssue({code:z.ZodIssueCode.custom,message:'Hosts and rule IDs must be unique.'});
    if (rules.some(r => !s.hosts.includes(r.host))) ctx.addIssue({code:z.ZodIssueCode.custom,message:'Every rule host must be listed in hosts.'});
    if (s.websocket.some(r => !r.frames.length && !r.pushes.length)) ctx.addIssue({code:z.ZodIssueCode.custom,message:'WebSocket rules need frame actions or server pushes.'});
    const matches=[...s.http.map(r=>`http:${r.method}:${r.host}:${r.path}`),...s.websocket.map(r=>`ws:${r.host}:${r.path}`)];
    if (new Set(matches).size !== matches.length) ctx.addIssue({code:z.ZodIssueCode.custom,message:'Duplicate match rules are ambiguous.'});
    if (JSON.stringify(s).length > 400000) ctx.addIssue({code:z.ZodIssueCode.custom,message:'Scenario exceeds 400 KB.'});
});
export type SandboxScenario = z.infer<typeof sandboxScenario>;
export type SandboxReport = { scenario_id: string; name: string; fingerprint: string; status: 'satisfied'|'inconclusive'; requirements: {id:string;required_hits:number;actual_hits:number}[]; missing_rules:string[]; blocked_events:number; events:{elapsed_ms:number;rule_id:string;action:string;direction?:string;status?:number}[]; payloads_recorded:boolean };
