param(
    [switch]$Upgrade,
    [switch]$Check,
    [string]$Target,
    [int]$WaitForPid = 0
)
$ErrorActionPreference = 'Stop'
$Cli = '__CLI__'
$Repo = 'https://github.com/__OWNER__/__REPO__'
if ($Check) {
    if ($Target -and (Test-Path $Target)) { & $Target --version }
    else { Write-Host 'Check the installed CLI with --version' }
    $Latest = & curl.exe -sSIL --max-time 20 -o NUL -w '%{url_effective}' "$Repo/releases/latest"
    if ($LASTEXITCODE -ne 0) { throw 'Could not resolve latest GitHub release' }
    Write-Host "Latest release: $Latest"
    exit 0
}
if ($Upgrade -and $Target) {
    if (-not [IO.Path]::IsPathRooted($Target) -or -not (Test-Path $Target)) { throw 'Upgrade target must be an existing absolute path' }
    # Override cargo-dist's chosen directory to update the current executable.
    $env:__CLI_ENV___INSTALL_DIR = Split-Path -Parent $Target
}
$Stage = Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $Stage | Out-Null
try {
    $Installer = Join-Path $Stage 'installer.ps1'
    Invoke-WebRequest "$Repo/releases/latest/download/${Cli}-installer.ps1" -OutFile $Installer
    if ($WaitForPid -gt 0) {
        try { Wait-Process -Id $WaitForPid -Timeout 120 -ErrorAction SilentlyContinue } catch { }
    }
    & $Installer
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw "cargo-dist installer exited $LASTEXITCODE" }
} finally {
    Remove-Item $Stage -Recurse -Force -ErrorAction SilentlyContinue
    if ($Upgrade -and $WaitForPid -gt 0) {
        Remove-Item $PSCommandPath -Force -ErrorAction SilentlyContinue
    }
}
