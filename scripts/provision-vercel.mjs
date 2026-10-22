#!/usr/bin/env node
// One-time local setup for a generated CLI project's docs-only CI deployment.
// Credentials never appear on the command line, in logs, or in project files.
import { spawnSync } from 'node:child_process';
import { readFileSync, statSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const keychainService = 'amxv vercel bootstrap token';
const templateNames = new Set(['amxv/go-cli-template', 'amxv/rust-cli-template']);

export function readLinkedProject(projectRoot) {
  const location = path.join(projectRoot, 'docs', '.vercel', 'project.json');
  let data;
  try {
    data = JSON.parse(readFileSync(location, 'utf8'));
  } catch {
    throw new Error('Link docs/ to its real Vercel project first: cd docs && vercel link --yes.');
  }
  if (typeof data.projectId !== 'string' || !data.projectId.startsWith('prj_') ||
      typeof data.orgId !== 'string' || !data.orgId.trim()) {
    throw new Error('docs/.vercel/project.json must include a valid projectId and orgId.');
  }
  return { projectId: data.projectId, orgId: data.orgId };
}

export function createTokenRequest(repo, linked, candidate) {
  const url = new URL('https://api.vercel.com/v3/user/tokens');
  if (linked.orgId.startsWith('team_')) url.searchParams.set('teamId', linked.orgId);
  return {
    url,
    options: {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + candidate,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        name: ('docs-' + repo.replace('/', '-') + '-' + linked.projectId.slice(-8)).slice(0, 100),
        projectId: linked.projectId
      })
    }
  };
}

export async function mintProjectToken(repo, linked, candidate, request = fetch) {
  const prepared = createTokenRequest(repo, linked, candidate);
  const result = await request(prepared.url, {
    ...prepared.options,
    signal: AbortSignal.timeout(20_000)
  });
  if (!result.ok) {
    const error = new Error('Vercel token creation returned HTTP ' + result.status +
      '. Check that the provisioning credential has full-account token creation access.');
    error.status = result.status;
    throw error;
  }
  let payload;
  try { payload = await result.json(); }
  catch { throw new Error('Vercel returned an invalid token response.'); }
  if (typeof payload?.bearerToken !== 'string' || payload.bearerToken.length < 8) {
    throw new Error('Vercel did not return a usable project token.');
  }
  return payload.bearerToken;
}

function execute(command, args, { input } = {}) {
  const env = { ...process.env };
  // Provisioning credentials must not be inherited by spawned CLI processes.
  delete env.VERCEL_BOOTSTRAP_TOKEN;
  const result = spawnSync(command, args, {
    cwd: root,
    env,
    encoding: 'utf8',
    input,
    timeout: 30_000,
    maxBuffer: 1024 * 1024
  });
  if (result.status !== 0) {
    throw new Error(command + ' ' + args.slice(0, 2).join(' ') +
      ' failed (exit ' + (result.status ?? 'unknown') + ').');
  }
  return result.stdout.trim();
}

export function repositoryName(command = execute) {
  const name = command('gh', ['repo', 'view', '--json', 'nameWithOwner', '-q', '.nameWithOwner']);
  if (!/^[\w.-]+\/[\w.-]+$/.test(name)) {
    throw new Error('Cannot identify the GitHub repository. Configure git origin and gh authentication.');
  }
  if (templateNames.has(name.toLowerCase())) {
    throw new Error('Refusing to provision the source template. Bootstrap a new GitHub repository first.');
  }
  return name;
}

function githubNames(repo, command = execute) {
  const entries = JSON.parse(command('gh', ['secret', 'list', '--repo', repo, '--json', 'name']));
  if (!Array.isArray(entries)) throw new Error('Cannot inspect GitHub Actions secrets.');
  return new Set(entries.map((entry) => entry.name));
}

function readCliCredential() {
  const candidates = [
    path.join(os.homedir(), 'Library', 'Application Support', 'com.vercel.cli', 'auth.json'),
    path.join(os.homedir(), '.local', 'share', 'com.vercel.cli', 'auth.json'),
    path.join(os.homedir(), '.vercel', 'auth.json')
  ];
  for (const file of candidates) {
    try {
      const mode = statSync(file).mode & 0o777;
      if (mode & 0o077) continue; // Do not trust broadly readable auth files.
      const token = JSON.parse(readFileSync(file, 'utf8')).token;
      if (typeof token === 'string' && token.length > 8) return token;
    } catch { /* Search the next supported location. */ }
  }
  return null;
}

