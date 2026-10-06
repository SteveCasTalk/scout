import { z } from 'zod';
import { caseInput } from './contracts';
import { decodeCase, retainRevision } from './case-record';
import { requireCaseCapabilities } from './execution-contract';
import { HttpError } from './errors';

export const authoringItem=z.object({request_id:z.string().uuid(),case:caseInput,id:z.string().uuid().optional(),expected_revision:z.number().int().positive().optional()}).strict();
function canonical(value:unknown):string{
 if(Array.isArray(value))return '['+value.map(canonical).join(',')+']';
 if(value&&typeof value==='object')return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+canonical((value as Record<string,unknown>)[k])).join(',')+'}';
 return JSON.stringify(value);
}
export async function writeCase(db:D1Database,owner:string,workspace:string,value:unknown,peer:unknown,dryRun=false){
 const item=authoringItem.parse(value),c=item.case;
 if(c.workspace_id!==workspace)throw new HttpError(400,'Case workspace must match the explicit authoring workspace.');
 requireCaseCapabilities(c,peer);
 if(!await db.prepare('SELECT id FROM workspaces WHERE owner=? AND id=?').bind(owner,workspace).first())throw new HttpError(404,'Workspace not found.');
 if(!!item.id!==!!item.expected_revision)throw new HttpError(400,'Updates require both case ID and expected_revision.');
 const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(canonical(item))))).map(n=>n.toString(16).padStart(2,'0')).join('');
 const existing=await db.prepare('SELECT payload_hash,response_json FROM case_authoring_requests WHERE owner=? AND workspace_id=? AND request_id=?').bind(owner,workspace,item.request_id).first<{payload_hash:string;response_json:string}>();
 if(existing){if(existing.payload_hash!==hash)throw new HttpError(409,'Request ID was already used for a different definition.');const replay=JSON.parse(existing.response_json);if(replay.error)throw new HttpError(replay.status||409,replay.error);return {...replay,duplicate:true};}
 const previous=item.id?await db.prepare('SELECT * FROM test_cases WHERE owner=? AND workspace_id=? AND id=? AND revision=?').bind(owner,workspace,item.id,item.expected_revision).first():null;
 if(item.id&&!previous)throw new HttpError(409,'Case revision conflict. Reload the definition.');
 if(previous){requireCaseCapabilities(decodeCase(previous),peer);if(decodeCase(previous).execution&&!Object.prototype.hasOwnProperty.call((value as {case:object}).case,'execution'))throw new HttpError(409,'Execution settings cannot be silently dropped.');}
 if(previous&&decodeCase(previous).sandbox?.schema_version===2&&!Object.prototype.hasOwnProperty.call((value as {case:object}).case,'sandbox'))throw new HttpError(409,'Sandbox settings cannot be silently dropped.');
 if(dryRun)return {valid:true,id:item.id||null,expected_revision:item.expected_revision||null};
 const id=item.id||crypto.randomUUID(),revision=(item.expected_revision||0)+1,updated=new Date().toISOString(),claim=crypto.randomUUID();
 const response={case:{...c,id,revision,updated}},error={error:'Case revision conflict. Reload the definition.',status:409};
 const key=[owner,workspace,item.request_id,claim];
 const hasClaim='EXISTS (SELECT 1 FROM case_authoring_requests WHERE owner=? AND workspace_id=? AND request_id=? AND claim=?)';
 const statements=[];
 if(previous)statements.push(retainRevision(db,owner,decodeCase(previous)));
 statements.push(db.prepare("INSERT OR IGNORE INTO case_authoring_requests (owner,workspace_id,request_id,payload_hash,claim,response_json,created) VALUES (?,?,?,?,?,'{}',?)").bind(owner,workspace,item.request_id,hash,claim,updated));
 if(item.id){
 statements.push(db.prepare('UPDATE test_cases SET project=?,ticket_key=?,comparison_key=?,sandbox_json=?,execution_json=?,app_id=?,title=?,platform=?,suite=?,goal=?,preconditions=?,steps=?,expected=?,assertion_text=?,checkpoints_json=?,starting_conditions_json=?,revision=revision+1,updated=? WHERE id=? AND owner=? AND workspace_id=? AND revision=? AND '+hasClaim).bind(c.project,c.ticket_key,c.comparison_key,JSON.stringify(c.sandbox),JSON.stringify(c.execution||null),c.app_id,c.title,c.platform,c.suite,c.goal,c.preconditions,c.steps,c.expected,c.assertion_text,JSON.stringify(c.checkpoints),JSON.stringify(c.starting_conditions),updated,id,owner,workspace,item.expected_revision,...key));
 }else{
 statements.push(db.prepare('INSERT INTO test_cases (id,owner,workspace_id,project,ticket_key,comparison_key,sandbox_json,execution_json,app_id,title,platform,suite,goal,preconditions,steps,expected,assertion_text,checkpoints_json,starting_conditions_json,revision,updated) SELECT ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,? WHERE '+hasClaim).bind(id,owner,workspace,c.project,c.ticket_key,c.comparison_key,JSON.stringify(c.sandbox),JSON.stringify(c.execution||null),c.app_id,c.title,c.platform,c.suite,c.goal,c.preconditions,c.steps,c.expected,c.assertion_text,JSON.stringify(c.checkpoints),JSON.stringify(c.starting_conditions),updated,...key));
 }
 // changes() immediately follows the case mutation within the same atomic D1 batch.
 statements.push(db.prepare('UPDATE case_authoring_requests SET response_json=CASE WHEN changes()>0 THEN ? ELSE ? END WHERE owner=? AND workspace_id=? AND request_id=? AND claim=?').bind(JSON.stringify(response),JSON.stringify(error),...key));
 statements.push(db.prepare('INSERT OR IGNORE INTO case_revisions (owner,workspace_id,case_id,revision,snapshot_json,created) SELECT ?,?,?,?,?,? WHERE EXISTS (SELECT 1 FROM test_cases WHERE owner=? AND workspace_id=? AND id=? AND revision=?) AND EXISTS (SELECT 1 FROM case_authoring_requests WHERE owner=? AND workspace_id=? AND request_id=? AND claim=? AND json_extract(response_json,\'$.case.id\')=?)').bind(owner,workspace,id,revision,JSON.stringify(response.case),updated,owner,workspace,id,revision,...key,id));
 await db.batch(statements);
 const saved=await db.prepare('SELECT payload_hash,response_json FROM case_authoring_requests WHERE owner=? AND workspace_id=? AND request_id=?').bind(owner,workspace,item.request_id).first<{payload_hash:string;response_json:string}>();
 if(!saved||saved.payload_hash!==hash)throw new HttpError(409,'Concurrent request ID conflict.');
 const result=JSON.parse(saved.response_json);
 if(result.error)throw new HttpError(result.status||409,result.error);
 return result;
}
