---
title: Docs site maintenance
description: Maintain the Astro/ZueDocs site without mixing JavaScript tooling into the Rust root.
order: 5
category: Reference
summary: The docs workspace boundary, checks, and Vercel behavior.
---

## Workspace boundary

Everything required by the web app lives in `docs/`:

```text
docs/package.json
docs/bun.lock
docs/astro.config.mjs
docs/vercel.json
docs/scripts/
docs/src/
```

The repository root intentionally has no Node package or Astro configuration.

## Development

```bash
just docs-install
just docs-dev
```

## Validation

```bash
just docs-test
just docs-check
```

Astro check is sufficient locally; Vercel runs the production build when deploying.

## Vercel

Set the Vercel project Root Directory to `docs`. The committed `vercel.json` builds static Astro output and calls `scripts/should-build.mjs` before a deployment.

That script compares merge-base Git commit ranges and returns a skip result when
only Rust, Swift, or root metadata changed; anything under `docs/` triggers a
build. It handles earlier changes in multi-commit pushes, renames, and deletions,
and fails open if Vercel lacks the necessary Git history. Its behavior is covered
by `just docs-test` / `bun run test:vercel`.

Vercel still counts deployments canceled by the Ignored Build Step toward daily
deployment limits. For a strict no-quota code-only push, use a `docs/**`-scoped
GitHub Actions deployment with automatic Vercel Git deployments disabled, or
native skip-unaffected-projects when the repository meets the workspace rules.