function readKeychainCredential() {
  if (process.platform !== 'darwin') return null;
  const result = spawnSync('security', [
    'find-generic-password', '-s', keychainService, '-w'
  ], { encoding: 'utf8', timeout: 10_000 });
  return result.status === 0 && result.stdout.trim() ? result.stdout.trim() : null;
}

export async function obtainProjectToken(repo, linked, options = {}) {
  const mint = options.mint ?? mintProjectToken;
  const explicitlySupplied = process.env.VERCEL_BOOTSTRAP_TOKEN?.trim();
  if (explicitlySupplied) {
    return mint(repo, linked, explicitlySupplied);
  }
  const cli = options.cliToken === undefined ? readCliCredential() : options.cliToken;
  const keychain = options.keychainToken === undefined ? readKeychainCredential() : options.keychainToken;
  if (cli) {
    try { return await mint(repo, linked, cli); }
    catch (error) {
      if (![401, 403].includes(error.status)) throw error;
      if (!keychain || keychain === cli) {
        throw new Error('Existing Vercel CLI login cannot mint project tokens (HTTP ' +
          error.status + '). Store a classic full-account token in macOS Keychain under "' +
          keychainService + '", then retry.');
      }
    }
  }
  if (keychain) return mint(repo, linked, keychain);
  throw new Error('No usable provisioning credential found. Log in with Vercel CLI, or ' +
    'store a classic Full Account token in macOS Keychain under "' + keychainService + '".');
}

export async function provision({ args = process.argv.slice(2), command = execute,
  mint, projectRoot = root, log = console.log } = {}) {
  if (args.includes('--help') || args.includes('-h')) {
    log('Usage: node scripts/provision-vercel.mjs [--check|--rotate]');
    log('Link docs/ with vercel link first. Uses existing CLI auth or local Keychain.');
    return;
  }
  if (args.some((arg) => !['--check', '--rotate'].includes(arg)) ||
      (args.includes('--check') && args.includes('--rotate'))) {
    throw new Error('Usage: provision-vercel.mjs [--check|--rotate]');
  }
  const repo = repositoryName(command);
  const linked = readLinkedProject(projectRoot);
  const exists = githubNames(repo, command).has('VERCEL_TOKEN');
  if (args.includes('--check')) {
    log('GitHub repository: ' + repo);
    log('Linked Vercel project: ' + linked.projectId);
    log('Deployment secret: ' + (exists ? 'present' : 'not configured'));
    return;
  }
  // Set IDs through GitHub *variables*, not GitHub secrets. They are not credentials.
  command('gh', ['variable', 'set', 'VERCEL_ORG_ID', '--repo', repo], { input: linked.orgId + '\n' });
  command('gh', ['variable', 'set', 'VERCEL_PROJECT_ID', '--repo', repo],
    { input: linked.projectId + '\n' });
  if (exists && !args.includes('--rotate')) {
    log('Deployment token already exists for ' + repo + '; keeping it. ' +
      'GitHub Actions project variables are synchronized. Use --rotate to replace the token.');
    return;
  }
  const token = await (mint ?? obtainProjectToken)(repo, linked);
  try {
    // The token is passed on stdin only, never in argv or stdout.
    command('gh', ['secret', 'set', 'VERCEL_TOKEN', '--repo', repo], { input: token + '\n' });
  } catch {
    throw new Error('Could not store the new Vercel token in GitHub Actions. ' +
      'Revoke the unused minted token from Vercel account settings and retry.');
  }
  log('Provisioned a project-scoped Vercel deployment token for ' + repo + '.');
  log('Stored VERCEL_TOKEN as a GitHub secret and VERCEL_ORG_ID / ' +
    'VERCEL_PROJECT_ID as GitHub variables. No token was printed or committed.');
  if (args.includes('--rotate')) {
    log('Revoke the previously issued token from Vercel Account Settings; ' +
      'replacing a GitHub secret does not revoke an old Vercel token.');
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  provision().catch((error) => {
    console.error('Vercel provisioning: ' + error.message);
    process.exitCode = 1;
  });
}
