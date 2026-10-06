import { createHash } from 'node:crypto';
import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';
export function sourceIdentity(root){
 const files=[];
 function visit(folder){for(const entry of readdirSync(folder,{withFileTypes:true})){const path=join(folder,entry.name);if(entry.isDirectory())visit(path);else if(/\.(?:ts|tsx|sql)$/.test(entry.name))files.push(path);}}
 for(const folder of ['app','lib','components','db','drizzle'])visit(join(root,folder));
 const digest=createHash('sha256');for(const file of files.sort()){digest.update(relative(root,file));digest.update(readFileSync(file));}
 return digest.digest('hex');
}
