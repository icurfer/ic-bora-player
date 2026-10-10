import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { runCheck } from '../src/run.mjs';
test('timeout terminates descendants in the started POSIX process group', {skip:process.platform==='win32'}, async t=>{
 const cwd=fs.mkdtempSync(path.join(os.tmpdir(),'praxis-runner-'));t.after(()=>fs.rmSync(cwd,{recursive:true,force:true}));
 const child="setTimeout(()=>require('fs').writeFileSync('survived','bad'),600);setInterval(()=>{},1000)";
 const code=`require('child_process').spawn(process.execPath,['-e',${JSON.stringify(child)}],{stdio:'ignore'});setInterval(()=>{},1000)`;
 const r=await runCheck({name:'descendants',command:process.execPath,args:['-e',code],cwd},200);
 assert.equal(r.timedOut,true);
 await new Promise(resolve=>setTimeout(resolve,800));
 assert.equal(fs.existsSync(path.join(cwd,'survived')),false);
});
