import { z } from 'zod';
import { context, failure, jsonBody } from '@/lib/server';
import { writeCase } from '@/lib/case-authoring';
const input=z.object({workspace_id:z.string().uuid(),items:z.array(z.unknown()).min(1).max(100),dry_run:z.boolean().default(false),runner_capabilities:z.unknown().optional()}).strict();
export async function POST(request:Request){try{
 const {db,owner}=await context(request,true);const raw=await jsonBody(request);if(JSON.stringify(raw).length>1000000)return Response.json({error:'Import exceeds the 1 MB limit.'},{status:413});const packet=input.parse(raw);
 const results=[];
 for(let index=0;index<packet.items.length;index++){
  try{results.push({index,...await writeCase(db,owner,packet.workspace_id,packet.items[index],packet.runner_capabilities,packet.dry_run)});}
  catch(error){results.push({index,error:error instanceof Error?error.message:'Validation failed.'});}
 }
 return Response.json({dry_run:packet.dry_run,results,execution_started:false});
}catch(error){return failure(error);}}
