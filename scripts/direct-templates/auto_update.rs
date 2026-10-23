//! Persistent opt-in daily updates for CLI-only applications. The operating
//! system owns the schedule, so the CLI need not remain open between checks.
use anyhow::{Context, Result, bail};
use std::env;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use crate::cli::AutoUpdateAction;

const APP_NAME: &str = "__CLI__";
const SERVICE_ID: &str = "__OWNER__.__REPO__.auto-update";
const DAY_SECONDS: u64 = 24 * 60 * 60;

#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
struct Preferences {
    enabled: bool,
    last_check: u64,
}

fn user_home() -> Result<PathBuf> {
    let home = env::var_os(if cfg!(windows) { "USERPROFILE" } else { "HOME" })
        .context("Cannot determine home directory")?;
    Ok(PathBuf::from(home))
}

fn preference_file() -> Result<PathBuf> {
    let base = if cfg!(windows) {
        PathBuf::from(env::var_os("APPDATA").context("APPDATA is not set")?)
    } else if cfg!(target_os = "macos") {
        user_home()?.join("Library/Application Support")
    } else if let Some(xdg) = env::var_os("XDG_CONFIG_HOME") {
        PathBuf::from(xdg)
    } else {
        user_home()?.join(".config")
    };
    Ok(base.join(APP_NAME).join("auto-update.conf"))
}

fn load() -> Result<Preferences> {
    let path = preference_file()?;
    let contents = match fs::read_to_string(path) {
        Ok(value) => value,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(Preferences::default()),
        Err(error) => return Err(error).context("Cannot read automatic update preferences"),
    };
    let mut prefs = Preferences::default();
    for line in contents.lines() {
        if let Some(value) = line.strip_prefix("enabled=") {
            prefs.enabled = match value {
                "true" => true, "false" => false, _ => bail!("Invalid saved auto-update preference"),
            };
        } else if let Some(value) = line.strip_prefix("last_check=") {
            prefs.last_check = value.parse().context("Invalid saved auto-update timestamp")?;
        } else if !line.is_empty() { bail!("Invalid saved auto-update preference line") }
    }
    Ok(prefs)
}

fn write_atomic(path: &Path, data: &[u8]) -> Result<()> {
    let parent = path.parent().context("Missing auto-update directory")?;
    fs::create_dir_all(parent).context("Cannot create auto-update directory")?;
    if let Ok(meta) = fs::symlink_metadata(path)
        && !meta.file_type().is_file()
    {
        bail!("Refusing non-regular auto-update path")
    }
    let name = format!(".auto-update-{}-{}", std::process::id(),
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos());
    let tmp = parent.join(name);
    let mut file = OpenOptions::new().create_new(true).write(true).open(&tmp)?;
    #[cfg(unix)] {
        use std::os::unix::fs::PermissionsExt;
        file.set_permissions(fs::Permissions::from_mode(0o600))?;
    }
    if let Err(error) = file.write_all(data).and_then(|_| file.sync_all()) {
        let _ = fs::remove_file(&tmp);
        return Err(error.into());
    }
    drop(file);
    if let Err(error) = fs::rename(&tmp, path) {
        let _ = fs::remove_file(&tmp);
        return Err(error.into());
    }
    Ok(())
}

fn save(prefs: Preferences) -> Result<()> {
    let text = format!("enabled={}\nlast_check={}\n", prefs.enabled, prefs.last_check);
    write_atomic(&preference_file()?, text.as_bytes())
}

pub fn enabled() -> Result<bool> { Ok(load()?.enabled) }

fn due(prefs: &mut Preferences, now: u64) -> bool {
    if !prefs.enabled { return false }
    if prefs.last_check > 0 && now >= prefs.last_check && now - prefs.last_check < DAY_SECONDS {
        return false;
    }
    prefs.last_check = now;
    true
}

struct ClaimLock(PathBuf);
impl Drop for ClaimLock {
    fn drop(&mut self) { let _ = fs::remove_dir(&self.0); }
}

