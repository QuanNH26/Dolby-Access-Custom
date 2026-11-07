<#
  HeSuVi / Equalizer APO control for the "Dolby Atmos Music Warm" emulation on UGREEN HiTune Max5c.

  .\hesuvi.ps1 status          check everything (files, device, APO, Spatial sound)
  .\hesuvi.ps1 status -Listen  also play ~5 s of test noise and verify processing on the live audio path
  .\hesuvi.ps1 on | off        turn the whole chain (EQ + leveler) on/off - takes effect immediately
  .\hesuvi.ps1 dyn-on | dyn-off  only the Nova leveler/safety stages (EQ stays)
  .\hesuvi.ps1 repair          restore config files from .\golden (keeps the current on/off state)
  .\hesuvi.ps1 rebind          after re-pairing the headphones: point the config at the new device GUID
  .\hesuvi.ps1 save-golden     make the current config the new golden copy
  Add -Quiet to only print problems (used by the logon check).
#>
param([Parameter(Position = 0)][string]$Command = "status", [switch]$Listen, [switch]$Quiet)

$ErrorActionPreference = "Stop"
$Here    = Split-Path -Parent $MyInvocation.MyCommand.Path
$Golden  = Join-Path $Here "golden"
$Apo     = "C:\Program Files\EqualizerAPO"
$Cfg     = Join-Path $Apo "config"
$Hsv     = Join-Path $Cfg "HeSuVi"
$Vst     = Join-Path $Cfg "VST\TDR Nova.dll"
$DevName = "UGREEN HiTune Max5c Stereo"
$RenderKey = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render"
$EapoClsid = "EACD2258-FCAC-4FF4-B36D-419E924A6D79"
$Utf8 = New-Object System.Text.UTF8Encoding($false)
# file name in golden -> live path
$Files = [ordered]@{
  "config.txt" = Join-Path $Cfg "config.txt"
  "conv.txt" = Join-Path $Hsv "conv.txt"; "conv44.txt" = Join-Path $Hsv "conv44.txt"
  "matrix.txt" = Join-Path $Hsv "matrix.txt"; "postlude.txt" = Join-Path $Hsv "postlude.txt"
  "music-warm.txt" = Join-Path $Hsv "music-warm.txt"; "devna.txt" = Join-Path $Hsv "devna.txt"
  "conn.txt" = Join-Path $Hsv "conn.txt"; "gain.txt" = Join-Path $Hsv "gain.txt"
}
$script:Problems = 0

function Say($msg, $color = "Gray") { if (-not $Quiet) { Write-Host $msg -ForegroundColor $color } }
function Ok($msg)   { Say "  [OK]   $msg" Green }
function Bad($msg)  { $script:Problems++; Write-Host "  [LOI]  $msg" -ForegroundColor Red }
function Warn($msg) { Write-Host "  [CHU Y] $msg" -ForegroundColor Yellow }
function Write-Utf8($path, $text) { [IO.File]::WriteAllText($path, $text, $Utf8) }
function Read-Text($path) { [IO.File]::ReadAllText($path) }

function Get-Device {
  # the UGREEN stereo render endpoint: GUID, state, whether EAPO is attached, sample rate
  foreach ($k in Get-ChildItem $RenderKey) {
    $p = Get-ItemProperty (Join-Path $k.PSPath "Properties") -ErrorAction SilentlyContinue
    if (-not $p) { continue }
    $name = $p.'{a45c254e-df1c-4efd-8020-67d146a850e0},2'; $iface = $p.'{b3f8fa53-0004-438e-9003-51a46e139bfc},6'
    if ($iface -ne $DevName -or $name -ne "Headphones") { continue }
    $fx = Get-ItemProperty (Join-Path $k.PSPath "FxProperties") -ErrorAction SilentlyContinue
    $hasApo = $false; if ($fx) { $hasApo = [bool]($fx.PSObject.Properties | Where-Object { "$($_.Value)" -match $EapoClsid }) }
    $fmt = $p.'{f19f064d-082c-4e27-bc73-6882a1bb8e4c},0'; $rate = 0; if ($fmt) { $rate = [BitConverter]::ToUInt32($fmt, 12) }
    return [pscustomobject]@{ Guid = $k.PSChildName.Trim("{}").ToLower(); State = (Get-ItemProperty $k.PSPath).DeviceState; Apo = $hasApo; Rate = $rate }
  }
  return $null
}

function Get-Active { (Read-Text (Join-Path $Hsv "deact.txt")) -match "active=true" }

