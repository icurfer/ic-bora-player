import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
test('input guard rejects unstaged repairs and untracked files without changing the index',t=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'index-check-'));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const git=(...args)=>spawnSync('git',args,{cwd:root,encoding:'utf8'});
 git('init','-q');fs.mkdirSync(path.join(root,'src'));fs.writeFileSync(path.join(root,'src/app'),'staged');git('add','src');
 const check=()=>spawnSync('bash',[new URL('../../scripts/check-index-clean.sh',import.meta.url).pathname,'src'],{cwd:root}).status;
 assert.equal(check(),0);fs.writeFileSync(path.join(root,'src/app'),'working');assert.equal(check(),1);
 assert.equal(git('show',':src/app').stdout,'staged');git('add','src');assert.equal(check(),0);
 fs.writeFileSync(path.join(root,'src/new'),'untracked');assert.equal(check(),1);
 fs.rmSync(path.join(root,'src/new'));fs.rmSync(path.join(root,'src/app'));assert.equal(check(),1);
});
