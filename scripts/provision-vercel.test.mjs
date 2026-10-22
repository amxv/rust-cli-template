import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {
  createTokenRequest, mintProjectToken, obtainProjectToken,
  provision, readLinkedProject, repositoryName
} from './provision-vercel.mjs';

const linked = { projectId: 'prj_abcdefgh12345678', orgId: 'team_abc987654321' };

function fixture(t) {
  const root = mkdtempSync(path.join(os.tmpdir(), 'vercel-provision-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  mkdirSync(path.join(root, 'docs', '.vercel'), { recursive: true });
  writeFileSync(path.join(root, 'docs', '.vercel', 'project.json'), JSON.stringify(linked));
  return root;
}

function github(existing = false) {
  const calls = [];
  const execute = (binary, args, { input } = {}) => {
    assert.equal(binary, 'gh');
    calls.push({ args, input });
    if (args[0] === 'repo') return 'example/spark';
    if (args[0] === 'secret' && args[1] === 'list') {
      return JSON.stringify(existing ? [{ name: 'VERCEL_TOKEN' }] : []);
    }
    assert.ok(args[0] === 'variable' || args[0] === 'secret');
    return '';
  };
  return { calls, execute };
}

test('mints a project-specific token using the official API with team scope', async () => {
  const request = createTokenRequest('example/spark', linked, 'sensitive-value');
  assert.equal(request.url.origin, 'https://api.vercel.com');
  assert.equal(request.url.pathname, '/v3/user/tokens');
  assert.equal(request.url.searchParams.get('teamId'), linked.orgId);
  assert.equal(request.options.headers.Authorization, 'Bearer sensitive-value');
  const payload = JSON.parse(request.options.body);
  assert.equal(payload.projectId, linked.projectId);
  assert.equal(Object.hasOwn(payload, 'expiresAt'), false);
  assert.match(payload.name, /^docs-example-spark-/);
  const actual = await mintProjectToken('example/spark', linked, 'sensitive-value',
    async (_url, options) => {
      assert.equal(options.headers.Authorization, 'Bearer sensitive-value');
      return { ok: true, json: async () => ({ bearerToken: 'new-project-ci-token' }) };
    });
  assert.equal(actual, 'new-project-ci-token');
  const personal = createTokenRequest('example/spark', { ...linked, orgId: 'user_abcd' }, 'abc');
  assert.equal(personal.url.searchParams.has('teamId'), false);
});

test('token API failure reports the status without including a token or response body', async () => {
  await assert.rejects(() => mintProjectToken('example/spark', linked, 'secret-auth',
    async () => ({ ok: false, status: 403, text: async () => 'secret returned by upstream' })),
  (error) => {
    assert.equal(error.status, 403);
    assert.doesNotMatch(error.message, /secret-auth|secret returned/);
    return true;
  });
});

test('CLI credential is preferred, Keychain fallback applies only to auth failures', async () => {
  const attempted = [];
  const mint = async (_repo, _linked, credential) => {
    attempted.push(credential);
    if (credential === 'cli-session-credential') {
      const denied = new Error('insufficient access');
      denied.status = 403;
      throw denied;
    }
    return 'new-project-ci-token';
  };
  const previous = process.env.VERCEL_BOOTSTRAP_TOKEN;
  delete process.env.VERCEL_BOOTSTRAP_TOKEN;
  try {
    const token = await obtainProjectToken('example/spark', linked, {
      cliToken: 'cli-session-credential', keychainToken: 'full-account-credential', mint
    });
    assert.equal(token, 'new-project-ci-token');
    assert.deepEqual(attempted, ['cli-session-credential', 'full-account-credential']);
    await assert.rejects(
      () => obtainProjectToken('example/spark', linked, {
        cliToken: 'cli-session-credential', keychainToken: null, mint
      }),
      /classic full-account token in macOS Keychain/
    );
  } finally {
    if (previous === undefined) delete process.env.VERCEL_BOOTSTRAP_TOKEN;
    else process.env.VERCEL_BOOTSTRAP_TOKEN = previous;
  }
});

test('first provision securely passes token only through gh secret stdin', async (t) => {
  const root = fixture(t);
  const gh = github(false);
  const logs = [];
  const calls = [];
  await provision({
    projectRoot: root,
    args: [],
    command: gh.execute,
    mint: async (repo, link) => {
      calls.push({ repo, link });
      return 'sample-never-print-token';
    },
    log: (line) => logs.push(line)
  });
  assert.deepEqual(calls, [{ repo: 'example/spark', link: linked }]);
  assert.equal(gh.calls.length, 5); // repo, secret list, two vars, token secret.
  const variables = gh.calls.filter((c) => c.args[0] === 'variable');
  assert.deepEqual(variables.map((c) => c.args[2]), ['VERCEL_ORG_ID', 'VERCEL_PROJECT_ID']);
  assert.equal(variables[0].input, linked.orgId + '\n');
  assert.equal(variables[1].input, linked.projectId + '\n');
  const uploaded = gh.calls.find((c) => c.args[0] === 'secret' && c.args[1] === 'set');
  assert.ok(uploaded);
  assert.equal(uploaded.input, 'sample-never-print-token\n');
  assert.equal(JSON.stringify(uploaded.args).includes('sample-never-print-token'), false);
  assert.equal(logs.join(' ').includes('sample-never-print-token'), false);
  assert.equal(readFileSync(path.join(root, 'docs', '.vercel', 'project.json'), 'utf8'),
    JSON.stringify(linked));
});

test('idempotent provisioning keeps existing token, but --rotate creates a new one', async (t) => {
  const root = fixture(t);
  const gh = github(true);
  let minted = 0;
  const options = {
    projectRoot: root, command: gh.execute, log: () => {},
    mint: async () => { minted++; return 'replacement-token'; }
  };
  await provision(options);
  assert.equal(minted, 0);
  assert.equal(gh.calls.filter((c) => c.args[0] === 'secret' && c.args[1] === 'set').length, 0);
  await provision({ ...options, args: ['--rotate'] });
  assert.equal(minted, 1);
  assert.equal(gh.calls.filter((c) => c.args[0] === 'secret' && c.args[1] === 'set').length, 1);
});

test('check mode reads but never changes GitHub secrets, variables, or Vercel tokens', async (t) => {
  const root = fixture(t);
  const gh = github(true);
  const logs = [];
  await provision({
    args: ['--check'], projectRoot: root, command: gh.execute,
    mint: async () => { throw new Error('check mode must not mint'); },
    log: (line) => logs.push(line)
  });
  assert.equal(gh.calls.length, 2);
  assert.match(logs.join('\n'), /Deployment secret: present/);
});

test('template source protection and linked project validation', (t) => {
  assert.throws(() => repositoryName(() => 'amxv/go-cli-template'), /Refusing to provision/);
  assert.throws(() => repositoryName(() => 'amxv/rust-cli-template'), /Refusing to provision/);
  const root = fixture(t);
  assert.deepEqual(readLinkedProject(root), linked);
  writeFileSync(path.join(root, 'docs', '.vercel', 'project.json'), '{}');
  assert.throws(() => readLinkedProject(root), /must include a valid projectId and orgId/);
});
