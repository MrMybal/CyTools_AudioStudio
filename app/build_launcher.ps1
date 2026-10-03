# Compiles app/launcher.cpp into <root>/CyTools_AudioStudio.exe (subsystem WINDOWS: no console).
# Works from a normal PowerShell: MSVC is located with vswhere when cl.exe is not on PATH.
$ErrorActionPreference = 'Stop'
$appRoot = $PSScriptRoot
$toolRoot = Split-Path -Parent $appRoot
& (Join-Path $appRoot 'build_icon.ps1')
$build = Join-Path $toolRoot 'runtime\build'
New-Item -ItemType Directory -Force -Path $build | Out-Null
$source = Join-Path $appRoot 'launcher.cpp'
$resource = Join-Path $build 'launcher.res'
$resourceSource = Join-Path $appRoot 'launcher.rc'
$resourceFlags = "/nologo /I`"$appRoot`" /fo`"$resource`" `"$resourceSource`""
$output = Join-Path $toolRoot 'CyTools_AudioStudio.exe'
$flags = "/nologo /std:c++17 /MT /EHsc /O2 /W3 /Fo`"$build\\`" `"$source`" /Fe:`"$output`" /link /SUBSYSTEM:WINDOWS user32.lib `"$resource`""
if (Get-Command cl.exe -ErrorAction SilentlyContinue) {
    Push-Location $build
    try { cmd /c "rc $resourceFlags && cl $flags" } finally { Pop-Location }
} else {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (-not (Test-Path -LiteralPath $vswhere)) { throw 'Visual Studio (vswhere.exe) not found: install the C++ build tools or open a developer prompt.' }
    $install = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if (-not $install) { throw 'No Visual Studio installation with the C++ tools was found.' }
    $vcvars = Join-Path $install 'VC\Auxiliary\Build\vcvars64.bat'
    if (-not (Test-Path -LiteralPath $vcvars)) { throw "vcvars64.bat not found in $install." }
    Push-Location $build
    try { cmd /c "`"$vcvars`" >nul 2>&1 && rc $resourceFlags && cl $flags" } finally { Pop-Location }
}
if ($LASTEXITCODE -ne 0) { throw 'Launcher compilation failed.' }
Write-Host "Built $output"
