import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, readFileSync, renameSync, unlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { shouldBuild } from './should-build.mjs';

const docsRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function git(repo, ...args) {
  const result = spawnSync('git', args, { cwd: repo, encoding: 'utf8' });
  assert.equal(result.status, 0, `git ${args.join(' ')}: ${result.stderr}`);
  return result.stdout.trim();
}

function fixture(t) {
  const root = mkdtempSync(path.join(tmpdir(), 'cli-template-vercel-ignore-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  git(root, 'init', '--initial-branch=main');
  git(root, 'config', 'user.email', 'fixture@example.com');
  git(root, 'config', 'user.name', 'CLI template test');
  mkdirSync(path.join(root, 'docs', 'public'), { recursive: true });
  mkdirSync(path.join(root, 'scripts'));
  mkdirSync(path.join(root, 'internal'));
  mkdirSync(path.join(root, 'src'));
  writeFileSync(path.join(root, 'docs', 'index.md'), 'initial docs\n');
  writeFileSync(path.join(root, 'docs', 'public', 'install.sh'), 'initial unix installer\n');
  writeFileSync(path.join(root, 'docs', 'public', 'install.ps1'), 'initial windows installer\n');
  writeFileSync(path.join(root, 'src', 'lib.rs'), 'initial Rust code\n');
  writeFileSync(path.join(root, 'internal', 'gateway.go'), 'initial code\n');
  git(root, 'add', '.');
  git(root, 'commit', '-m', 'initial');
  const base = git(root, 'rev-parse', 'HEAD');
  return {
    root,
    base,
    commit(relativePath, contents) {
      writeFileSync(path.join(root, relativePath), contents);
      git(root, 'add', '-A');
      git(root, 'commit', '-m', `change ${relativePath}`);
      return git(root, 'rev-parse', 'HEAD');
    },
    build(head = git(root, 'rev-parse', 'HEAD'), from = base, env = {}) {
      return shouldBuild(path.join(root, 'docs'), {
        VERCEL_GIT_COMMIT_SHA: head,
        VERCEL_GIT_PREVIOUS_SHA: from,
        ...env,
      });
    },
  };
}

test('Go/Rust source, root metadata and bootstrap scripts do not deploy docs', t => {
  const f = fixture(t);
  f.commit('internal/gateway.go', 'new router\n');
  assert.equal(f.build(), false);
  f.commit('src/lib.rs', 'different Rust code\n');
  assert.equal(f.build(), false);
  f.commit('VERSION', '0.4.0\n');
  assert.equal(f.build(), false);
  f.commit('scripts/setup.js', 'bootstrap changed\n');
  assert.equal(f.build(), false);
  f.commit('README.md', 'root readme changed\n');
  assert.equal(f.build(), false);
});

test('any documentation change deploys', t => {
  const f = fixture(t);
  f.commit('docs/index.md', 'updated docs\n');
  assert.equal(f.build(), true);
});

for (const installer of ['install.sh', 'install.ps1']) {
  test(`changes to docs/public/${installer} deploy docs`, t => {
    const f = fixture(t);
    f.commit(`docs/public/${installer}`, 'updated website installer\n');
    assert.equal(f.build(), true);
  });
}

test('documentation renames and deletions deploy', t => {
  const f = fixture(t);
  renameSync(path.join(f.root, 'docs/index.md'), path.join(f.root, 'docs/renamed.md'));
  git(f.root, 'add', '-A');
  git(f.root, 'commit', '-m', 'rename docs');
  assert.equal(f.build(), true);
  const renamed = git(f.root, 'rev-parse', 'HEAD');
  unlinkSync(path.join(f.root, 'docs/renamed.md'));
  git(f.root, 'add', '-A');
  git(f.root, 'commit', '-m', 'remove docs');
  assert.equal(f.build(undefined, renamed), true);
});

test('earlier relevant commit in a multi-commit push is not missed', t => {
  const f = fixture(t);
  f.commit('docs/index.md', 'important docs update\n');
  f.commit('internal/gateway.go', 'a later code-only commit\n');
  assert.equal(f.build(), true);
});

test('PR base and explicit local override work when previous SHA is absent', t => {
  const f = fixture(t);
  f.commit('docs/index.md', 'new guide\n');
  assert.equal(f.build(undefined, '', {
    VERCEL_GIT_PREVIOUS_SHA: '',
    VERCEL_GIT_PULL_REQUEST_BASE_SHA: f.base,
  }), true);
  assert.equal(f.build(undefined, '', {
    VERCEL_GIT_PREVIOUS_SHA: '',
    VERCEL_GIT_PULL_REQUEST_BASE_SHA: '',
    SITE_DEPLOY_DIFF_BASE: f.base,
  }), true);
});

test('docs-free multi-commit push is ignored', t => {
  const f = fixture(t);
  f.commit('internal/gateway.go', 'fix Go logic\n');
  f.commit('src/lib.rs', 'fix Rust logic\n');
  assert.equal(f.build(), false);
});

test('unresolved base/head and missing Git repository fail open', t => {
  const f = fixture(t);
  f.commit('internal/gateway.go', 'code only\n');
  assert.equal(f.build(undefined, 'not-a-real-sha'), true);
  assert.equal(f.build('not-a-real-sha'), true);
  assert.equal(f.build(undefined, '', { VERCEL_GIT_PREVIOUS_SHA: '', SITE_DEPLOY_DIFF_BASE: '' }), true);
  assert.equal(shouldBuild(tmpdir(), { VERCEL_GIT_COMMIT_SHA: 'HEAD' }), true);
});

test('committed Vercel configuration restricts branches and uses the script', () => {
  const config = JSON.parse(readFileSync(path.join(docsRoot, 'vercel.json'), 'utf8'));
  assert.equal(config.ignoreCommand, 'node scripts/should-build.mjs');
  assert.deepEqual(config.git.deploymentEnabled, { main: true, '*': false });
});
