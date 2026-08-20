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
just docs-build
just docs-dev
```

Run `docs-check` and `docs-build` serially. Configure Vercel with Root Directory `docs`.

## Release infrastructure

`dist-workspace.toml` is maintained source. `.github/workflows/release.yml` is generated:

```bash
dist plan
dist generate
```

Current distribution defaults:

- GitHub Releases
- shell installer for macOS/Linux
- PowerShell installer for Windows
- npm binary installer package
- GitHub artifact attestations

Homebrew is intentionally not part of this template.

## npm publishing

The generated `dist` npm publish job expects a GitHub Actions secret:

```text
NPM_TOKEN
```

For the first publish, the token normally needs write access to the scope because the npm package does not exist yet. Store credentials outside the repository.

## crates.io

The template itself sets `publish = false`. A real project can opt in during bootstrap with `--crates-io`, after checking that its crate name is available. That makes normal `cargo publish` / `cargo install <crate>` distribution possible; crates.io publisher/trusted-publishing setup remains an explicit owner action.

## Release process

1. Update `Cargo.toml` to the release version and refresh `Cargo.lock` with a Cargo command.
2. Update `docs/src/content/docs/changelog.md` with user-relevant changes.
3. Run:

```bash
just check
just docs-check
just docs-build
dist plan
```

4. Commit and push the release preparation.
5. Push the matching tag:

```bash
just release-tag 0.2.0
```

6. Watch `.github/workflows/release.yml` to completion and verify the GitHub Release plus npm version.

The release workflow is tag-driven. Do not repair a failed release by silently creating a different version; inspect the failed job first.
