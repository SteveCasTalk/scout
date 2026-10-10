import { z } from 'zod';
const id=z.string().regex(/^[A-Za-z0-9_-]{1,40}$/), pkg=z.string().regex(/^[A-Za-z0-9_.]{3,240}$/);
export const selectorInput=z.object({resource_id:z.string().max(240).default(''),text:z.string().max(240).default(''),class_name:z.string().max(240).default('')}).strict().refine(v=>!!v.resource_id||!!v.text,'Exact resource_id or text is required.');
const entry=z.object({id,selector:selectorInput,screen_text:z.string().min(1).max(240),destination_package:pkg,destination_text:z.string().min(1).max(240),timeout_ms:z.number().int().min(100).max(30000).default(10000)}).strict();
const external=z.object({package:pkg,from_package:pkg,entry_text:z.string().min(1).max(240),return_text:z.string().min(1).max(240),max_duration_ms:z.number().int().min(100).max(120000).default(30000),max_actions:z.number().int().min(0).max(10).default(2),taps:z.array(selectorInput).max(10).default([]),allow_back:z.boolean().default(false),checkout:z.boolean().default(false),require_return:z.boolean().default(true)}).strict();
const action=z.object({id,operation:z.enum(['TAP','BACK','SWIPE','DRAG','TAP_BURST','PURCHASE_ENTRY','OBSERVE','BACKGROUND']),package:pkg,selector:selectorInput.nullable().default(null),destination:selectorInput.nullable().default(null),entry_id:z.string().max(40).default(''),direction:z.enum(['left','right','up','down']).default('left'),duration_ms:z.number().int().min(50).max(3000).default(300),hold_ms:z.number().int().min(0).max(2000).default(400),count:z.number().int().min(2).max(5).default(2),interval_ms:z.number().int().min(50).max(1000).default(100),wait_text:z.string().max(240).default(''),timeout_ms:z.number().int().min(100).max(30000).default(5000),background_ms:z.number().int().min(500).max(120000).default(3000),travel:z.tuple([z.number(),z.number()]).default([0.85,0.15])}).strict().superRefine((v,c)=>{
 if(['TAP','SWIPE','DRAG','TAP_BURST'].includes(v.operation)&&!v.selector)c.addIssue({code:'custom',message:'Selector required.'});
 if(!(v.travel[1]>=0.05&&v.travel[1]<v.travel[0]&&v.travel[0]<=0.95))c.addIssue({code:'custom',message:'Swipe travel must be [start, end] with 0.05 <= end < start <= 0.95.'});
 if(v.operation==='DRAG'&&!v.destination)c.addIssue({code:'custom',message:'Drag destination required.'});
 if(v.operation==='PURCHASE_ENTRY'&&!id.safeParse(v.entry_id).success)c.addIssue({code:'custom',message:'Entry ID required.'});
});
const temporal=z.object({id,after_action:id,mode:z.enum(['within','never_during','stable_for','ordered','until']),text:z.string().min(1).max(240),context_text:z.string().min(1).max(240),until_text:z.string().max(240).default(''),ordered_texts:z.array(z.string().trim().min(1).max(240)).max(10).default([]),window_ms:z.number().int().min(100).max(600000),poll_ms:z.number().int().min(50).max(5000).default(250),max_gap_ms:z.number().int().min(100).max(10000).default(2000),evidence:z.enum(['sampled_ui','continuous_events']).default('sampled_ui'),required:z.boolean().default(true)}).strict().superRefine((v,c)=>{
 if(v.mode==='ordered'&&v.ordered_texts.length<2)c.addIssue({code:'custom',message:'Ordered needs at least two predicates.'});
 if(v.mode==='until'&&!v.until_text)c.addIssue({code:'custom',message:'Until requires terminal text.'});
});
const hook=z.object({id,operation:z.enum(['terminate','permission','wifi','clear_data']),permission:z.string().regex(/^(?:android\.permission\.[A-Z_]+)?$/).max(120).default(''),enabled:z.boolean().default(false)}).strict().refine(v=>v.operation!=='permission'||!!v.permission,'Permission required.');
const media=z.object({id,artifact:z.string().regex(/^[A-Za-z0-9_-]+\.(?:mp4|webm|mov|wav|mp3)$/).max(100),width:z.number().int().min(1).max(16384).nullable().default(null),height:z.number().int().min(1).max(16384).nullable().default(null),duration_min_ms:z.number().int().min(0).max(3600000).default(0),duration_max_ms:z.number().int().min(1).max(3600000).default(3600000),required:z.boolean().default(true),kind:z.enum(['metadata','frame_change']).default('metadata'),frame_start_ms:z.number().int().min(0).max(3600000).default(0),frame_end_ms:z.number().int().min(1).max(3600000).default(1000),minimum_change:z.number().min(0).max(1).default(0.02)}).strict().refine(v=>v.frame_start_ms<v.frame_end_ms,'Frame samples must be ordered.').refine(v=>v.duration_min_ms<=v.duration_max_ms,'Invalid duration range.');
export const executionInput=z.object({schema_version:z.literal(2).default(2),required_capabilities:z.array(z.string()).max(20).default([]),purchase_entries:z.array(entry).max(5).default([]),external_flows:z.array(external).max(10).default([]),actions:z.array(action).max(100).default([]),temporal_assertions:z.array(temporal).max(12).default([]),lifecycle:z.object({before:z.array(hook).max(10).default([]),notification_policy:z.enum(['legacy_suppress','preserve']).default('legacy_suppress')}).strict().default({}),media_assertions:z.array(media).max(12).default([]),finish:z.enum(['verify','model']).default('verify'),timeout_seconds:z.number().int().min(10).max(1800).default(600)}).strict().superRefine((v,c)=>{
 const collections=[v.actions.map(a=>a.id),v.purchase_entries.map(a=>a.id),v.temporal_assertions.map(a=>a.id),v.media_assertions.map(a=>a.id),v.lifecycle.before.map(a=>a.id),v.external_flows.map(a=>a.package),v.required_capabilities];
 if(collections.some(a=>new Set(a).size!==a.length))c.addIssue({code:'custom',message:'IDs/packages/capabilities must be unique.'});
 if(v.temporal_assertions.some(t=>!v.actions.some(a=>a.id===t.after_action)))c.addIssue({code:'custom',message:'Unknown temporal trigger.'});
 const used=v.actions.filter(a=>a.operation==='PURCHASE_ENTRY').map(a=>a.entry_id);
 if(new Set(used).size!==used.length||used.some(i=>!v.purchase_entries.some(e=>e.id===i)))c.addIssue({code:'custom',message:'Unknown or repeated purchase entry.'});
 if(used.length){
  if(v.finish!=='verify')c.addIssue({code:'custom',message:'Purchase entry must finish in verification.'});
  let opened=false;for(const a of v.actions){if(opened&&!['OBSERVE','BACK'].includes(a.operation))c.addIssue({code:'custom',message:'Only observation/back after purchase entry.'});if(a.operation==='PURCHASE_ENTRY')opened=true;}
  if(v.actions.some(a=>a.operation==='TAP_BURST'&&v.purchase_entries.some(e=>JSON.stringify(a.selector)===JSON.stringify(e.selector))))c.addIssue({code:'custom',message:'Purchase bursts are forbidden.'});
 }
 const needed:string[]=[];
 if(v.purchase_entries.length)needed.push('purchase_entry');if(v.external_flows.length)needed.push('external_packages');
 if(v.actions.some(a=>['SWIPE','DRAG'].includes(a.operation)))needed.push('target_gestures');if(v.actions.some(a=>a.operation==='TAP_BURST'))needed.push('tap_burst');if(v.actions.some(a=>a.operation==='BACKGROUND'))needed.push('app_background');
 if(v.temporal_assertions.length)needed.push('temporal_ui');if(v.lifecycle.before.length||v.lifecycle.notification_policy!=='legacy_suppress')needed.push('lifecycle');if(v.media_assertions.length)needed.push('media_metadata');
 if(needed.some(n=>!v.required_capabilities.includes(n)))c.addIssue({code:'custom',message:'Declare every required capability: '+needed.join(', ')});
});
export type Execution=z.infer<typeof executionInput>;
export const capableClient={contract_versions:[1,2],features:['purchase_entry','external_packages','target_gestures','tap_burst','temporal_ui','lifecycle','media_metadata','network_contract_v2','request_assertions','app_background']};
export function runGrants(execution:Execution|null|undefined,purchase:boolean,clear:boolean){return {purchase_entries:purchase?(execution?.purchase_entries.map(e=>e.id)||[]):[],clear_data:clear&&!!execution?.lifecycle.before.some(h=>h.operation==='clear_data')};}
export const runnerHandshake=z.object({contract_versions:z.array(z.number().int()),features:z.array(z.string())});
export function requireCapabilities(execution:Execution|null|undefined,peer:unknown){
 if(!execution)return;
 const result=runnerHandshake.safeParse(peer);
 if(!result.success||!result.data.contract_versions.includes(2)||execution.required_capabilities.some(c=>!result.data.features.includes(c)))throw new Error('Runner capability handshake does not support this case. Upgrade/reload the runner.');
}
export function exportCase<T extends {execution?:Execution|null;sandbox?:{schema_version:number}|null}>(value:T){return value.execution||value.sandbox?.schema_version===2?{format:'scout-case-v2',case:value}:value;}

export function requireCaseCapabilities(value:{execution?:Execution|null;sandbox?:{schema_version:number;http?:({assertions?:unknown[]}|{id:string})[]}|null},peer:unknown){
 requireCapabilities(value.execution,peer);
 if(value.sandbox?.schema_version===2)requireCapabilities({required_capabilities:['network_contract_v2',...(value.sandbox.http?.some(r=>'assertions' in r&&r.assertions?.length)?['request_assertions']:[])]} as Execution,peer);
}
