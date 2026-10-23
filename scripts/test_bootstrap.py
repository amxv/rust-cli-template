#!/usr/bin/env python3
"""Run isolated bootstrap regressions without modifying the template checkout."""

from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
import sys
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

    def bootstrap(self, distribution: str, menubar: bool = False, rust_version: str = "1.98.0") -> None:
        args = [
            "python3", "scripts/bootstrap.py", "--cli-name", "spark", "--crate-name", "spark",
            "--github-owner", "example", "--github-repo", "spark", "--description", 'A "fast" native CLI',
            "--homepage", "https://spark.example.com", "--canonical-url", "https://spark.example.com",
            "--rust-version", rust_version, "--distribution", distribution,
        ]
        if menubar:
            args.append("--macos-menubar")
        run(self.repo, *args)
        for relative, original in self.prose.items():
            self.assertEqual((self.repo / relative).read_bytes(), original, f"bootstrap modified {relative}")
        self.assertEqual(toml(self.repo, "Cargo.toml")["package"]["name"], "spark")
        self.assertEqual(toml(self.repo, "Cargo.toml")["package"]["repository"], "https://github.com/example/spark")
        self.assertEqual(toml(self.repo, "Cargo.toml")["package"]["description"], 'A "fast" native CLI')
        self.assertIn('"name": "spark"', (self.repo / "docs/src/data/docs.ts").read_text())
        self.assertIn('"repoUrl": "https://github.com/example/spark"', (self.repo / "docs/src/data/docs.ts").read_text())
        self.assertIn("https://spark.example.com", (self.repo / "docs/astro.config.mjs").read_text())
        self.assertIn("@example/spark-docs", (self.repo / "docs/package.json").read_text())
        vercel = json.loads((self.repo / "docs/vercel.json").read_text())
        self.assertIs(vercel["git"]["deploymentEnabled"], False)
        self.assertNotIn("ignoreCommand", vercel)
        workflow = (self.repo / ".github/workflows/docs.yml").read_text()
        self.assertIn('"docs/**"', workflow)
        self.assertIn("VERCEL_TOKEN", workflow)
        self.assertIn("working-directory: .", workflow)
        self.assertIn("cp -R docs/.vercel/output .vercel/output", workflow)
        ci = (self.repo / ".github/workflows/ci.yml").read_text()
        self.assertIn(f"- name: Install Rust {rust_version}", ci)
        self.assertIn(f"toolchain: {rust_version}", ci)

    def cleanup(self) -> None:
        run(self.repo, "just", "bootstrap-clean")
        self.assertFalse((self.repo / "scripts/provision-vercel.mjs").exists())
        self.assertTrue((self.repo / ".github/workflows/docs.yml").exists(),
                        "Bootstrap cleanup must retain docs-only production deployment workflow")
        self.assertTrue((self.repo / "docs/scripts/should-build.mjs").exists(),
                        "Bootstrap cleanup must retain Vercel docs-only filtering")
        self.assertFalse((self.repo / "scripts/bootstrap.py").exists())
        self.assertFalse((self.repo / "scripts/cleanup.py").exists())
        self.assertFalse((self.repo / "scripts/direct-templates").exists())
        self.assertFalse((self.repo / "scripts/licenses").exists())
        self.assertNotIn("bootstrap *args:", (self.repo / "Justfile").read_text())
        self.assertNotIn("bootstrap-clean:", (self.repo / "Justfile").read_text())
        self.assertNotIn("vercel-provision:", (self.repo / "Justfile").read_text())
        ci = (self.repo / ".github/workflows/ci.yml").read_text()
        self.assertNotIn("Check bootstrap script syntax", ci)
        self.assertNotIn("scripts/bootstrap.py", ci)

    def test_just_bootstrap_preserves_quoted_arguments(self) -> None:
        run(self.repo, "just", "bootstrap", "--cli-name", "spark",
            "--github-owner", "example", "--github-repo", "spark",
            "--description", 'A "fast" native CLI with spaces',
            "--rust-version", "1.98.0", "--distribution", "npm")
        self.assertEqual(toml(self.repo, "Cargo.toml")["package"]["description"],
                         'A "fast" native CLI with spaces')
        self.cleanup()
        self.assertIn('set positional-arguments\n', (self.repo / "Justfile").read_text())
        self.assertIn("Hello, two words!", run(self.repo, "just", "run", "hello", "two words"))

    def test_npm_only(self) -> None:
        self.bootstrap("npm")
        run(self.repo, "node", "--test", "scripts/provision-vercel.test.mjs")
        self.assertFalse((self.repo / "apps/menubar").exists())
        dist = toml(self.repo, "dist-workspace.toml")["dist"]
        self.assertEqual(dist["installers"], ["npm"])
        self.assertEqual(dist["publish-jobs"], ["npm"])
        self.assertEqual(dist["npm-package"], "spark")
        self.assertFalse((self.repo / "docs/public/install.sh").exists())
        self.assertFalse((self.repo / "src/commands/upgrade.rs").exists())
        self.assertIn("publish-npm:", (self.repo / ".github/workflows/release.yml").read_text())
        run(self.repo, "cargo", "test", "--locked")
        self.cleanup()
        self.assertFalse((self.repo / "scripts/direct-templates/menubar").exists())
        run(self.repo, "cargo", "check", "--locked")

    def test_direct_only(self) -> None:
        # The current stable toolchain surfaced new Clippy checks in Rindle.
        self.bootstrap("direct", rust_version="1.99.1")
        self.assertFalse((self.repo / "apps/menubar").exists())
        self.assertFalse((self.repo / ".github/workflows/publish-menubar.yml").exists())
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
        self.assertTrue((self.repo / "src/commands/auto_update.rs").exists())
        self.assertIn("AutoUpdate", (self.repo / "src/cli.rs").read_text())
        run(self.repo, "sh", "-n", "docs/public/install.sh")
        run(self.repo, "cargo", "fmt", "--all", "--", "--check")
        run(self.repo, "cargo", "clippy", "--locked", "--all-targets", "--", "-D", "warnings")
        run(self.repo, "cargo", "test", "--locked")
        output = run(self.repo, "cargo", "run", "--quiet", "--", "upgrade", "--help")
        self.assertIn("--check", output)
        self.check_auto_update_controls()
        self.cleanup()
        self.assertFalse((self.repo / "scripts/direct-templates/menubar").exists())
        self.assertTrue((self.repo / "docs/public/install.sh").exists())
        self.assertTrue((self.repo / "src/commands/upgrade.rs").exists())
        self.assertTrue((self.repo / "src/commands/auto_update.rs").exists())
        run(self.repo, "cargo", "check", "--locked")

    def test_menu_bar_requires_direct_distribution(self) -> None:
        p = subprocess.run(
            ["python3", "scripts/bootstrap.py", "--macos-menubar", "--distribution", "npm"],
            cwd=self.repo, text=True, capture_output=True
        )
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("--macos-menubar requires --distribution direct", p.stderr)
        self.assertFalse((self.repo / "apps/menubar").exists())

    @unittest.skipUnless(sys.platform == "darwin", "Swift menu bar bundles require macOS")
    def test_direct_menu_bar_builds_installs_and_survives_cleanup(self) -> None:
        self.bootstrap("direct", menubar=True)
        self.assertTrue((self.repo / "apps/menubar/Info.plist").exists())
        self.assertTrue((self.repo / "apps/menubar/Sources/main.swift").exists())
        self.assertTrue((self.repo / ".github/workflows/publish-menubar.yml").exists())
        self.assertFalse((self.repo / "package.json").exists())
        dist = toml(self.repo, "dist-workspace.toml")["dist"]
        self.assertEqual(dist["post-announce-jobs"], ["./publish-menubar"])
        self.assertEqual(dist["installers"], ["shell", "powershell"])
        workflow = (self.repo / ".github/workflows/release.yml").read_text()
        self.assertIn("custom-publish-menubar:", workflow)
        self.assertNotIn("publish-npm:", workflow)
        script = (self.repo / "docs/public/install.sh").read_text()
        self.assertIn("Spark.app", script)
        self.assertIn("${binary}_darwin_${arch}.tar.gz", script)
        run(self.repo, "dist", "generate", "--check")
        run(self.repo, "sh", "-n", "docs/public/install.sh")
        run(self.repo, "cargo", "fmt", "--all", "--", "--check")
        run(self.repo, "cargo", "test", "--locked")
        run(self.repo, "cargo", "build", "--locked")
        cargo = json.loads(run(self.repo, "cargo", "metadata", "--no-deps", "--format-version", "1"))
        binary = Path(cargo["target_directory"]) / "debug" / "spark"
        stage = self.repo / "stage"
        stage.mkdir()
        shutil.copy2(binary, stage / "spark")
        app = stage / "Spark.app"
        architecture = "arm64" if os.uname().machine in ("arm64", "aarch64") else "amd64"
        run(self.repo, "bash", "apps/menubar/build.sh", str(app), architecture, "0.1.0")
        run(self.repo, "codesign", "--verify", "--deep", "--strict", str(app))
        self.assertIn(
            "companion CLI are ready",
            run(self.repo, str(app / "Contents/MacOS/spark-menubar"), "--check")
        )
        asset = f"spark_darwin_{architecture}.tar.gz"
        archive = self.repo / asset
        p = subprocess.run(
            ["tar", "-czf", str(archive), "-C", str(stage), "spark", "Spark.app"],
            cwd=self.repo, capture_output=True, text=True,
            env={**os.environ, "COPYFILE_DISABLE": "1"}
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
        (self.repo / (asset + ".sha256")).write_text(checksum + "\n")
        fake_tools = self.repo / "mock-tools"
        fake_tools.mkdir()
        curl = fake_tools / "curl"
        curl.write_text("\n".join([
            "#!/bin/sh",
            'target=""',
            'previous=""',
            'asset=""',
            'for argument in "$@"; do',
            '  if [ "$previous" = "-o" ]; then target="$argument"; fi',
            '  previous="$argument"',
            '  case "$argument" in',
            f'    */{asset}.sha256) asset="{asset}.sha256" ;;',
            f'    */{asset}) asset="{asset}" ;;',
            "  esac",
            "done",
            'test -n "$asset" && test -n "$target" || exit 40',
            'cp "$FAKE_RELEASE/$asset" "$target"',
            "",
        ]))
        curl.chmod(0o755)
        installed = self.repo / "installed"
        env = {
            **os.environ, "PATH": str(fake_tools) + ":" + os.environ.get("PATH", ""),
            "CLI_INSTALL_DIR": str(installed), "CLI_VERSION": "0.1.0",
            "CLI_NO_LAUNCH": "1", "FAKE_RELEASE": str(self.repo),
        }

        def install(*args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(["sh", "docs/public/install.sh", *args], cwd=self.repo,
                                  text=True, capture_output=True, env=env)

        result = install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((installed / "spark").read_bytes(), binary.read_bytes())
        run(self.repo, "codesign", "--verify", "--deep", "--strict", str(installed / "Spark.app"))
        (self.repo / (asset + ".sha256")).write_text("0" * 64 + "\n")
        result = install("upgrade")
        self.assertNotEqual(result.returncode, 0, "checksum mismatch must abort before replacing the app")
        self.assertEqual((installed / "spark").read_bytes(), binary.read_bytes())
        (self.repo / (asset + ".sha256")).write_text(checksum + "\n")
        result = install("upgrade")
        self.assertEqual(result.returncode, 0, result.stderr)
        run(self.repo, "codesign", "--verify", "--deep", "--strict", str(installed / "Spark.app"))
        self.cleanup()
        self.assertTrue((self.repo / "apps/menubar/build.sh").exists())
        self.assertTrue((self.repo / ".github/workflows/publish-menubar.yml").exists())
        self.assertFalse((self.repo / "scripts/direct-templates/menubar").exists())
        run(self.repo, "cargo", "check", "--locked")

    def check_auto_update_controls(self) -> None:
        run(self.repo, "cargo", "build", "--locked")
        cargo = json.loads(run(self.repo, "cargo", "metadata", "--no-deps", "--format-version", "1"))
        cli = Path(cargo["target_directory"]) / "debug" / ("spark.exe" if os.name == "nt" else "spark")
        self.assertTrue(cli.is_file(), f"missing compiled fixture executable: {cli}")
        home = self.repo / "scheduler-home"
        commands = self.repo / "scheduler-bin"
        home.mkdir()
        commands.mkdir()
        fake = commands / ("launchctl" if sys.platform == "darwin" else "systemctl")
        fake.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$SCHEDULER_TEST_LOG\"\n"
                        "if [ \"$1\" = print ]; then\n"
                        "  case \"$2\" in */com.example.spark.auto-update) exit 1 ;; esac\n"
                        "fi\nexit 0\n")
        fake.chmod(0o755)
        log = self.repo / "scheduler.log"
        env = {**os.environ, "HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"),
               "PATH": f"{commands}:{os.environ.get('PATH', '')}", "SCHEDULER_TEST_LOG": str(log)}
        fake_curl = commands / "curl"
        fake_curl.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CURL_TEST_LOG\"\n"
                             "if [ \"${FAKE_CURL_FAIL:-0}\" = 1 ]; then exit 7; fi\n"
                             "printf 'HTTP/2 302\\r\\nlocation: https://github.com/example/spark/releases/tag/v0.1.0\\r\\n\\r\\n'\n")
        fake_curl.chmod(0o755)
        curl_log = self.repo / "curl.log"
        env["CURL_TEST_LOG"] = str(curl_log)

        def invoke(*args: str) -> str:
            result = subprocess.run([str(cli), *args], text=True, capture_output=True, env=env, cwd=self.repo)
            self.assertEqual(result.returncode, 0, f"{' '.join(args)}: {result.stderr}")
            return result.stdout

        self.assertIn("off", invoke("auto-update", "status"))
        invoke("upgrade", "--automatic")  # disabled, no real network access
        invoke("auto-update", "on")
        self.assertIn("on (every 24 hours)", invoke("auto-update", "status"))
        env["FAKE_CURL_FAIL"] = "1"
        failed = subprocess.run([str(cli), "upgrade", "--automatic"], text=True, capture_output=True, cwd=self.repo, env=env)
        self.assertNotEqual(failed.returncode, 0, "network failure must be surfaced")
        self.assertIn("on", invoke("auto-update", "status"), "a failed check must not disable scheduling")
        first_calls = len(curl_log.read_text().splitlines())
        self.assertEqual(first_calls, 1)
        invoke("upgrade", "--automatic")  # already claimed today; no retry loop
        self.assertEqual(len(curl_log.read_text().splitlines()), 1)
        env.pop("FAKE_CURL_FAIL")
        checked = invoke("upgrade", "--check")
        self.assertIn("Installed: 0.1.0", checked)
        self.assertIn("Latest: 0.1.0", checked)
        self.assertNotIn("Update available.", checked)
        if sys.platform == "darwin":
            self.assertIn("bootstrap gui/", log.read_text())
            self.assertIn("86400", (home / "Library/LaunchAgents/com.example.spark.auto-update.plist").read_text())
        else:
            self.assertIn("enable --now", log.read_text())
            self.assertIn("OnCalendar=daily", (home / ".config/systemd/user/example.spark.auto-update.timer").read_text())
        invoke("auto-update", "off")
        self.assertIn("off", invoke("auto-update", "status"))
        invoke("upgrade", "--automatic")  # opt-out is persistent


if __name__ == "__main__":
    unittest.main(verbosity=2)
