#!/usr/bin/env python3
"""Retire one-time Rust bootstrap code from an initialized project."""

from __future__ import annotations

import re
import shutil
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    with (ROOT / "Cargo.toml").open("rb") as file:
        package = tomllib.load(file)["package"]
    if package.get("repository") == "https://github.com/amxv/rust-cli-template" and package["name"] == "mycli":
        raise SystemExit("Refusing to clean the canonical Rust CLI template. Bootstrap a project first.")

    justfile = ROOT / "Justfile"
    source = justfile.read_text()
    pattern = (
        r'(?m)^bootstrap \*args:\n    python3 scripts/bootstrap\.py "\$@"\n\n'
        r"bootstrap-clean:\n    python3 scripts/cleanup\.py\n\n"
        r"vercel-provision:\n    node scripts/provision-vercel\.mjs\n\n"
    )
    updated, count = re.subn(pattern, "", source, count=1)
    if count != 1:
        raise SystemExit("Could not find the bootstrap and bootstrap-clean recipes in Justfile")

    # The source template checks its bootstrap script in CI. Generated projects
    # must not try to check a script that bootstrap-clean has just deleted.
    ci_workflow = ROOT / ".github/workflows/ci.yml"
    ci_source = ci_workflow.read_text()
    bootstrap_check = (
        "      - name: Check bootstrap script syntax\n"
        "        run: python3 -m py_compile scripts/bootstrap.py\n\n"
    )
    if ci_source.count(bootstrap_check) != 1:
        raise SystemExit("Could not find the one-time bootstrap CI step")
    justfile.write_text(updated)
    ci_workflow.write_text(ci_source.replace(bootstrap_check, "", 1))

    for relative in [
        "scripts/bootstrap.py", "scripts/cleanup.py", "scripts/test_bootstrap.py",
        "scripts/provision-vercel.mjs", "scripts/provision-vercel.test.mjs",
    ]:
        (ROOT / relative).unlink(missing_ok=True)
    for relative in ["scripts/licenses", "scripts/direct-templates", "scripts/__pycache__"]:
        shutil.rmtree(ROOT / relative, ignore_errors=True)
    try:
        (ROOT / "scripts").rmdir()
    except OSError:
        pass  # Keep any project-owned scripts.
    print("Bootstrap removed. Cargo, docs, and the chosen release workflow are intact.")


if __name__ == "__main__":
    main()
