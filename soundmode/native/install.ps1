# install.ps1 - one-click install of what the sound modes need. Run elevated by gui/api.py (one UAC prompt).
# Uses the installers kept in <project>\vendor\installers (portable, checked against SourceForge's MD5).
# Progress goes to -Out as one JSON object per line: {"step","state":"run|ok|skip|fail","text"}.
#   1. Equalizer APO   (silent install)
#   2. HeSuVi          (silent install into EqualizerAPO\config\HeSuVi)
#   3. Plugins         (vendor\VST\*.dll -> EqualizerAPO\config\VST)
#   4. Config          (golden HeSuVi files that are missing + postlude that includes the app's soundmode.txt)
#   5. Device Selector (opens; the user ticks the headphones, Windows then asks to restart)
param([string]$Root, [string]$Out, [string]$Device = '', [switch]$KeepOriginal, [switch]$NoSelector)
$ErrorActionPreference = 'Stop'
$Apo = 'C:\Program Files\EqualizerAPO'
$Inst = Join-Path $Root 'vendor\installers'
$Golden = Join-Path $Root 'hesuvi-control\golden'
$Md5 = @{ 'EqualizerAPO-x64-1.4.2.exe' = '410aab9749ae4673b950bc29a4eb226f'; 'HeSuVi_2.0.0.1.exe' = '7e4e34edcce385a75ee310af31da380a' }
Set-Content -Path $Out -Value '' -Encoding UTF8

function Log($step, $state, $text) {
    Add-Content -Path $Out -Encoding UTF8 -Value (([ordered]@{ step = $step; state = $state; text = $text }) | ConvertTo-Json -Compress)
}
function Installer($name) {
    $p = Join-Path $Inst $name
    if (-not (Test-Path $p)) { throw "$name is missing from vendor\installers" }
    $h = (Get-FileHash $p -Algorithm MD5).Hash.ToLower()
    if ($h -ne $Md5[$name]) { throw "$name does not match the official checksum (got $h), not running it" }
    return $p
}
function Run($exe, $argList) {
    $p = Start-Process -FilePath $exe -ArgumentList $argList -Wait -PassThru
    if ($p.ExitCode -ne 0) { throw "$(Split-Path $exe -Leaf) exited with code $($p.ExitCode)" }
}

$failed = $false
try {
    Log 'eapo' 'run' 'Installing Equalizer APO 1.4.2'
    if (Test-Path (Join-Path $Apo 'EqualizerAPO.dll')) { Log 'eapo' 'skip' 'Equalizer APO is already installed' }
    else {
        $p = Start-Process -FilePath (Installer 'EqualizerAPO-x64-1.4.2.exe') -ArgumentList '/S' -PassThru
        while (-not $p.HasExited) {
            Get-Process DeviceSelector -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
            Start-Sleep -Milliseconds 500
        }
        if (-not (Test-Path (Join-Path $Apo 'EqualizerAPO.dll'))) { throw 'install finished but EqualizerAPO.dll is not there' }; Log 'eapo' 'ok' 'Equalizer APO installed' }
} catch { Log 'eapo' 'fail' "$($_.Exception.Message)"; $failed = $true }

if (-not $failed) {
    try {
        Log 'hesuvi' 'run' 'Installing HeSuVi 2.0.0.1'
        if (Test-Path (Join-Path $Apo 'config\HeSuVi\hesuvi.txt')) { Log 'hesuvi' 'skip' 'HeSuVi is already installed' }
        else { Run (Installer 'HeSuVi_2.0.0.1.exe') '/S'; if (-not (Test-Path (Join-Path $Apo 'config\HeSuVi\hesuvi.txt'))) { throw 'install finished but HeSuVi\hesuvi.txt is not there' }; Log 'hesuvi' 'ok' 'HeSuVi installed' }
    } catch { Log 'hesuvi' 'fail' "$($_.Exception.Message)"; $failed = $true }
}

if (-not $failed) {
    try {
        Log 'vst' 'run' 'Copying the leveler plugins'
        $dst = Join-Path $Apo 'config\VST'; New-Item -ItemType Directory -Force $dst | Out-Null
        $n = 0
        foreach ($f in Get-ChildItem (Join-Path $Root 'vendor\VST') -Filter *.dll) {
            $t = Join-Path $dst $f.Name
            if (-not (Test-Path $t)) { Copy-Item $f.FullName $t; $n++ }
        }
        Log 'vst' ($(if ($n) { 'ok' } else { 'skip' })) ($(if ($n) { "Copied $n plugin(s)" } else { 'Plugins already in place' }))
    } catch { Log 'vst' 'fail' "$($_.Exception.Message)"; $failed = $true }
}

if (-not $failed) {
    try {
        Log 'config' 'run' 'Setting up the HeSuVi files'
        $hsv = Join-Path $Apo 'config\HeSuVi'; $n = 0
        $bk = Join-Path $Root ('backups\install-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
        foreach ($f in 'conv.txt', 'conv44.txt', 'matrix.txt', 'music-warm.txt', 'devna.txt', 'conn.txt', 'gain.txt', 'postlude.txt') {
            $live = Join-Path $hsv $f; $gold = Join-Path $Golden $f
            $force = $f -eq 'postlude.txt' -and -not ((Test-Path $live) -and (Get-Content $live -Raw) -match 'soundmode\.txt')
            if (-not (Test-Path $live) -or $force) {
                if (Test-Path $live) { New-Item -ItemType Directory -Force $bk | Out-Null; Copy-Item $live (Join-Path $bk $f) }
                Copy-Item $gold $live -Force; $n++
            }
        }
        $deact = Join-Path $hsv 'deact.txt'
        if (-not (Test-Path $deact)) { Set-Content $deact 'Eval: active=false' -Encoding ASCII; $n++ }
        # the app writes soundmode.txt / deact.txt from a normal (non-admin) window: let Users modify the HeSuVi folder
        & icacls $hsv /grant '*S-1-5-32-545:(OI)(CI)M' /T /Q | Out-Null
        Log 'config' 'ok' "Prepared $n file(s); the app can now switch modes without admin"
    } catch { Log 'config' 'fail' "$($_.Exception.Message)"; $failed = $true }
}

if (-not $failed -and $Device) {
    try {
        Log 'attach' 'run' 'Connecting Equalizer APO to the chosen device (sound drops for a few seconds)'
        $r = Join-Path $Root 'backups\attach-last.json'
        $a = @{ Action = 'attach'; Device = $Device; Root = $Root; Out = $r }; if ($KeepOriginal) { $a.KeepOriginal = $true }
        & (Join-Path $Root 'soundmode\native\attach.ps1') @a
        $j = Get-Content $r -Raw | ConvertFrom-Json
        if (-not $j.ok) { throw $j.error }
        Log 'attach' 'ok' "Connected to $($j.name)"
    } catch { Log 'attach' 'fail' "$($_.Exception.Message)"; $failed = $true }
}
Log 'done' ($(if ($failed) { 'fail' } else { 'ok' })) ($(if ($failed) { 'Stopped at the step above' } else { 'All set: the sound modes now run on your device.' }))
