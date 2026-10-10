import fs from 'node:fs';
import { runCheck } from './run.mjs';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const state = 'harness/.state';
const fail = message => { throw new Error(message); };
const text = value => typeof value === 'string' && value.trim().length > 0;
function git(args, optional = false) {
  const result = spawnSync('git', args, { cwd: root, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 });
  if (result.error || result.status !== 0) {
    if (optional) return '';
    fail('Git 저장소를 확인하세요. / Check the Git repository.');
  }
  return result.stdout;
}
// Refuse symlinks for harness inputs and output paths, including parent folders.
function local(relative) {
  if (!text(relative) || path.isAbsolute(relative) || relative.split(/[\\/]/).some(p => p === '..' || p === '.git')) fail('Invalid repository path.');
  let current = root;
  for (const part of relative.split(/[\\/]/)) {
    current = path.join(current, part);
    if (fs.existsSync(current) || (() => { try { return fs.lstatSync(current).isSymbolicLink(); } catch { return false; } })()) {
      if (fs.lstatSync(current).isSymbolicLink()) fail(`Symlink is not allowed: ${relative}`);
    }
  }
  return current;
}
function read(relative) {
  try { return JSON.parse(fs.readFileSync(local(relative), 'utf8')); }
  catch (error) { fail(`설정/기록을 읽을 수 없습니다 / Cannot read ${relative}: ${error.message}`); }
}
function write(relative, value) {
  const dest = local(relative);
  const temp = `${dest}.${crypto.randomUUID()}.tmp`;
  try {
    fs.writeFileSync(temp, JSON.stringify(value, null, 2) + '\n', { flag: 'wx', mode: 0o600 });
    fs.renameSync(temp, dest);
  } finally { if (fs.existsSync(temp)) fs.unlinkSync(temp); }
}
function taskPath(id) {
  if (!/^[a-z0-9][a-z0-9-]{0,63}$/.test(id || '')) fail('작업 ID는 영문 소문자·숫자·하이픈으로 입력하세요 / Invalid task ID.');
  return `${state}/${id}.json`;
}
function loadTask(id) {
  const task = read(taskPath(id));
  if (task.schemaVersion !== 1 || task.id !== id || !text(task.title) || !['small', 'big'].includes(task.size) ||
      !Array.isArray(task.plan) || !task.plan.every(text)) fail('Invalid task record.');
  return task;
}
function configuration() {
  const config = read('harness/config/project.json');
  if (config.schemaVersion !== 1 || !Array.isArray(config.checks)) fail('Invalid project configuration.');
  const names = new Set();
  for (const check of config.checks) {
    if (!check || !text(check.name) || names.has(check.name) || !Array.isArray(check.command) ||
        !check.command.length || !check.command.every(text) ||
        !Number.isInteger(check.timeoutSeconds) || check.timeoutSeconds < 1 || check.timeoutSeconds > 3600) fail('Invalid check: use a unique name, command array and timeoutSeconds (1–3600).');
    names.add(check.name);
  }
  return config;
}
function blockers(task, config) {
  const issues = [];
  if (!config.checks.length) issues.push('검증 명령이 없습니다. 에이전트에게 “프로젝트 검증 명령 설정해줘”라고 요청하세요. / Configure project checks.');
  if (task.size === 'big' && !task.plan.length) issues.push('큰 변경은 계획 문서가 필요합니다. / Big changes require --plan <file>.');
  for (const document of task.plan) {
    const filename = local(document);
    if (!fs.existsSync(filename) || !fs.statSync(filename).isFile() || !fs.readFileSync(filename, 'utf8').trim()) issues.push(`계획 문서를 작성하세요 / Missing or empty plan: ${document}`);
  }
  if (!fs.existsSync(local('scripts/check-conventions.sh'))) issues.push('Missing scripts/check-conventions.sh; reinstall praxis.');
  return issues;
}
function snapshot(task) {
  const digest = crypto.createHash('sha256');
  digest.update(JSON.stringify({ id: task.id, title: task.title, size: task.size, plan: task.plan }));
  digest.update(git(['rev-parse', '--verify', 'HEAD'], true));
  // Include index and working tree: a staging change can change the gate outcome.
  digest.update(git(['ls-files', '--stage', '-z']));
  const files = [...new Set(git(['ls-files', '--cached', '--others', '--exclude-standard', '-z']).split('\0').filter(Boolean))].sort();
  for (const name of files) {
    if (name.startsWith(`${state}/`)) continue;
    const filename = path.join(root, name);
    digest.update(JSON.stringify(name));
    let stat;
    try { stat = fs.lstatSync(filename); } catch (error) { if (error.code === 'ENOENT') { digest.update('deleted'); continue; } throw error; }
    digest.update(String(stat.mode));
    if (stat.isSymbolicLink()) digest.update(fs.readlinkSync(filename));
    else if (stat.isFile()) digest.update(fs.readFileSync(filename));
    else fail(`Cannot fingerprint ${name}; submodules/directories need a separate validation workflow.`);
  }
  // These may be ignored by the target repo; still include their current contents.
  for (const name of ['harness/config/profile.json', 'harness/config/project.json', 'scripts/check-conventions.sh', ...task.plan]) {
    digest.update(name); digest.update(fs.readFileSync(local(name)));
  }
  return digest.digest('hex');
}
async function execute(check) {
  console.log(`검사 중 / Running: ${check.name}`);
  const result = await runCheck({ name: check.name, command: check.command[0], args: check.command.slice(1), cwd: root }, check.timeoutSeconds * 1000);
  return { ...result, command: check.command, passed: result.exitCode === 0 && !result.timedOut && !result.spawnError && !result.interrupted };
}
const help = `사용법 / Usage (Node.js 18+):
  node harness/bin/praxis.mjs task init <id> --title "작업 설명" [--size small|big] [--plan docs/plan.md]
  node harness/bin/praxis.mjs task check <id>
  node harness/bin/praxis.mjs task validate <id>
  node harness/bin/praxis.mjs task status <id>

기본 크기는 big입니다. 작은 수정만 --size small을 사용하세요.
에이전트에게 “작업 시작해줘”, “검증해줘”, “현재 상태 알려줘”라고 요청할 수 있습니다.
CI는 기본으로 꺼져 있습니다. / CI is off by default.`;

