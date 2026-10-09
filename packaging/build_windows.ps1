# Builds UbiClipper for Windows: a folder with the official Python inside,
# all packages, FFmpeg and the app, then UbiClipper-Setup-<ver>.exe (Inno
# Setup) and UbiClipper-<ver>-portable.zip.
#
# Runs on GitHub's Windows machines (.github/workflows/build.yml) and works
# the same on your own PC:
#     powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
# Needs: 64-bit Python 3.12 from python.org (the one that runs this script is
# copied), Inno Setup 6 (choco install innosetup / winget install JRSoftware.InnoSetup).

param(
    [string]$Python = "python",
    [string]$Out = "dist",
    [switch]$NoInstaller
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # Invoke-WebRequest is 10x faster without it
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Version = (& $Python -c "print(open('clipper/__init__.py').read().split('__version__ = ')[1].split()[0].strip(chr(34)))").Trim()
Write-Host "== UbiClipper $Version"

$Stage = Join-Path $Out "UbiClipper"
if (Test-Path $Out) { Remove-Item -Recurse -Force $Out }
New-Item -ItemType Directory -Force $Stage | Out-Null

# ------------------------------------------------------------------ Python
# The official python.org build (signed by the Python Software Foundation),
# copied as-is so Windows / Smart App Control trusts it like any Python.
$PyHome = (& $Python -c "import sys; print(sys.base_prefix)").Trim()
$PyVer = (& $Python -c "import sys; print('%d.%d' % sys.version_info[:2])").Trim()
if ($PyVer -ne "3.12") { Write-Warning "Built and tested with Python 3.12; this is $PyVer" }
Write-Host "== Copying Python $PyVer from $PyHome"
$PyDst = Join-Path $Stage "python"
robocopy $PyHome $PyDst /E /NFL /NDL /NJH /NJS /NP /XD "__pycache__" "test" "tests" "idle_test" "Scripts" "Doc" "Tools" "site-packages" | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE)" }
New-Item -ItemType Directory -Force (Join-Path $PyDst "Lib\site-packages") | Out-Null
foreach ($f in @("python.exe", "pythonw.exe", "Lib\tkinter\__init__.py", "DLLs\_tkinter.pyd", "tcl")) {
    if (-not (Test-Path (Join-Path $PyDst $f))) { throw "Python copy is missing $f (is this the python.org build with Tcl/Tk?)" }
}
$Py = Join-Path $PyDst "python.exe"

Write-Host "== Installing packages"
& $Py -m ensurepip --default-pip | Out-Null
& $Py -m pip install --disable-pip-version-check --no-warn-script-location -q --upgrade pip
& $Py -m pip install --disable-pip-version-check --no-warn-script-location -q -r requirements.txt -r requirements-optional.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
# pip's .exe launchers point at this build machine; the app doesn't use them
Remove-Item -Recurse -Force (Join-Path $PyDst "Scripts") -ErrorAction SilentlyContinue
Get-ChildItem $PyDst -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

# ------------------------------------------------------------------ FFmpeg
# Gyan's release "essentials" build: the one `winget install Gyan.FFmpeg` gets,
# with libass for burning subtitles.
Write-Host "== FFmpeg"
$FfZip = Join-Path $env:TEMP "ffmpeg-release-essentials.zip"
if (-not (Test-Path $FfZip)) {
    Invoke-WebRequest "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -OutFile $FfZip
}
$FfTmp = Join-Path $env:TEMP "ffmpeg-unpacked"
if (Test-Path $FfTmp) { Remove-Item -Recurse -Force $FfTmp }
Expand-Archive $FfZip $FfTmp
$FfDir = Get-ChildItem $FfTmp -Directory | Select-Object -First 1
New-Item -ItemType Directory -Force (Join-Path $Stage "ffmpeg\bin") | Out-Null
Copy-Item (Join-Path $FfDir.FullName "bin\ffmpeg.exe"), (Join-Path $FfDir.FullName "bin\ffprobe.exe") (Join-Path $Stage "ffmpeg\bin")
Copy-Item (Join-Path $FfDir.FullName "LICENSE") (Join-Path $Stage "ffmpeg\LICENSE.txt") -ErrorAction SilentlyContinue
Copy-Item (Join-Path $FfDir.FullName "README.txt") (Join-Path $Stage "ffmpeg\README.txt") -ErrorAction SilentlyContinue

# ------------------------------------------------------------------ the app
Write-Host "== App files"
$Skip = @(".git", ".github", "packaging", $Out, "build", "__pycache__", "tests")
Get-ChildItem $Root -Force | Where-Object {
    $Skip -notcontains $_.Name -and $_.Name -notlike ".*" -and
    @("run_windows.bat", "install_gpu.bat", "corrections.txt") -notcontains $_.Name -and
    $_.Name -notlike ".installed_*" -and $_.Name -ne ".models_ok"
} | ForEach-Object { Copy-Item $_.FullName (Join-Path $Stage $_.Name) -Recurse }
Get-ChildItem $Stage -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Set-Content (Join-Path $Stage "ubiclipper.build") "UbiClipper $Version" -Encoding ascii
Copy-Item (Join-Path $PSScriptRoot "Start UbiClipper.bat") $Stage

# Compile once so the first start is quick (errors are ignored on purpose:
# some packages ship Python 2 test files)
& $Py -m compileall -q -j 0 $Stage 2>$null | Out-Null

# ------------------------------------------------------------------ smoke test
Write-Host "== Smoke test"
& $Py (Join-Path $Stage "check_setup.py")
if ($LASTEXITCODE -ne 0) { throw "check_setup found problems" }

# ------------------------------------------------------------------ outputs
Write-Host "== Portable zip"
$Zip = Join-Path $Out "UbiClipper-$Version-portable.zip"
tar.exe -a -c -f $Zip -C $Out UbiClipper
if ($LASTEXITCODE -ne 0) { throw "zip failed" }

if (-not $NoInstaller) {
    Write-Host "== Installer"
    $Iscc = (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source
    if (-not $Iscc) {
        foreach ($p in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
                         "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")) {
            if (Test-Path $p) { $Iscc = $p; break }
        }
    }
    if (-not $Iscc) { throw "Inno Setup 6 not found (choco install innosetup)" }
    & $Iscc /Q "/DAppVersion=$Version" "/DStageDir=$(Resolve-Path $Stage)" "/DOutDir=$(Resolve-Path $Out)" (Join-Path $PSScriptRoot "ubiclipper.iss")
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
}

Get-ChildItem $Out -File | ForEach-Object { "{0,-45} {1,8:N0} MB" -f $_.Name, ($_.Length / 1MB) }
exit 0
