// Synthetic integration checks against SQLite; does not run devices or the dashboard.
import { build } from 'esbuild';
import assert from 'node:assert/strict';
import { mkdtempSync,readFileSync,readdirSync,rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join,resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { spawnSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
const root=resolve(import.meta.dirname,'..'),scratch=mkdtempSync(join(tmpdir(),'scout-capabilities-'));
const python=process.env.SCOUT_CHECK_PYTHON||resolve(root,'../.venv/bin/python');
const dbPath=join(scratch,'checks.sqlite');
const sqlRunner=`import sys,json,sqlite3\np=json.load(sys.stdin)\nc=sqlite3.connect(p['db']);c.row_factory=sqlite3.Row\ntry:\n if p.get('scripts'):\n  for s in p['scripts']:c.executescript(s)\n result=[]\n for s in p.get('statements',[]):\n  cur=c.execute(s['sql'],s.get('params',[]));rows=[dict(r) for r in cur.fetchall()]\n  result.append({'results':rows,'meta':{'changes':c.execute('SELECT changes()').fetchone()[0]}})\n c.commit();print(json.dumps(result))\nexcept Exception as e:\n c.rollback();print(json.dumps({'error':str(e)}));sys.exit(1)\nfinally:c.close()\n`;
function runSQL(statements=[],scripts=[]){
 const p=spawnSync(python,['-c',sqlRunner],{input:JSON.stringify({db:dbPath,statements,scripts}),encoding:'utf8'});
 if(p.status!==0)throw new Error(p.stdout||p.stderr);return JSON.parse(p.stdout);
}
const db={prepare(sql){return {sql,params:[],bind(...params){return {...this,params};},async first(){return runSQL([this])[0].results[0]||null;},async all(){return runSQL([this])[0];},async run(){return runSQL([this])[0];}};},async batch(statements){return runSQL(statements);}};
try{
 const output=join(scratch,'contracts.mjs');
 await build({stdin:{contents:`export {writeCase} from './lib/case-authoring.ts';export {executionInput,exportCase,requireCaseCapabilities} from './lib/execution-contract.ts';export {sandboxScenario} from './lib/sandbox-contract.ts';export {decodeCase} from './lib/case-record.ts';`,resolveDir:root,loader:'ts'},bundle:true,platform:'node',format:'esm',outfile:output});
 const {writeCase,executionInput,exportCase,requireCaseCapabilities,sandboxScenario,decodeCase}=await import(pathToFileURL(output));
 const fixtures=JSON.parse(readFileSync(resolve(root,'../checks/fixtures/capability-contracts.json'),'utf8'));
 for(const fixture of fixtures){const result=(fixture.kind==='execution'?executionInput:sandboxScenario).safeParse(fixture.input);assert.equal(result.success,fixture.valid,fixture.name);if(result.success)assert.deepEqual(result.data,fixture.normalized,fixture.name+' normalized Python/TS contract');}
 runSQL([],readdirSync(join(root,'drizzle')).filter(f=>f.endsWith('.sql')).sort().map(f=>readFileSync(join(root,'drizzle',f),'utf8')));
 const workspace=randomUUID(),owner='synthetic-owner';runSQL([{sql:'INSERT INTO workspaces (id,owner,name,created) VALUES (?,?,?,?)',params:[workspace,owner,'Synthetic','now']}]);
 const definition={workspace_id:workspace,title:'Synthetic observation',platform:'Android',suite:'Synthetic',goal:'Observe the synthetic screen',steps:'Observe',preconditions:'Synthetic inputs only',expected:'Synthetic screen visible'};
 const peer={contract_versions:[1,2],features:['target_gestures','media_metadata','network_contract_v2','request_assertions']};
 const request=randomUUID();const item={request_id:request,case:definition};
 assert.equal((await writeCase(db,owner,workspace,item,peer,true)).valid,true);
 assert.equal(runSQL([{sql:'SELECT count(*) AS n FROM test_cases'}])[0].results[0].n,0);
 const first=await writeCase(db,owner,workspace,item,peer);const duplicate=await writeCase(db,owner,workspace,item,peer);assert.equal(first.case.id,duplicate.case.id);assert.equal(duplicate.duplicate,true);
 await assert.rejects(writeCase(db,owner,workspace,{...item,case:{...definition,title:'Different payload'}},peer),/different definition/);
 await assert.rejects(writeCase(db,'other-owner',workspace,{request_id:randomUUID(),case:definition},peer),/Workspace not found/);
 const execution=fixtures.find(f=>f.name==='target swipe').normalized;
 const update={request_id:randomUUID(),id:first.case.id,expected_revision:1,case:{...definition,execution}};
 const second=await writeCase(db,owner,workspace,update,peer);assert.equal(second.case.revision,2);
 const row=runSQL([{sql:'SELECT * FROM test_cases WHERE id=?',params:[first.case.id]}])[0].results[0];assert.deepEqual(decodeCase(row).execution,execution);
 assert.equal(exportCase(second.case).format,'scout-case-v2');assert.equal(exportCase(first.case).id,first.case.id);
 assert.throws(()=>requireCaseCapabilities(second.case,{contract_versions:[1],features:[]}),/handshake/);
 await assert.rejects(writeCase(db,owner,workspace,{...update,request_id:randomUUID()},peer),/revision conflict/);
 await assert.rejects(writeCase(db,owner,workspace,{request_id:randomUUID(),id:first.case.id,expected_revision:2,case:definition},peer),/silently dropped/);
 const previous=runSQL([{sql:'SELECT snapshot_json FROM case_revisions WHERE case_id=? AND revision=1',params:[first.case.id]}])[0].results[0];assert.equal(JSON.parse(previous.snapshot_json).execution,undefined);
 const raceItems=[0,1].map(i=>({request_id:randomUUID(),id:first.case.id,expected_revision:2,case:{...definition,execution,title:'Concurrent '+i}}));
 const race=await Promise.allSettled(raceItems.map(i=>writeCase(db,owner,workspace,i,peer)));assert.equal(race.filter(r=>r.status==='fulfilled').length,1);assert.equal(race.filter(r=>r.status==='rejected').length,1);
 const same={request_id:randomUUID(),case:definition};const [a,b]=await Promise.all([writeCase(db,owner,workspace,same,peer),writeCase(db,owner,workspace,same,peer)]);assert.equal(a.case.id,b.case.id);
 console.log(`Passed ${fixtures.length} shared contract fixtures and SQLite migration/authoring checks (dry-run, ownership, idempotency, revisions, concurrent writes, retained snapshots, legacy/new exports).`);
}finally{rmSync(scratch,{recursive:true,force:true});}
