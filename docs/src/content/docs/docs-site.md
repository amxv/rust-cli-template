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

In the generated GitHub repository, configure secrets `VERCEL_TOKEN`,
`VERCEL_ORG_ID`, and `VERCEL_PROJECT_ID` from the linked docs project before
the first push-to-deploy. `just docs-test` validates both the GitHub path
filter and the retained local Git diff helper `docs/scripts/should-build.mjs`.
It is deliberately **not** wired to `ignoreCommand`, because a canceled
Vercel Ignored Build Step still counts toward deployment quotas.
