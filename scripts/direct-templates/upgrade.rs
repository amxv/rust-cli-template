use anyhow::{Context, Result, bail};
use std::env;
use std::fs;
use std::path::PathBuf;
use std::process::{Command, Stdio};

use crate::commands::auto_update;

const INSTALLER_SITE: &str = "__SITE__";
const GITHUB_LATEST: &str = "https://github.com/__OWNER__/__REPO__/releases/latest";
const TAG_PREFIX: &str = "/__OWNER__/__REPO__/releases/tag/v";

fn parse_version(value: &str) -> Option<[u64; 3]> {
    let version = value.strip_prefix('v').unwrap_or(value);
    let segments: Vec<_> = version.split('.').collect();
    if segments.len() != 3 { return None }
    let mut parsed = [0; 3];
    for (i, part) in segments.iter().enumerate() {
        if part.is_empty() || !part.bytes().all(|x| x.is_ascii_digit()) { return None }
        parsed[i] = part.parse().ok()?;
    }
    Some(parsed)
}

fn latest_from_location(raw: &str) -> Result<String> {
    let url = raw.trim();
    let path = if let Some(relative) = url.strip_prefix("https://github.com") {
        relative
    } else if url.starts_with('/') && !url.starts_with("//") {
        url
    } else {
        bail!("Untrusted latest GitHub release redirect");
    };
    let Some(version) = path.strip_prefix(TAG_PREFIX) else {
        bail!("GitHub redirect did not identify this repository's release");
    };
    if parse_version(version).is_none() {
        bail!("GitHub release version is not a stable three-part SemVer");
    }
    Ok(version.to_string())
}

fn latest_version() -> Result<String> {
    // /releases/latest redirects are not subject to the shared GitHub REST
    // anonymous API quota. Do not follow to untrusted URLs.
    let output = Command::new("curl")
        .args(["--proto", "=https", "--tlsv1.2", "-fsSI", "--max-time", "20", GITHUB_LATEST])
        .output().context("curl is required to check releases")?;
    if !output.status.success() { bail!("Unable to read latest GitHub Release headers"); }
    let headers = String::from_utf8(output.stdout).context("Invalid GitHub Release headers")?;
    let location = headers.lines().rev()
        .find_map(|line| line.trim().strip_prefix("location:")
            .or_else(|| line.trim().strip_prefix("Location:")))
        .context("Latest release response was missing a redirect")?;
    latest_from_location(location)
}

/// `upgrade --automatic` is reserved for the background OS scheduler. It
/// persists the daily check before network I/O and never flips a user's opt-out.
pub fn run(check: bool, automatic: bool) -> Result<()> {
    if automatic && !auto_update::claim()? { return Ok(()) }
    let latest = latest_version()?;
    let current = env!("CARGO_PKG_VERSION");
    if check { println!("Installed: {current}\nLatest: {latest}"); }
    let Some(installed) = parse_version(current) else {
        if automatic { bail!("Cannot auto-update a development or prerelease build") }
        if check { return Ok(()) }
        bail!("Unknown installed version {current}");
    };
    let release = parse_version(&latest).context("Latest stable version was invalid")?;
    if release <= installed {
        if !check { println!("Already up to date."); }
        return Ok(())
    }
    if check {
        println!("Update available.");
        return Ok(())
    }
    if automatic && !auto_update::enabled()? { return Ok(()) }
    install(&latest, automatic)
}

fn install(version: &str, automatic: bool) -> Result<()> {
    let exe = env::current_exe().context("Cannot determine current executable")?.canonicalize()?;
    let filename = if cfg!(windows) { "install.ps1" } else { "install.sh" };
    let url = format!("{INSTALLER_SITE}/{filename}");
    let suffix = if cfg!(windows) { "ps1" } else { "sh" };
    let path: PathBuf = env::temp_dir().join(format!("__CLI__-upgrade-{}.{}", std::process::id(), suffix));
    if path.exists() { bail!("Temporary installer already exists at {}", path.display()) }

    let curl = if cfg!(windows) { "curl.exe" } else { "curl" };
    let fetched = Command::new(curl)
        .args(["--proto", "=https", "--tlsv1.2", "-fsSL", "--retry", "3", "-o"])
        .arg(&path)
        .arg(url)
        .status()
        .context("curl is required for direct CLI upgrades")?;
    if !fetched.success() {
        let _ = fs::remove_file(&path);
        bail!("Could not download installer from the docs website")
    }
    if automatic && !auto_update::enabled()? {
        let _ = fs::remove_file(&path);
        return Ok(())
    }

    let mut command;
    if cfg!(windows) {
        command = Command::new("powershell.exe");
        command.args(["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File"]);
        command.arg(&path).arg("-Upgrade").arg("-Target").arg(&exe)
            .arg("-WaitForPid").arg(std::process::id().to_string());
        command.env("CLI_VERSION", version);
    } else {
        command = Command::new("sh");
        command.arg(&path).arg("upgrade");
        command.env("CLI_UPGRADE_TARGET", &exe);
    }
    command.stdin(Stdio::null()).stdout(Stdio::inherit()).stderr(Stdio::inherit());
    if cfg!(windows) {
        let child = command.spawn().context("Could not start detached Windows upgrade")?;
        println!("Upgrade started. Replacement completes after this command exits.");
        drop(child);
        return Ok(()); // Windows helper removes the temporary installer script.
    }
    let result = command.status();
    let _ = fs::remove_file(&path);
    if !result.context("Installer failed to execute")?.success() {
        bail!("Upgrade installer exited unsuccessfully");
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn compares_three_part_stable_versions() {
        assert!(parse_version("1.2.3") > parse_version("1.2.2"));
        assert!(parse_version("2.0.0") > parse_version("1.99.99"));
        assert!(parse_version("1.2.0") < parse_version("1.3.0"));
        for invalid in ["dev", "1.2", "1.2.3-beta", "1.2.3.4"] {
            assert!(parse_version(invalid).is_none());
        }
    }

    #[test]
    fn rejects_cross_repository_and_prerelease_redirects() {
        assert_eq!(latest_from_location("https://github.com/__OWNER__/__REPO__/releases/tag/v1.2.3").unwrap(), "1.2.3");
        assert_eq!(latest_from_location("/__OWNER__/__REPO__/releases/tag/v1.2.3").unwrap(), "1.2.3");
        for invalid in [
            "https://evil.example/__OWNER__/__REPO__/releases/tag/v1.2.3",
            "https://github.com/other/project/releases/tag/v1.2.3",
            "https://github.com/__OWNER__/__REPO__/releases/tag/v1.2.3?unsafe=1",
            "https://github.com/__OWNER__/__REPO__/releases/tag/v1.2.3-rc1",
        ] {
            assert!(latest_from_location(invalid).is_err(), "{invalid}");
        }
    }
}
