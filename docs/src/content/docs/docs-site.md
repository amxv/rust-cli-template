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

Set the Vercel project Root Directory to `docs` and connect its GitHub repo,
but keep `git.deploymentEnabled: false` in the committed `vercel.json`. The
`.github/workflows/docs.yml` workflow responds to `docs/**` changes on
`main`, validates Astro, and deploys with the Vercel CLI. Rust-only, Swift-only,
and Cargo changes never request a Vercel deployment, so they cannot use its
daily deployment quota through this pipeline.

After linking `docs/` to Vercel, run `just vercel-provision` in the generated
repository **before** `just bootstrap-clean`. It mints a project-scoped CI
token using the existing Vercel CLI login (or macOS Keychain as a fallback),
stores `VERCEL_TOKEN` in Actions secrets and the two non-sensitive IDs in
Actions variables. The GitHub workflow builds and deploys Astro's static
output with `--prebuilt`, avoiding broad settings calls that may fail with
restricted tokens. Agents use only `just docs-check` for local Astro
validation. `just docs-test` validates both the GitHub path
filter and the retained local Git diff helper `docs/scripts/should-build.mjs`.
It is deliberately **not** wired to `ignoreCommand`, because a canceled
Vercel Ignored Build Step still counts toward deployment quotas.