/// Reserve one background check per 24 hours before contacting GitHub. Errors
/// never flip the user's opt-in back to off.
pub fn claim() -> Result<bool> {
    let path = preference_file()?;
    let parent = path.parent().context("Missing preference parent")?;
    fs::create_dir_all(parent)?;
    let lock = path.with_extension("lock");
    if let Err(error) = fs::create_dir(&lock) {
        if error.kind() != std::io::ErrorKind::AlreadyExists { return Err(error.into()) }
        let stale = fs::metadata(&lock)?.modified()?.elapsed().unwrap_or_default() > Duration::from_secs(3600);
        if !stale { return Ok(false) }
        fs::remove_dir(&lock).context("Cannot reclaim stale auto-update lock")?;
        if fs::create_dir(&lock).is_err() { return Ok(false) }
    }
    let _guard = ClaimLock(lock);
    let mut prefs = load()?;
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    if !due(&mut prefs, now) { return Ok(false) }
    save(prefs)?;
    Ok(true)
}

pub fn run(action: AutoUpdateAction) -> Result<()> {
    let mut prefs = load()?;
    match action {
        AutoUpdateAction::Status => {
            if prefs.enabled {
                println!("Automatic daily updates: on (every 24 hours)");
                if prefs.last_check > 0 { println!("Last automatic check (Unix): {}", prefs.last_check); }
            } else { println!("Automatic daily updates: off"); }
        }
        AutoUpdateAction::On => {
            let exe = env::current_exe()?.canonicalize()?;
            let previous = prefs;
            prefs.enabled = true;
            save(prefs)?;
            if let Err(error) = install_schedule(&exe) {
                save(previous).context("Could not restore preferences after schedule setup failed")?;
                return Err(error).context("Could not schedule daily automatic updates");
            }
            println!("Automatic daily updates enabled. Disable with '{APP_NAME} auto-update off'.");
        }
        AutoUpdateAction::Off => {
            // Save opt-out first: a scheduled process cannot re-enable itself.
            prefs.enabled = false;
            save(prefs)?;
            remove_schedule().context("Auto-updates are off, but schedule cleanup failed")?;
            println!("Automatic daily updates disabled.");
        }
    }
    Ok(())
}

fn execute(name: &str, args: &[&str]) -> Result<()> {
    let output = Command::new(name).args(args).output()
        .with_context(|| format!("Cannot run {name}"))?;
    if !output.status.success() {
        bail!("{name} failed: {}", String::from_utf8_lossy(&output.stderr).trim())
    }
    Ok(())
}

fn successful(name: &str, args: &[&str]) -> bool {
    Command::new(name).args(args).output().is_ok_and(|out| out.status.success())
}

fn xml_escape(value: &str) -> String {
    value.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;")
        .replace('"', "&quot;").replace('\'', "&apos;")
}

fn plist(exe: &Path, log: &Path) -> String {
    format!(r#"<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.{SERVICE_ID}</string>
<key>ProgramArguments</key><array><string>{}</string><string>upgrade</string><string>--automatic</string></array>
<key>RunAtLoad</key><true/>
<key>StartInterval</key><integer>86400</integer>
<key>StandardOutPath</key><string>{}</string>
<key>StandardErrorPath</key><string>{}</string>
</dict></plist>
"#, xml_escape(&exe.to_string_lossy()), xml_escape(&log.to_string_lossy()), xml_escape(&log.to_string_lossy()))
}

fn service_unit(exe: &Path) -> String {
    let path = exe.to_string_lossy().replace('%', "%%")
        .replace('\\', "\\\\").replace('"', "\\\"");
    format!("[Unit]\nDescription={APP_NAME} daily updates\n[Service]\nType=oneshot\nExecStart=\"{path}\" upgrade --automatic\n")
}

fn timer_unit() -> &'static str {
    "[Unit]\nDescription=Daily CLI release check\n[Timer]\nOnCalendar=daily\nPersistent=true\nRandomizedDelaySec=30min\n[Install]\nWantedBy=timers.target\n"
}

fn launchctl_domain() -> Result<String> {
    let out = Command::new("id").arg("-u").output()?;
    if !out.status.success() { bail!("Cannot resolve user id for launchd") }
    Ok(format!("gui/{}", String::from_utf8(out.stdout)?.trim()))
}

