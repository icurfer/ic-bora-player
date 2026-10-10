import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
const source = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
function fixture(t) {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'praxis-harness-'));
  t.after(() => fs.rmSync(base, { recursive: true, force: true }));
  const root = path.join(base, 'repo'); fs.mkdirSync(root);
  for (const name of ['harness', 'scripts', '.githooks', '.gitignore', 'AGENTS.md', 'CLAUDE.md', 'docs/RELEASING.md']) {
    fs.cpSync(path.join(source, name), path.join(root, name), { recursive: true, filter: p => !p.includes(`${path.sep}.state`) });
  }
  function run(cmd, args, expected = 0) {
    const result = spawnSync(cmd, args, { cwd: root, encoding: 'utf8' });
    assert.equal(result.status, expected, result.stdout + result.stderr);
    return result.stdout + result.stderr;
  }
  const cli = (args, expected = 0) => run(process.execPath, ['harness/bin/praxis.mjs', ...args], expected);
  const git = (...args) => run('git', args);
  git('init', '-q'); git('config', 'user.name', 'Harness Test'); git('config', 'user.email', 'test@example.invalid');
  fs.writeFileSync(path.join(root, 'harness/config/profile.json'), JSON.stringify({ schemaVersion: 1, profile: null }));
  cli(['profile', 'select', 'development']);
  fs.writeFileSync(path.join(root, 'version'), '0.0.0');
  git('add', '.'); git('-c', 'core.hooksPath=/dev/null', 'commit', '-qm', 'fixture');
  const config = checks => fs.writeFileSync(path.join(root, 'harness/config/project.json'), JSON.stringify({ schemaVersion: 1, checks }));
  config([]);
  const check = code => ({ name: 'test', command: [process.execPath, '-e', code], timeoutSeconds: 5 });
  const init = (id = 'sample', extra = ['--size', 'small']) => cli(['task', 'init', id, '--title', 'Sample task', ...extra]);
  return { root, base, run, cli, git, config, check, init };
}

test('unconfigured checks block; pass becomes stale after working tree/index/config changes', t => {
  const f = fixture(t); f.init();
  assert.match(f.cli(['task', 'check', 'sample'], 1), /Configure project checks/);
  f.config([f.check('process.exit(0)')]);
  f.cli(['task', 'validate', 'sample']);
  assert.match(f.cli(['task', 'status', 'sample']), /Status: 통과 \/ passed/);
  fs.writeFileSync(path.join(f.root, 'notes.txt'), 'new');
  assert.match(f.cli(['task', 'status', 'sample'], 1), /stale/);
  f.cli(['task', 'validate', 'sample']);
  f.git('add', 'notes.txt');
  assert.match(f.cli(['task', 'status', 'sample'], 1), /stale/);
  f.cli(['task', 'validate', 'sample']);
  f.config([f.check('process.exit(1)')]);
  assert.match(f.cli(['task', 'status', 'sample'], 1), /stale/);
  f.cli(['task', 'validate', 'sample'], 1);
  assert.match(f.cli(['task', 'status', 'sample'], 1), /failed/);
});

test('big tasks need a nonempty plan; records and path boundaries are protected', t => {
  const f = fixture(t); f.config([f.check('process.exit(0)')]); f.init('big', []);
  f.cli(['task', 'check', 'big'], 1);
  f.init('planned', ['--plan', 'plan.md']); f.cli(['task', 'check', 'planned'], 1);
  fs.writeFileSync(path.join(f.root, 'plan.md'), ''); f.cli(['task', 'check', 'planned'], 1);
  fs.writeFileSync(path.join(f.root, 'plan.md'), 'A real plan'); f.cli(['task', 'check', 'planned']);
  const before = fs.readFileSync(path.join(f.root, 'harness/.state/planned.json'));
  f.cli(['task', 'init', 'planned', '--title', 'Overwrite'], 1);
  assert.deepEqual(fs.readFileSync(path.join(f.root, 'harness/.state/planned.json')), before);
  f.cli(['task', 'init', '../escape', '--title', 'Escape'], 1);
  f.cli(['task', 'init', 'escape', '--title', 'Escape', '--plan', '../outside'], 1);
  f.cli(['task', 'status', 'planned', '--unknown'], 1);
  fs.writeFileSync(path.join(f.root, 'harness/config/project.json'), '{'); f.cli(['task', 'check', 'planned'], 1);
});

