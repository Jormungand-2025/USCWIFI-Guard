$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$previousTclLibrary = $env:TCL_LIBRARY
$previousTkLibrary = $env:TK_LIBRARY
Push-Location -LiteralPath $repoRoot
try {
    $pythonBase = (& python -c "import sys; print(sys.base_prefix)").Trim()
    $tkVersion = (& python -c "import _tkinter; print(_tkinter.TCL_VERSION)").Trim()
    $tclLibrary = Join-Path (Join-Path $pythonBase 'tcl') ('tcl' + $tkVersion)
    $tkLibrary = Join-Path (Join-Path $pythonBase 'tcl') ('tk' + $tkVersion)
    if (Test-Path -LiteralPath $tclLibrary) { $env:TCL_LIBRARY = $tclLibrary }
    if (Test-Path -LiteralPath $tkLibrary) { $env:TK_LIBRARY = $tkLibrary }

    $appSource = Get-Content -LiteralPath (Join-Path $repoRoot 'src/campus_guard.py') -Raw
    $versionMatch = [regex]::Match($appSource, "(?m)^APP_VERSION = '([0-9]+\.[0-9]+\.[0-9]+)'")
    if (-not $versionMatch.Success) { throw 'Application version not found.' }
    $exeName = 'USCWIFI_Guard_v' + $versionMatch.Groups[1].Value
    python scripts/generate_icon.py
    if ($LASTEXITCODE -ne 0) { throw 'Icon generation failed.' }
    $iconPath = Join-Path $repoRoot 'assets/campus_guard.ico'
    python -m PyInstaller --clean --noconfirm --onefile --windowed --name $exeName --icon $iconPath --distpath dist --workpath build --specpath build src/campus_guard.py
    if ($LASTEXITCODE -ne 0) { throw 'Executable build failed.' }
    Write-Host "Build complete: dist/$exeName.exe"
} finally {
    if ($null -eq $previousTclLibrary) { Remove-Item Env:TCL_LIBRARY -ErrorAction SilentlyContinue }
    else { $env:TCL_LIBRARY = $previousTclLibrary }
    if ($null -eq $previousTkLibrary) { Remove-Item Env:TK_LIBRARY -ErrorAction SilentlyContinue }
    else { $env:TK_LIBRARY = $previousTkLibrary }
    Pop-Location
}
