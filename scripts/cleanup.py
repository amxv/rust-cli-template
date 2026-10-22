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
    pattern = r"(?m)^bootstrap \*args:\n    python3 scripts/bootstrap\.py \{\{args\}\}\n\nbootstrap-clean:\n    python3 scripts/cleanup\.py\n\n"
    updated, count = re.subn(pattern, "", source, count=1)
    if count != 1:
        raise SystemExit("Could not find the bootstrap and bootstrap-clean recipes in Justfile")
    justfile.write_text(updated)

    for relative in ["scripts/bootstrap.py", "scripts/cleanup.py", "scripts/test_bootstrap.py"]:
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