function Show-Status {
  Say "== HeSuVi / Equalizer APO ==" Cyan
  if (Get-Active) { Ok "HeSuVi dang BAT" } else { Warn "HeSuVi dang TAT (chay: hesuvi.ps1 on)" }
  $wc = Read-Text $Files["music-warm.txt"]
  $nVst = ([regex]::Matches($wc, "(?m)^\s*VSTPlugin:")).Count; $nOff = ([regex]::Matches($wc, "(?m)^\s*#\s*VSTPlugin:")).Count
  if ($nVst -eq 2) { Ok "Leveler TDR Nova dang BAT" } elseif ($nOff -eq 2) { Warn "Leveler TDR Nova dang TAT (chay: hesuvi.ps1 dyn-on)" } else { Bad "music-warm.txt khong co dong VSTPlugin hop le" }

  foreach ($f in $Files.Keys) {
    $live = $Files[$f]; $gold = Join-Path $Golden $f
    if (-not (Test-Path $live)) { Bad "$f bi mat"; continue }
    $l = (Read-Text $live) -replace "(?m)^(\s*)#\s*(VSTPlugin:)", '$1$2'   # dyn-off state is intentional, not drift
    if ($l.Trim() -ne (Read-Text $gold).Trim()) { Bad "$f khac ban chuan (HeSuVi GUI da ghi de?) -> chay: hesuvi.ps1 repair" }
  }
  if ($script:Problems -eq 0) { Ok "Tat ca file cau hinh khop ban chuan" }
  if (Test-Path $Vst) { Ok "Plugin TDR Nova co mat" } else { Bad "Thieu $Vst" }

  $d = Get-Device
  if (-not $d) { Bad "Khong tim thay tai nghe '$DevName' (chua ghep Bluetooth?)" }
  else {
    $want = ([regex]::Match((Read-Text $Files["devna.txt"]), '"([0-9a-f-]+)"')).Groups[1].Value
    if ($d.Guid -ne $want) { Bad "Tai nghe co GUID moi ($($d.Guid)) - da ghep lai Bluetooth -> chay: hesuvi.ps1 rebind" } else { Ok "GUID tai nghe khop cau hinh" }
    if ($d.Apo) { Ok "Equalizer APO dang gan vao tai nghe" } else { Bad "Equalizer APO KHONG gan vao tai nghe (Windows/driver update?) -> mo DeviceSelector.exe, tick 'Headphones (UGREEN...)', khoi dong lai" }
    if ($d.State -eq 1) { Ok "Tai nghe dang ket noi" } else { Warn "Tai nghe chua ket noi (state $($d.State))" }
    if ($d.Rate -in 44100, 48000) { Ok "Sample rate $($d.Rate) Hz" } elseif ($d.Rate) { Bad "Sample rate $($d.Rate) Hz - HeSuVi chi chay 44100/48000" }
  }
  if ($Listen) { Test-Live }
  if (-not $Quiet) { Write-Host "" }
  if ($script:Problems -eq 0) { Say "=> Moi thu on." Green } else { Write-Host "=> Co $script:Problems van de can xu ly (xem [LOI] o tren)." -ForegroundColor Red }
  Say "Nhac nho: Windows Sound > Headphones > Properties > Spatial sound phai la 'Off' (khong dung Dolby cung HeSuVi)." DarkGray
}

function Test-Live {
  Say "-- Kiem tra tren duong am thanh that (phat ~5 s noise nho) --" Cyan
  $py = Join-Path $Here "livecheck.py"
  $ErrorActionPreference = "Continue"   # soundcard prints harmless warnings on stderr
  $out = & python -I -W ignore $py 2>$null | Out-String
  $ErrorActionPreference = "Stop"
  Say $out.TrimEnd()
  $act = Get-Active
  if ($out -match "RESULT=FAIL") { Bad "Am thanh thuc te khong dung (xem dong '=>' o tren)" }
  elseif ($act -and $out -match "RESULT=OFF") { Bad "HeSuVi dang bat nhung am thanh KHONG duoc xu ly -> APO khong chay tren thiet bi nay (DeviceSelector) hoac thiet bi mac dinh khong phai tai nghe" }
  elseif (-not $act -and $out -match "RESULT=ONE") { Warn "HeSuVi dang tat nhung van co lop Warm -> co the Spatial sound (Dolby) dang bat" }
  else { Ok "Am thanh thuc te khop trang thai hien tai" }
}

function Set-Active([bool]$on) {
  Write-Utf8 (Join-Path $Hsv "deact.txt") ("Eval: active=" + $(if ($on) { "true" } else { "false" }))
  Say ("HeSuVi da " + $(if ($on) { "BAT" } else { "TAT" }) + " (co hieu luc ngay).") Green
}

