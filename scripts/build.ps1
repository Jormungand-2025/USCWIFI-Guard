$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $repoRoot
try {
    $appSource = Get-Content -LiteralPath (Join-Path $repoRoot 'src/campus_guard.py') -Raw
    $versionMatch = [regex]::Match($appSource, "(?m)^APP_VERSION = '([0-9]+\.[0-9]+\.[0-9]+)'")
    if (-not $versionMatch.Success) { throw 'Application version not found.' }
    $exeName = 'USCWIFI_Guard_v' + $versionMatch.Groups[1].Value
    python scripts/generate_icon.py
    if ($LASTEXITCODE -ne 0) { throw 'Icon generation failed.' }
    $iconPath = Join-Path $repoRoot 'assets/campus_guard.ico'
    python -m PyInstaller --noconfirm --onefile --windowed --name $exeName --icon $iconPath --distpath dist --workpath build --specpath build src/campus_guard.py
    if ($LASTEXITCODE -ne 0) { throw 'Executable build failed.' }
    Write-Host "Build complete: dist/$exeName.exe"
} finally {
    Pop-Location
}
