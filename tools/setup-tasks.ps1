<#
  Portable setup for "Dolby Access Custom". Run SETUP.cmd from wherever this folder lives (any drive, any PC).
  Safe to re-run: every step checks first and only changes what is missing or points to an old location.

  Steps
    1. Equalizer APO installed and attached to the headphones (only checks; install is manual)
    2. Python + numpy/scipy/soundcard (offers pip install, asks first)
    3. audiohelper.exe (built with the C# compiler that ships with Windows)
    4. TDR Nova plugin copied into EAPO\config\VST (from .\vendor\VST)
    5. HeSuVi config: rebind to this PC's headphone GUID, restore golden files
    6. Logon task "HeSuVi Logon Check" pointing at THIS folder (asks first)
    7. Logon task "Dolby Access Custom Guard": background overlap guard (asks first)
#>
param([switch]$Yes)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Ctl = Join-Path $Root "hesuvi-control"
$Apo = "C:\Program Files\EqualizerAPO"
$TaskName = "HeSuVi Logon Check"

function Step($m) { Write-Host "`n== $m" -ForegroundColor Cyan }
function Ok($m) { Write-Host "  [OK]   $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [CHU Y] $m" -ForegroundColor Yellow }
function Ask($q) { if ($Yes) { return $true }; (Read-Host "  $q (y/n)") -match '^(y|c|yes|co)$' }

Write-Host "Dolby Access Custom - cai dat tai: $Root" -ForegroundColor White

Step "1. Equalizer APO"
if (Test-Path (Join-Path $Apo "EqualizerAPO.dll")) { Ok "Da cai Equalizer APO" }
else {
  Warn "Chua cai Equalizer APO. Tai tu https://sourceforge.net/projects/equalizerapo/ , khi cai tick tai nghe, khoi dong lai, roi chay lai SETUP."
  Warn "Neu muon dung che do Music Warm hien tai, cai them HeSuVi: https://sourceforge.net/projects/hesuvi/"
  exit 1
}

Step "2. Python"
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { Warn "Khong thay python. Cai Python 3.10+ tu https://www.python.org (tick 'Add to PATH'), roi chay lai."; exit 1 }
& python -c "import numpy, scipy, soundcard" 2>$null
if ($LASTEXITCODE -eq 0) { Ok "Python va thu vien numpy, scipy, soundcard da co" }
elseif (Ask "Thieu thu vien. Cai numpy, scipy, soundcard bang pip (~60 MB)?") { & python -m pip install --user numpy scipy soundcard; Ok "Da cai thu vien" }
else { Warn "Bo qua. Phan do (probe) va kiem tra nghe thu se khong chay." }

Step "3. audiohelper.exe"
$helper = Join-Path $Root "soundmode\native\audiohelper.exe"
if (Test-Path $helper) { Ok "Da co" } else { & cmd /c (Join-Path $Root "soundmode\native\build.cmd"); if (Test-Path $helper) { Ok "Da build" } else { Warn "Build loi" } }

Step "4. Plugin TDR Nova (leveler)"
$vstSrc = Join-Path $Root "vendor\VST\TDR Nova.dll"; $vstDst = Join-Path $Apo "config\VST\TDR Nova.dll"
if (Test-Path $vstDst) { Ok "Da co trong EqualizerAPO\config\VST" }
elseif (Test-Path $vstSrc) {
  try { New-Item -ItemType Directory -Force (Split-Path $vstDst) | Out-Null; Copy-Item $vstSrc $vstDst; Ok "Da chep plugin" }
  catch { Warn "Khong chep duoc (can quyen admin). Chuot phai SETUP.cmd > Run as administrator." }
} else { Warn "Khong co vendor\VST\TDR Nova.dll trong goi portable" }

Step "5. Cau hinh HeSuVi cho tai nghe tren may nay"
if (Test-Path (Join-Path $Apo "config\HeSuVi")) {
  & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Ctl "hesuvi.ps1") rebind
  # only restore golden files on a fresh PC: on this PC the live preset may be mid-tuning
  if (-not (Test-Path (Join-Path $Apo "config\HeSuVi\music-warm.txt"))) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Ctl "hesuvi.ps1") repair
  } else { Ok "Giu nguyen cau hinh dang dung (chay '4 - SUA LOI' neu muon khoi phuc ban chuan)" }
} else { Warn "Chua cai HeSuVi, bo qua buoc nay." }

