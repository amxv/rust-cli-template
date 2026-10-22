#!/usr/bin/env python3
"""Run isolated bootstrap regressions without modifying the template checkout."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROSE_FILES = (
    "README.md", "AGENTS.md", "CONTRIBUTORS.md",
    "docs/src/pages/index.astro", "docs/src/pages/docs/index.astro",
    "docs/src/content/docs/quickstart.md", "docs/src/content/docs/changelog.md",
)


def copy_repo(destination: Path) -> Path:
    shutil.copytree(
        ROOT, destination,
        ignore=shutil.ignore_patterns(".git", "target", "node_modules", ".astro", ".vercel", "dist", "__pycache__", ".DS_Store"),
    )
    return destination


def run(repo: Path, *command: str) -> str:
    env = dict(os.environ, CARGO_NET_OFFLINE="true")
    p = subprocess.run(command, cwd=repo, text=True, capture_output=True, env=env, check=False)
    if p.returncode:
        raise AssertionError(f"{' '.join(command)} failed ({p.returncode}):\n{p.stdout}\n{p.stderr}")
    return p.stdout


def toml(repo: Path, filename: str) -> dict:
    with (repo / filename).open("rb") as f:
        return tomllib.load(f)


class BootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="rust-cli-scaffold-")
        self.addCleanup(self.temp.cleanup)
        self.repo = copy_repo(Path(self.temp.name) / "checkout")
        self.prose = {p: (self.repo / p).read_bytes() for p in PROSE_FILES}

    def bootstrap(self, distribution: str) -> None:
        run(
            self.repo, "python3", "scripts/bootstrap.py", "--cli-name", "spark", "--crate-name", "spark",
            "--github-owner", "example", "--github-repo", "spark", "--description", 'A "fast" native CLI',
            "--homepage", "https://spark.example.com", "--canonical-url", "https://spark.example.com",
            "--rust-version", "1.98.0", "--distribution", distribution,
        )
        for relative, original in self.prose.items():
            self.assertEqual((self.repo / relative).read_bytes(), original, f"bootstrap modified {relative}")
        self.assertEqual(toml(self.repo, "Cargo.toml")["package"]["name"], "spark")
        self.assertEqual(toml(self.repo, "Cargo.toml")["package"]["repository"], "https://github.com/example/spark")
        self.assertEqual(toml(self.repo, "Cargo.toml")["package"]["description"], 'A "fast" native CLI')
        self.assertIn('"name": "spark"', (self.repo / "docs/src/data/docs.ts").read_text())
        self.assertIn('"repoUrl": "https://github.com/example/spark"', (self.repo / "docs/src/data/docs.ts").read_text())
        self.assertIn("https://spark.example.com", (self.repo / "docs/astro.config.mjs").read_text())
        self.assertIn("@example/spark-docs", (self.repo / "docs/package.json").read_text())

    def cleanup(self) -> None:
        run(self.repo, "just", "bootstrap-clean")
        self.assertFalse((self.repo / "scripts/bootstrap.py").exists())
        self.assertFalse((self.repo / "scripts/cleanup.py").exists())
        self.assertFalse((self.repo / "scripts/direct-templates").exists())
        self.assertFalse((self.repo / "scripts/licenses").exists())
        self.assertNotIn("bootstrap *args:", (self.repo / "Justfile").read_text())
        self.assertNotIn("bootstrap-clean:", (self.repo / "Justfile").read_text())

    def test_npm_only(self) -> None:
        self.bootstrap("npm")
        dist = toml(self.repo, "dist-workspace.toml")["dist"]
        self.assertEqual(dist["installers"], ["npm"])
        self.assertEqual(dist["publish-jobs"], ["npm"])
        self.assertEqual(dist["npm-package"], "spark")
        self.assertFalse((self.repo / "docs/public/install.sh").exists())
        self.assertFalse((self.repo / "src/commands/upgrade.rs").exists())
        self.assertIn("publish-npm:", (self.repo / ".github/workflows/release.yml").read_text())
        run(self.repo, "cargo", "test", "--locked")
        self.cleanup()
        run(self.repo, "cargo", "check", "--locked")

    def test_direct_only(self) -> None:
        self.bootstrap("direct")
        dist = toml(self.repo, "dist-workspace.toml")["dist"]
        self.assertEqual(dist["installers"], ["shell", "powershell"])
        self.assertEqual(dist["publish-jobs"], [])
        self.assertNotIn("npm-scope", dist)
        self.assertNotIn("npm-package", dist)
        self.assertNotIn("publish-npm:", (self.repo / ".github/workflows/release.yml").read_text())
        installer = (self.repo / "docs/public/install.sh").read_text()
        self.assertIn("${cli}-installer.sh", installer)
        self.assertIn("cli='spark'", installer)
        self.assertIn("github.com/example/spark", installer)
        self.assertIn("${Cli}-installer.ps1", (self.repo / "docs/public/install.ps1").read_text())
        self.assertIn("https://spark.example.com", (self.repo / "src/commands/upgrade.rs").read_text())
        run(self.repo, "sh", "-n", "docs/public/install.sh")
        run(self.repo, "cargo", "test", "--locked")
        output = run(self.repo, "cargo", "run", "--quiet", "--", "upgrade", "--help")
        self.assertIn("--check", output)
        self.cleanup()
        self.assertTrue((self.repo / "docs/public/install.sh").exists())
        self.assertTrue((self.repo / "src/commands/upgrade.rs").exists())
        run(self.repo, "cargo", "check", "--locked")


if __name__ == "__main__":
    unittest.main(verbosity=2)
