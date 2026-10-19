$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $repoRoot
try {
    python -m PyInstaller --noconfirm --onefile --windowed --name USCWIFI_Guard --distpath dist --workpath build --specpath build src/campus_guard.py
    if ($LASTEXITCODE -ne 0) { throw 'Executable build failed.' }
    Write-Host 'Build complete: dist/USCWIFI_Guard.exe'
} finally {
    Pop-Location
}
