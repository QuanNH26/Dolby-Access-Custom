<#
  build.ps1 - turn this source folder into the files users get.

    powershell -ExecutionPolicy Bypass -File build.ps1            # build everything
    powershell -ExecutionPolicy Bypass -File build.ps1 -SkipSetup # only the exes + runtime (to run from source)

  Output
    Dolby Access Custom.exe                 launcher, next to the sources (run the app straight from this folder)
    dist\DolbyAccessCustom-Setup-<ver>.exe  one-file installer for users: no admin, installs per user, keeps settings on update

  Steps
    1. launcher exe + native helpers (C# compiler that ships with Windows, no downloads)
    2. runtime\  portable Python + packages (launcher\make-runtime.ps1, only if missing)
    3. vendor\installers  Equalizer APO + HeSuVi installers (downloaded once from SourceForge, MD5-checked)
    4. stage the app (no backups / state / measurement runs / caches) -> zip -> append to the setup stub
  vendor\VBCABLE is left out unless -IncludeVBCable (VB-Audio does not allow redistributing it without a licence).
#>
param([switch]$SkipSetup, [switch]$IncludeVBCable)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Ver = (Get-Content (Join-Path $Root 'VERSION') -Raw).Trim()
$Csc = "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
function Step($m) { Write-Host "`n== $m" -ForegroundColor Cyan }

Step "1. Launcher + native helpers (v$Ver)"
& $Csc /nologo /optimize /target:winexe "/win32icon:$Root\launcher\app.ico" /r:System.Windows.Forms.dll "/out:$Root\Dolby Access Custom.exe" "$Root\launcher\launcher.cs"
if ($LASTEXITCODE) { throw 'launcher build failed' }
& cmd /c "`"$Root\soundmode\native\build.cmd`"" | Out-Host
if ($LASTEXITCODE) { throw 'native helper build failed' }

Step '2. Portable Python runtime'
if (Test-Path "$Root\runtime\pythonw.exe") { Write-Host '  runtime\ already there' }
else { & powershell -NoProfile -ExecutionPolicy Bypass -File "$Root\launcher\make-runtime.ps1"; if ($LASTEXITCODE) { throw 'runtime build failed' } }

Step '3. Third-party installers'
$inst = Join-Path $Root 'vendor\installers'; New-Item -ItemType Directory -Force $inst | Out-Null
$want = @{
  'EqualizerAPO-x64-1.4.2.exe' = @('https://downloads.sourceforge.net/project/equalizerapo/1.4.2/EqualizerAPO-x64-1.4.2.exe', '410aab9749ae4673b950bc29a4eb226f')
  'HeSuVi_2.0.0.1.exe'         = @('https://downloads.sourceforge.net/project/hesuvi/HeSuVi_2.0.0.1.exe', '7e4e34edcce385a75ee310af31da380a')
}
foreach ($n in $want.Keys) {
  $p = Join-Path $inst $n
  if (-not (Test-Path $p)) {
    # curl follows SourceForge's mirror redirects (Invoke-WebRequest can get an HTML page instead of the file)
    Write-Host "  downloading $n"
    & curl.exe -fsSL --retry 4 --retry-delay 5 -o $p $want[$n][0]
    if ($LASTEXITCODE) { throw "download of $n failed" }
  }
  if ((Get-FileHash $p -Algorithm MD5).Hash.ToLower() -ne $want[$n][1]) { Remove-Item $p; throw "$n does not match the official checksum" }
  Write-Host "  $n OK"
}
if ($SkipSetup) { Write-Host "`nDone (no setup built)." -ForegroundColor Green; return }

Step '4. Setup exe'
$dist = Join-Path $Root 'dist'; $stage = Join-Path $dist 'stage'
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force $stage | Out-Null
$items = 'Dolby Access Custom.exe', 'VERSION', 'LICENSE', 'README.md', 'gui', 'soundmode', 'modes', 'hesuvi-control', 'runtime', 'vendor', 'dolby-probe'
foreach ($i in $items) { Copy-Item (Join-Path $Root $i) $stage -Recurse -Force }
# never ship local data / caches / dev leftovers
Get-ChildItem $stage -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
foreach ($x in 'dolby-probe\runs', 'vendor\VBCABLE\VBCABLE_Driver_Pack45.zip') { $p = Join-Path $stage $x; if (Test-Path $p) { Remove-Item $p -Recurse -Force } }
if (-not $IncludeVBCable) { Remove-Item (Join-Path $stage 'vendor\VBCABLE') -Recurse -Force -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Force (Join-Path $stage 'dolby-probe\runs') | Out-Null

$zip = Join-Path $dist 'payload.zip'; if (Test-Path $zip) { Remove-Item $zip }
Add-Type -AssemblyName System.IO.Compression.FileSystem
[IO.Compression.ZipFile]::CreateFromDirectory($stage, $zip, [IO.Compression.CompressionLevel]::Optimal, $false)

$stub = Join-Path $dist 'setup-stub.exe'
& $Csc /nologo /optimize /target:winexe "/win32icon:$Root\launcher\app.ico" /r:System.Windows.Forms.dll /r:System.Drawing.dll `
  /r:System.IO.Compression.dll /r:System.IO.Compression.FileSystem.dll "/out:$stub" "$Root\installer\setup.cs"
if ($LASTEXITCODE) { throw 'setup build failed' }

$out = Join-Path $dist "DolbyAccessCustom-Setup-$Ver.exe"
$fs = [IO.File]::Create($out)
try {
  foreach ($f in $stub, $zip) { $b = [IO.File]::OpenRead($f); try { $b.CopyTo($fs) } finally { $b.Close() } }
  $len = (Get-Item $zip).Length
  $fs.Write([BitConverter]::GetBytes([long]$len), 0, 8)
  $fs.Write([Text.Encoding]::ASCII.GetBytes('DACSETUP'), 0, 8)
} finally { $fs.Close() }
Remove-Item $stage -Recurse -Force; Remove-Item $zip, $stub
Write-Host ("`nDone: {0} ({1:N0} MB)" -f $out, ((Get-Item $out).Length / 1MB)) -ForegroundColor Green
