#!/usr/bin/env node

// A local/regression helper for assessing changes to docs/.
// Actual production filtering runs in GitHub Actions using on.push.paths.
// Never wire this into Vercel ignoreCommand: that creates a canceled deployment
// that still counts toward Vercel's deployment quota.
// Return true to build and false to skip; all paths are relative to repo root.
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

// Both distribution paths keep everything the website needs inside docs/.
// Rust source, cargo-dist files, Swift app source and release workflows are unrelated.
const relevantPaths = ['docs'];

function git(args, cwd) {
  return spawnSync('git', args, {
    cwd,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
    timeout: 10_000,
  });
}

function resolveCommit(ref, repo) {
  if (!ref) return null;
  const result = git(['rev-parse', '--verify', `${ref}^{commit}`], repo);
  return result.status === 0 ? result.stdout.trim() : null;
}

export function shouldBuild(cwd = process.cwd(), env = process.env) {
  const root = git(['rev-parse', '--show-toplevel'], cwd);
  if (root.status !== 0) return true;
  const repo = root.stdout.trim();

  const head = resolveCommit(env.VERCEL_GIT_COMMIT_SHA ?? 'HEAD', repo);
  if (!head) return true;

  const previous = [
    env.VERCEL_GIT_PREVIOUS_SHA,
    env.VERCEL_GIT_PULL_REQUEST_BASE_SHA,
    env.SITE_DEPLOY_DIFF_BASE, // explicit local/test override only
  ].find(Boolean);
  const base = resolveCommit(previous, repo);
  if (!base) return true;

  const mergeBase = git(['merge-base', base, head], repo);
  if (mergeBase.status !== 0 || !mergeBase.stdout.trim()) return true;

  // Captures relevant additions, modifications, deletions and renames,
  // including changes earlier in a multi-commit push.
  const diff = git([
    'diff', '--quiet', mergeBase.stdout.trim(), head, '--', ...relevantPaths,
  ], repo);
  if (diff.status === 0) return false;
  return true; // a changed path, or an inconclusive Git error: fail open
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(shouldBuild() ? 1 : 0);
}
