import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const choices = ['development', 'infrastructure'];
const selectionHelp = `하네스 종류를 선택하세요 / Select a harness profile:
  development     개발용: 코드 작업과 테스트·빌드 검증
  infrastructure  인프라용: 참고 프로젝트 연동 준비 (운영 실행 미구현)

node harness/bin/praxis.mjs profile select development
node harness/bin/praxis.mjs profile select infrastructure
node harness/bin/praxis.mjs profile status

에이전트에게 “하네스 적용해줘”라고 요청하면 먼저 종류를 선택합니다.
CI는 두 종류 모두 기본으로 꺼져 있습니다. / CI remains opt-in.`;

function profileFile() {
  let current = root;
  for (const segment of ['harness', 'config', 'profile.json']) {
    current = path.join(current, segment);
    // lstat also catches dangling links; absent selection files must fail closed.
    if (fs.lstatSync(current).isSymbolicLink()) throw new Error('Symlink is not allowed for profile selection.');
  }
  return current;
}
function readProfile() {
  const value = JSON.parse(fs.readFileSync(profileFile(), 'utf8'));
  if (!value || value.schemaVersion !== 1 || !(value.profile === null || choices.includes(value.profile))) {
    throw new Error('Invalid harness/config/profile.json; choose development or infrastructure.');
  }
  return value;
}
function report(profile) {
  if (profile === null) { console.log(selectionHelp); return 1; }
  if (profile === 'infrastructure') {
    console.log('인프라용 선택됨 / infrastructure: pending implementation.\n참고 프로젝트를 harness/config/infrastructure.json에 기록하세요.\n다음 단계: harness/profiles/infrastructure/README.md — 운영 명령은 아직 실행할 수 없습니다.');
    return 1;
  }
  console.log('개발용 선택됨 / development selected.\n작업별 검증은 별도입니다. / Task validation is separate.\nNext: node harness/bin/praxis.mjs task --help');
  return 0;
}
function select(profile) {
  if (!choices.includes(profile)) throw new Error(selectionHelp);
  const filename = profileFile();
  const lock = `${filename}.lock`;
  const fd = fs.openSync(lock, 'wx', 0o600);
  fs.closeSync(fd);
  try {
    const previous = readProfile();
    if (previous.profile !== null && previous.profile !== profile) {
      throw new Error('이미 종류가 선택되어 있습니다. / Profile already selected; changing types requires a reviewed migration. Existing records were preserved.');
    }
    if (previous.profile === null) {
      fs.writeFileSync(lock, JSON.stringify({ ...previous, profile }, null, 2) + '\n');
      fs.renameSync(lock, filename);
    }
  } finally { if (fs.existsSync(lock)) fs.unlinkSync(lock); }
  report(profile);
  return 0; // Selection succeeds; infrastructure readiness/status still fails.
}

export async function main(args) {
  if (args[0] === 'profile') {
    if (args[1] === 'select' && args.length === 3) return select(args[2]);
    if (args[1] === 'status' && args.length === 2) return report(readProfile().profile);
    throw new Error(selectionHelp);
  }
  if (!args.length || ['--help', 'help'].includes(args[0])) {
    console.log(selectionHelp);
    console.log('\nDevelopment tasks: task init / check / validate / status. After selecting development, use task --help.');
    return 0;
  }
  const profile = readProfile().profile;
  if (profile !== 'development') return report(profile);
  // Load only the selected implementation. Infrastructure never falls back here.
  const development = await import('./development.mjs');
  if (args.length === 2 && args[0] === 'task' && args[1] === '--help') return development.main(['--help']);
  return development.main(args);
}