export async function main(args) {
  if (!args.length || args[0] === '--help' || args[0] === 'help') { console.log(help); return 0; }
  const [group, command, id, ...options] = args;
  if (group !== 'task' || !['init', 'check', 'validate', 'status'].includes(command)) fail(help);
  const filename = taskPath(id);
  if (fs.realpathSync(git(['rev-parse', '--show-toplevel']).trim()) !== fs.realpathSync(root)) fail('Install harness at the Git repository root.');
  if (command !== 'init' && options.length) fail('Unexpected options.');
  if (command === 'status') {
    const task = loadTask(id); const config = configuration(); const issues = blockers(task, config);
    let status = '미검증 / not validated';
    if (task.validation) {
      status = '실패 / failed';
      if (task.validation.passed) status = !issues.length && task.validation.fingerprint === snapshot(task) ? '통과 / passed' : '재검증 필요 / stale';
    }
    console.log(`${task.id}: ${task.title}\n상태 / Status: ${status}`);
    issues.forEach(issue => console.log(`- ${issue}`));
    console.log(`다음 / Next: node harness/bin/praxis.mjs task ${issues.length ? 'check' : 'validate'} ${id}`);
    return status === '통과 / passed' ? 0 : 1;
  }
  fs.mkdirSync(local(state), { recursive: true });
  const lock = local(`${state}/lock`);
  try { fs.mkdirSync(lock); } catch { fail('다른 하네스 작업이 실행 중입니다. / Harness is locked. If a process crashed, confirm it stopped before removing harness/.state/lock.'); }
  try {
    if (command === 'init') {
      const task = { schemaVersion: 1, id, title: '', size: 'big', plan: [], createdAt: new Date().toISOString() };
      const seen = new Set();
      for (let i = 0; i < options.length; i += 2) {
        const key = options[i], value = options[i + 1];
        if (!['--title', '--size', '--plan'].includes(key) || !text(value) || value.startsWith('--') || (key !== '--plan' && seen.has(key))) fail('Invalid init options.');
        seen.add(key);
        if (key === '--plan') { local(value); task.plan.push(value); }
        else task[key.slice(2)] = value;
      }
      if (!text(task.title) || !['small', 'big'].includes(task.size)) fail('Specify --title and --size small|big.');
      if (fs.existsSync(local(filename))) fail('이미 존재하는 작업입니다 / Task already exists; choose another ID.');
      write(filename, task);
      console.log(`작업 생성 / Created: ${id}\n다음 / Next: node harness/bin/praxis.mjs task check ${id}`); return 0;
    }
    const task = loadTask(id), config = configuration(), issues = blockers(task, config);
    if (issues.length) {
      if (command === 'validate') { task.validation = { passed: false, checkedAt: new Date().toISOString(), issues }; write(filename, task); }
      issues.forEach(issue => console.error(`- ${issue}`)); return 1;
    }
    if (command === 'check') { console.log('시작 조건 충족 / Preconditions met. 문서 내용의 타당성은 별도 검토가 필요합니다.'); return 0; }
    const before = snapshot(task);
    // Persist invalidation BEFORE executing commands, so interruption cannot retain a prior pass.
    task.validation = { passed: false, checkedAt: new Date().toISOString(), fingerprint: before, results: [] };
    write(filename, task);
    const checks = [{ name: 'praxis gate (staged rules)', command: ['bash', 'scripts/check-conventions.sh'], timeoutSeconds: 120 }, ...config.checks];
    for (const check of checks) {
      const result = await execute(check); task.validation.results.push(result); write(filename, task);
      if (!result.passed) break;
    }
    const after = snapshot(task);
    task.validation.passed = task.validation.results.length === checks.length && task.validation.results.every(r => r.passed) && before === after;
    task.validation.fingerprint = after;
    task.validation.changedDuringChecks = before !== after;
    write(filename, task);
    console.log(task.validation.passed ? '검증 통과 / Validation passed.' : '검증 실패 / Validation failed. 검사 결과와 파일 변경을 확인하세요.');
    return task.validation.passed ? 0 : 1;
  } finally { fs.rmdirSync(lock); }
}