Step "6. Tac vu kiem tra khi dang nhap"
$arg = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Ctl\hesuvi.ps1`" logon"
$t = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($t -and $t.Actions[0].Arguments -eq $arg) { Ok "Tac vu da tro dung thu muc nay" }
else {
  $why = if ($t) { "Tac vu dang tro toi thu muc cu: $($t.Actions[0].Arguments)" } else { "Chua co tac vu" }
  Warn $why
  if (Ask "Tao/cap nhat tac vu '$TaskName' chay khi dang nhap, tro toi thu muc nay?") {
    $a = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg
    if ($t) { Set-ScheduledTask -TaskName $TaskName -Action $a | Out-Null }
    else { Register-ScheduledTask -TaskName $TaskName -Action $a -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME) -Settings (New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries) | Out-Null }
    Ok "Da cap nhat tac vu"
  }
}

Step "7. Bao ve chong chong chay nen"
$GuardTask = "Dolby Access Custom Guard"
$pyw = Join-Path (Split-Path (Get-Command python).Source) "pythonw.exe"
$gt = Get-ScheduledTask -TaskName $GuardTask -ErrorAction SilentlyContinue
if ($gt -and $gt.Actions[0].WorkingDirectory -eq $Root -and $gt.Actions[0].Execute -eq $pyw) { Ok "Tac vu bao ve da tro dung thu muc nay" }
elseif (Ask "Tao tac vu '$GuardTask' chay an khi dang nhap (tu tat che do cua app khi Dolby/app khac cung xu ly)?") {
  $a = New-ScheduledTaskAction -Execute $pyw -Argument "-m soundmode guard" -WorkingDirectory $Root
  $s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
  if ($gt) { Set-ScheduledTask -TaskName $GuardTask -Action $a -Settings $s | Out-Null }
  else { Register-ScheduledTask -TaskName $GuardTask -Action $a -Settings $s -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME) | Out-Null }
  Start-ScheduledTask -TaskName $GuardTask
  Ok "Da tao va chay tac vu bao ve (nhat ky: guard.log)"
}

Step "8. Am thanh vom 7.1 (VB-CABLE -> tai nghe)"
$BridgeTask = "Dolby Access Custom 7.1 Bridge"
$capKey = Get-ChildItem "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture" | Where-Object {
  (Get-ItemProperty "$($_.PSPath)\Properties" -ErrorAction SilentlyContinue).'{a45c254e-df1c-4efd-8020-67d146a850e0},2' -eq "CABLE Output" } | Select-Object -First 1
if (-not $capKey) { Warn "Chua cai VB-CABLE (vendor\VBCABLE), bo qua 7.1." }
else {
  $capGuid = $capKey.PSChildName.Trim("{}")
  $bridge = Join-Path $Root "soundmode\native\bridge.exe"
  $bt = Get-ScheduledTask -TaskName $BridgeTask -ErrorAction SilentlyContinue
  if ($bt -and $bt.Actions[0].Execute -eq $bridge -and $bt.Actions[0].Arguments -eq $capGuid) { Ok "Bridge 7.1 da chay khi dang nhap" }
  elseif (Ask "Tao tac vu '$BridgeTask' chay an khi dang nhap (chuyen am tu CABLE ra tai nghe, thay cho 'Listen')?") {
    $a = New-ScheduledTaskAction -Execute $bridge -Argument $capGuid
    $s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
    if ($bt) { Set-ScheduledTask -TaskName $BridgeTask -Action $a -Settings $s | Out-Null }
    else { Register-ScheduledTask -TaskName $BridgeTask -Action $a -Settings $s -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME) | Out-Null }
    Ok "Da tao tac vu bridge 7.1"
  }
}

Step "Kiem tra tong the"
& python -m soundmode status
Write-Host "`nXong. Co the chay lai SETUP bat cu luc nao (vi du sau khi chuyen thu muc hoac ghep lai tai nghe)." -ForegroundColor Green