test('timeouts, missing executables and mutations fail; a prior pass is invalidated', t => {
  const f = fixture(t); f.init(); f.config([f.check('process.exit(0)')]); f.cli(['task', 'validate', 'sample']);
  f.config([{ name: 'timeout', command: [process.execPath, '-e', 'setInterval(() => {}, 1000)'], timeoutSeconds: 1 }]);
  f.cli(['task', 'validate', 'sample'], 1);
  assert.match(f.cli(['task', 'status', 'sample'], 1), /failed/);
  f.config([{ name: 'missing', command: ['praxis-no-such-executable'], timeoutSeconds: 1 }]);
  f.cli(['task', 'validate', 'sample'], 1);
  f.config([f.check("require('fs').writeFileSync('generated.txt', 'changed')")]);
  f.cli(['task', 'validate', 'sample'], 1);
  assert.equal(JSON.parse(fs.readFileSync(path.join(f.root, 'harness/.state/sample.json'))).validation.changedDuringChecks, true);
});

test('Bora hook permits ordinary code without bump but rejects invalid staged versions', t => {
  const f = fixture(t); f.run('bash', ['scripts/install-hooks.sh']);
  fs.mkdirSync(path.join(f.root, 'src')); fs.writeFileSync(path.join(f.root, 'src/sample.txt'), 'code');
  f.git('add', 'src/sample.txt');
  f.init(); f.config([f.check('process.exit(0)')]);
  f.cli(['task', 'validate', 'sample']); f.git('commit', '-qm', 'code without bump');
  assert.match(f.cli(['task', 'status', 'sample'], 1), /stale/);
  fs.writeFileSync(path.join(f.root, 'version'), 'invalid'); f.git('add', 'version');
  f.cli(['task', 'validate', 'sample'], 1);
  f.run('git', ['commit', '-qm', 'must block'], 1);
});

test('locks and symlinked state prevent writes outside the repo', t => {
  const f = fixture(t); f.init();
  fs.mkdirSync(path.join(f.root, 'harness/.state/lock')); f.cli(['task', 'init', 'other', '--title', 'Other'], 1);
  fs.rmSync(path.join(f.root, 'harness/.state'), { recursive: true });
  const outside = path.join(f.base, 'outside'); fs.mkdirSync(outside);
  fs.symlinkSync(outside, path.join(f.root, 'harness/.state'), 'junction');
  f.cli(['task', 'init', 'other', '--title', 'Other'], 1);
  assert.deepEqual(fs.readdirSync(outside), []);
});

test('invalid staged version cannot hide behind a corrected working file', t => {
  const f = fixture(t);
  fs.writeFileSync(path.join(f.root, 'version'), '1.0.0'); f.git('add','version'); f.git('commit','-qm','baseline');
  fs.writeFileSync(path.join(f.root, 'version'), 'invalid'); f.git('add','version');
  fs.writeFileSync(path.join(f.root, 'version'), '1.0.1');
  assert.match(f.run('bash',['scripts/check-conventions.sh'],1), /version|버전/);
  f.git('add','version'); f.run('bash',['scripts/check-conventions.sh']);
});

test('unvalidated status is nonzero', t => {
  const f = fixture(t); f.init(); f.config([f.check('process.exit(0)')]);
  assert.match(f.cli(['task','status','sample'],1), /not validated/);
});

test('CI staging supports both initial empty tree and existing commit baselines', {skip: !fs.existsSync(path.join(source,'.github/workflows/praxis-gate.yml'))}, t => {
  const workflow=fs.readFileSync(path.join(source,'.github/workflows/praxis-gate.yml'),'utf8');
  const block=workflow.split('- name: Stage the whole change set\n')[1].split('\n      - name:')[0];
  const script=block.split('run: |\n')[1].split('\n').map(line=>line.replace(/^          /,'')).join('\n');
  for(const initial of [false,true]) {
    const f=fixture(t);
    const base=initial ? f.git('hash-object','-t','tree','/dev/null').trim() : f.git('rev-parse','HEAD').trim();
    fs.writeFileSync(path.join(f.root,'version'),'0.0.1');f.git('add','version');f.git('commit','-qm','change');
    f.run('bash',['-c',script.replace('${{ steps.base.outputs.sha }}',base)]);
    assert.match(f.git('diff','--cached','--name-only'),/version/);
    f.run('bash',['scripts/check-conventions.sh']);
  }
});
