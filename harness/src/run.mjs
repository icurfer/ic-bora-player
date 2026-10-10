// Execute a bounded check and collect its outcome without persisting output logs.
import { spawn } from 'node:child_process';
export async function runCheck(check, timeout = 600000) {
  const began = Date.now();
  return new Promise(resolve => {
    let timedOut = false, spawnError = false, interrupted = false, escalation;
    const child = spawn(check.command, check.args, { cwd: check.cwd, stdio: 'inherit', detached: process.platform !== 'win32', shell: false });
    const killGroup = signal => { if (child.pid) { try { if (process.platform === 'win32') child.kill(signal); else process.kill(-child.pid, signal); } catch {} } };
    const interrupt = () => { interrupted = true; killGroup('SIGKILL'); };
    process.once('SIGINT', interrupt); process.once('SIGTERM', interrupt);
    const timer = setTimeout(() => {
      timedOut = true; killGroup('SIGTERM');
      escalation = setTimeout(() => killGroup('SIGKILL'), 1000);
    }, timeout);
    child.on('error', () => { spawnError = true; });
    child.on('close', code => {
      clearTimeout(timer); clearTimeout(escalation);
      process.removeListener('SIGINT', interrupt); process.removeListener('SIGTERM', interrupt);
      // Clean up any surviving children on abnormal exit as well.
      if (timedOut || spawnError || interrupted || code !== 0) killGroup('SIGKILL');
      resolve({ name: check.name, exitCode: code, timedOut, spawnError, interrupted, durationMs: Date.now() - began });
    });
  });
}
