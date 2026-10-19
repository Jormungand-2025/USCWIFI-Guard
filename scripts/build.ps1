$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $repoRoot
try {
    python scripts/generate_icon.py
    if ($LASTEXITCODE -ne 0) { throw 'Icon generation failed.' }
    $iconPath = Join-Path $repoRoot 'assets/campus_guard.ico'
    python -m PyInstaller --noconfirm --onefile --windowed --name USCWIFI_Guard --icon $iconPath --distpath dist --workpath build --specpath build src/campus_guard.py
    if ($LASTEXITCODE -ne 0) { throw 'Executable build failed.' }
    Write-Host 'Build complete: dist/USCWIFI_Guard.exe'
} finally {
    Pop-Location
}