fn launchd_path() -> Result<PathBuf> {
    Ok(user_home()?.join("Library/LaunchAgents").join(format!("com.{SERVICE_ID}.plist")))
}

fn systemd_paths() -> Result<(PathBuf, PathBuf)> {
    let base = user_home()?.join(".config/systemd/user");
    Ok((base.join(format!("{SERVICE_ID}.service")), base.join(format!("{SERVICE_ID}.timer"))))
}

fn install_schedule(exe: &Path) -> Result<()> {
    if cfg!(target_os = "macos") {
        let log_dir = user_home()?.join("Library/Logs").join(APP_NAME);
        fs::create_dir_all(&log_dir)?;
        let path = launchd_path()?;
        write_atomic(&path, plist(exe, &log_dir.join("auto-update.log")).as_bytes())?;
        let domain = launchctl_domain()?;
        let label = format!("{domain}/com.{SERVICE_ID}");
        if successful("launchctl", &["print", &label]) { return Ok(()) }
        // Headless terminals have no GUI domain; the saved plist loads at login.
        if successful("launchctl", &["print", &domain]) {
            execute("launchctl", &["bootstrap", &domain, &path.to_string_lossy()])?;
        }
    } else if cfg!(target_os = "linux") {
        let (service, timer) = systemd_paths()?;
        write_atomic(&service, service_unit(exe).as_bytes())?;
        write_atomic(&timer, timer_unit().as_bytes())?;
        execute("systemctl", &["--user", "daemon-reload"])?;
        execute("systemctl", &["--user", "enable", "--now", &format!("{SERVICE_ID}.timer")])?;
    } else if cfg!(windows) {
        let task = format!(r"\{SERVICE_ID}");
        let action = format!("\"{}\" upgrade --automatic", exe.display());
        execute("schtasks.exe", &["/Create", "/F", "/SC", "DAILY", "/ST", "10:00", "/TN", &task, "/TR", &action])?;
    } else { bail!("Automatic updates not supported on this operating system") }
    Ok(())
}

fn remove_schedule() -> Result<()> {
    if cfg!(target_os = "macos") {
        let path = launchd_path()?;
        if path.exists() { fs::remove_file(&path)?; }
        let domain = launchctl_domain()?;
        let label = format!("{domain}/com.{SERVICE_ID}");
        if successful("launchctl", &["print", &label]) { execute("launchctl", &["bootout", &label])?; }
    } else if cfg!(target_os = "linux") {
        let (service, timer) = systemd_paths()?;
        let _ = execute("systemctl", &["--user", "disable", "--now", &format!("{SERVICE_ID}.timer")]);
        for path in [service, timer] {
            if path.exists() { fs::remove_file(path)?; }
        }
        execute("systemctl", &["--user", "daemon-reload"])?;
    } else if cfg!(windows) {
        let task = format!(r"\{SERVICE_ID}");
        if successful("schtasks.exe", &["/Query", "/TN", &task]) {
            execute("schtasks.exe", &["/Delete", "/F", "/TN", &task])?;
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn disabled_by_default_and_daily_claim_does_not_reset_opt_out() {
        let mut prefs = Preferences::default();
        assert!(!due(&mut prefs, 100_000));
        prefs.enabled = true;
        assert!(due(&mut prefs, 100_000));
        assert!(!due(&mut prefs, 100_001));
        assert!(!due(&mut prefs, 100_000 + DAY_SECONDS - 1));
        assert!(due(&mut prefs, 100_000 + DAY_SECONDS));
        prefs.enabled = false;
        assert!(!due(&mut prefs, 100_000 + DAY_SECONDS * 3));
    }

    #[test]
    fn schedule_definitions_are_daily_and_escaped() {
        let launch = plist(Path::new("/Applications/Some & App/tool"), Path::new("/logs/app.log"));
        assert!(launch.contains("<integer>86400</integer>"));
        assert!(launch.contains("upgrade</string><string>--automatic"));
        assert!(launch.contains("Some &amp; App"));
        assert!(timer_unit().contains("OnCalendar=daily"));
        assert!(timer_unit().contains("Persistent=true"));
        assert!(service_unit(Path::new("/home/app with spaces/tool")).contains("upgrade --automatic"));
    }
}