function Set-Dyn([bool]$on) {
  $p = $Files["music-warm.txt"]; $t = Read-Text $p
  if ($on) { $t = $t -replace "(?m)^(\s*)#\s*(VSTPlugin:)", '$1$2' } else { $t = $t -replace "(?m)^(\s*)(VSTPlugin:)", '$1# $2' }
  Write-Utf8 $p $t
  Say ("Leveler TDR Nova da " + $(if ($on) { "BAT" } else { "TAT" }) + " (EQ van giu nguyen).") Green
}

function Repair {
  $dynWasOff = (Read-Text $Files["music-warm.txt"]) -match "(?m)^\s*#\s*VSTPlugin:"
  $n = 0
  foreach ($f in $Files.Keys) {
    $live = $Files[$f]; $gold = Join-Path $Golden $f
    $cur = ""; if (Test-Path $live) { $cur = (Read-Text $live) -replace "(?m)^(\s*)#\s*(VSTPlugin:)", '$1$2' }
    if ($cur.Trim() -ne (Read-Text $gold).Trim()) { Copy-Item $gold $live -Force; $n++; Say "  khoi phuc $f" Yellow }
  }
  if ($dynWasOff) { Set-Dyn $false | Out-Null }
  if ($n -eq 0) { Say "Khong co gi can khoi phuc." Green } else { Write-Host "Da khoi phuc $n file tu ban chuan." -ForegroundColor Green }
}

function Rebind {
  $d = Get-Device; if (-not $d) { throw "Khong tim thay tai nghe '$DevName'. Hay ket noi tai nghe truoc." }
  $old = ([regex]::Match((Read-Text $Files["devna.txt"]), '"([0-9a-f-]+)"')).Groups[1].Value
  if ($old -eq $d.Guid) { Say "GUID khong doi ($old)." Green }
  else {
    foreach ($f in "devna.txt", "music-warm.txt") {
      foreach ($p in $Files[$f], (Join-Path $Golden $f)) { Write-Utf8 $p ((Read-Text $p).Replace($old, $d.Guid)) }
    }
    Write-Host "Da chuyen cau hinh sang GUID moi $($d.Guid)." -ForegroundColor Green
  }
  if (-not $d.Apo) { Warn "Equalizer APO chua gan vao thiet bi moi: mo '$Apo\DeviceSelector.exe' (quyen admin), tick Headphones (UGREEN...), OK, roi khoi dong lai may." }
}

function Save-Golden {
  foreach ($f in $Files.Keys) { $t = (Read-Text $Files[$f]) -replace "(?m)^(\s*)#\s*(VSTPlugin:)", '$1$2'; Write-Utf8 (Join-Path $Golden $f) $t }
  Write-Host "Da luu cau hinh hien tai lam ban chuan." -ForegroundColor Green
}

function Logon-Check {
  # silent: repair drifted files, then pop up only for problems the user must fix by hand
  $log = Join-Path $Here "logon.log"
  $msgs = @()
  try {
    $script:Quiet = $true; Repair *> $null
    if (-not (Test-Path $Vst)) { $msgs += "Thieu plugin TDR Nova ($Vst)." }
    $d = Get-Device
    if ($d) {
      $want = ([regex]::Match((Read-Text $Files["devna.txt"]), '"([0-9a-f-]+)"')).Groups[1].Value
      if ($d.Guid -ne $want) { $msgs += "Tai nghe UGREEN co GUID moi (da ghep lai Bluetooth). Bam '7 - Sau khi ghep lai Bluetooth.cmd'." }
      if (-not $d.Apo) { $msgs += "Equalizer APO khong con gan vao tai nghe UGREEN (thuong do Windows/driver update). Mo DeviceSelector.exe, tick Headphones (UGREEN...), khoi dong lai." }
      if ($d.Rate -and $d.Rate -notin 44100, 48000) { $msgs += "Sample rate tai nghe la $($d.Rate) Hz; HeSuVi chi chay 44100/48000." }
    }
  } catch { $msgs += "Loi khi kiem tra: $_" }
  Add-Content $log ("{0}  {1}" -f (Get-Date -Format s), $(if ($msgs) { $msgs -join " | " } else { "OK" }))
  if ($msgs) {
    $sh = New-Object -ComObject WScript.Shell
    $sh.Popup(($msgs -join "`n`n") + "`n`nThu muc: $Here", 0, "HeSuVi - can kiem tra", 48) | Out-Null
  }
}

switch ($Command.ToLower()) {
  "logon"       { Start-Sleep -Seconds 20; Logon-Check }
  "status"      { Show-Status; if ($script:Problems) { exit 1 } }
  "on"          { Set-Active $true }
  "off"         { Set-Active $false }
  "dyn-on"      { Set-Dyn $true }
  "dyn-off"     { Set-Dyn $false }
  "repair"      { Repair }
  "rebind"      { Rebind }
  "save-golden" { Save-Golden }
  default       { Get-Help $MyInvocation.MyCommand.Path; exit 2 }
}
