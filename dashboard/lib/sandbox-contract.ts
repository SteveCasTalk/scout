import { z } from 'zod';
const id = z.string().regex(/^[A-Za-z0-9_-]{1,60}$/);
const host = z.string().max(253).regex(/^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$/).refine(s => !s.includes('..'));
const path = z.string().max(500).regex(/^\/[^?#\r\n]*$/);
const reply = z.object({ status: z.number().int().min(200).max(599).default(200), body: z.string().max(64000).default('{}'), delay_ms: z.number().int().min(0).max(30000).default(0), headers: z.record(z.string(), z.string()).default({'Content-Type':'application/json'}).refine(h => Object.keys(h).length <= 20 && Object.entries(h).every(([k,v]) => /^[A-Za-z0-9-]{1,80}$/.test(k) && v.length <= 1000 && !/[\r\n]/.test(v) && !['content-length','transfer-encoding','connection','content-encoding'].includes(k.toLowerCase())), 'Invalid response headers') }).strict();
const match = { id, host, path, required_hits: z.number().int().min(0).max(100).default(1) };
const legacyScenario = z.object({
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
const source=z.enum(['query','header','json','path']);
const safeField=z.object({source,key:z.string().min(1).max(240)}).strict();
function fieldSafe(v:{source:string;key:string}){return !/authorization|cookie|password|secret|token|api[-_]?key/i.test(v.key)&&(v.source!=='json'||v.key.startsWith('/'));}
const correlation=safeField.refine(fieldSafe,'Secret fields are forbidden and JSON keys must be pointers.');
const predicate=safeField.extend({operator:z.enum(['equals','exists']).default('equals'),value:z.union([z.string(),z.number().finite(),z.boolean(),z.null()]).default(null)}).refine(fieldSafe,'Unsafe predicate field.').refine(v=>v.operator!=='exists'||typeof v.value==='boolean','Exists requires boolean.');
const assertion=safeField.extend({id,kind:z.enum(['equals','exists','count','ordered','duplicate']),expected:z.union([z.string(),z.number().finite(),z.boolean(),z.array(z.string().max(240)),z.null()]).default(null)}).refine(fieldSafe,'Unsafe assertion field.').superRefine((v,c)=>{
 if(v.kind==='count'&&(!Number.isInteger(v.expected)||Number(v.expected)<0||Number(v.expected)>10000))c.addIssue({code:'custom',message:'Count requires bounded integer.'});
 if(v.kind==='ordered'&&(!Array.isArray(v.expected)||v.expected.length>100))c.addIssue({code:'custom',message:'Ordered requires at most 100 identifiers.'});
});
const base=legacyScenario.innerType();
const httpV2=base.shape.http.removeDefault().element.extend({path_template:z.boolean().default(false),match:z.array(predicate).max(20).default([]),correlation:correlation.nullable().default(null),advance_on:z.string().max(60).default(''),emit_event:z.string().max(60).default(''),assertions:z.array(assertion).max(20).default([])});
const wsBase=base.shape.websocket.removeDefault().element;
const wsV2=wsBase.extend({path_template:z.boolean().default(false),match:z.array(predicate).max(20).default([]),correlation:correlation.nullable().default(null),pushes:z.array(wsBase.shape.pushes.removeDefault().element.extend({after_ms:z.number().int().min(0).max(600000).default(0),trigger_event:z.string().max(60).default('')})).max(20).default([])});
const scenarioV2=base.extend({schema_version:z.literal(2),http:z.array(httpV2).max(40).default([]),websocket:z.array(wsV2).max(20).default([])}).superRefine((s,c)=>{
 const rules=[...s.http,...s.websocket],events=new Set(s.http.map(r=>r.emit_event).filter(Boolean));
 if(!rules.length||!rules.some(r=>r.required_hits>0))c.addIssue({code:'custom',message:'At least one rule must require a hit.'});
 if(new Set(s.hosts).size!==s.hosts.length||new Set(rules.map(r=>r.id)).size!==rules.length)c.addIssue({code:'custom',message:'Unique hosts and rule IDs required.'});
 if(rules.some(r=>!s.hosts.includes(r.host)))c.addIssue({code:'custom',message:'Rule host must be listed.'});
 if(s.websocket.some(r=>!r.frames.length&&!r.pushes.length))c.addIssue({code:'custom',message:'WS actions required.'});
 if(rules.some(r=>r.path_template&&r.path.split('/').some(p=>(p.includes('{')||p.includes('}'))&&!/^\{[A-Za-z][A-Za-z0-9_]*\}$/.test(p))))c.addIssue({code:'custom',message:'Template parameters occupy whole path segments.'});
 for(const r of s.http){if([r.advance_on,r.emit_event].some(e=>!!e&&!id.safeParse(e).success)||!!r.advance_on&&!events.has(r.advance_on))c.addIssue({code:'custom',message:'Invalid advancement event.'});if(new Set(r.assertions.map(a=>a.id)).size!==r.assertions.length)c.addIssue({code:'custom',message:'Duplicate assertion IDs.'});}
 if(s.websocket.some(r=>r.pushes.some(p=>!!p.trigger_event&&!events.has(p.trigger_event))))c.addIssue({code:'custom',message:'Unknown push trigger.'});
 const matches=[...s.http.map(r=>JSON.stringify(['http',r.host,r.path,r.method,r.match])),...s.websocket.map(r=>JSON.stringify(['ws',r.host,r.path,'WS',r.match]))];
 if(new Set(matches).size!==matches.length)c.addIssue({code:'custom',message:'Duplicate v2 matches.'});
 if(new TextEncoder().encode(JSON.stringify(s)).length>400000)c.addIssue({code:'custom',message:'Scenario exceeds 400 KB.'});
});
export const sandboxScenario=z.union([legacyScenario,scenarioV2]);
export type SandboxScenario = z.infer<typeof sandboxScenario>;
export type SandboxReport = { scenario_id: string; name: string; fingerprint: string; status: 'satisfied'|'inconclusive'; requirements: {id:string;required_hits:number;actual_hits:number}[]; missing_rules:string[]; blocked_events:number; events:{elapsed_ms:number;rule_id:string;action:string;direction?:string;status?:number}[]; payloads_recorded:boolean };
