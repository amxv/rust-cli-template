# Contributor and maintainer notes

## Prerequisites

- Rust from `rust-toolchain.toml` (currently 1.98.0)
- `just`
- Bun for documentation work
- `dist` 0.32.0 when changing or inspecting release configuration
- GitHub repository admin access for release/npm/Vercel setup

## Development

```bash
just check-fast
just check
just build
./target/debug/mycli --help
```

The full Rust check is deliberately conventional: format check, strict Clippy, then tests.

## Docs

The documentation application is isolated in `docs/`:

```bash
just docs-install
just docs-check
just docs-dev
```

Use `docs-check` for routine local validation; GitHub Actions builds the
production bundle. Configure Vercel Root Directory `docs`.

The docs GitHub Action deploys production **only** for `docs/**` changes on
`main`. Vercel remains connected to GitHub, but its Git-triggered deployments
are disabled via `docs/vercel.json` to save the Vercel deployment quota. Set
GitHub Actions secrets `VERCEL_TOKEN`, `VERCEL_ORG_ID`, and `VERCEL_PROJECT_ID`
from the linked docs project before the first production docs deployment.
Code-only commits must never issue a Vercel deployment request.
The workflow stages `docs/.vercel/output` as repository-root `.vercel/output`
and invokes Vercel from the **repository root**, not `docs/`.

## Release infrastructure

`dist-workspace.toml` is maintained source. `.github/workflows/release.yml` is generated:

```bash
dist plan
dist generate
```

Distribution is selected during bootstrap (`npm` is the default):

- GitHub Releases
- npm mode: npm binary installer package, no standalone shell/PowerShell installer
- direct mode: website-hosted shell and PowerShell wrappers, native `upgrade`,
  cargo-dist shell/PowerShell installers, and no npm publication
- GitHub artifact attestations

## npm publishing

Only npm-mode projects have a generated npm publish job and need this GitHub Actions secret:

```text
NPM_TOKEN
```

For the first publish, the token normally needs write access to the scope because the npm package does not exist yet. Store credentials outside the repository.

## crates.io

The template itself sets `publish = false`. A real project can opt in during bootstrap with `--crates-io`, after checking that its crate name is available. That makes normal `cargo publish` / `cargo install <crate>` distribution possible; crates.io publisher/trusted-publishing setup remains an explicit owner action.

## Release process

The repository-local release skill is the canonical release procedure:

```text
.agents/skills/release/SKILL.md
```

Use it whenever cutting, shipping, or publishing a new release.
