# attach.ps1 - attach / detach Equalizer APO on ONE playback device, the same registry changes Equalizer APO's own
# Device Selector makes (EqualizerAPO 1.4 DeviceAPOInfo::install / uninstall, install version 2), so the app can do it
# without that window. Run elevated by gui/api.py (one UAC prompt). Result JSON goes to -Out.
#   -Action attach  -Device <endpoint guid>  [-KeepOriginal]   keep the maker's effect (Nahimic, Realtek...) chained behind EAPO
#   -Action detach  -Device <endpoint guid>                    put the device back exactly as it was
# The FxProperties key is exported to <project>\backups before any change. Windows Audio is restarted afterwards
# (instead of a reboot) so the change is live straight away.
param([ValidateSet('attach', 'detach')][string]$Action, [string]$Device, [string]$Root, [string]$Out, [switch]$KeepOriginal, [switch]$NoRestart)
$ErrorActionPreference = 'Stop'
$res = [ordered]@{ ok = $false; action = $Action; device = $Device; steps = @() }
function Done { $res | ConvertTo-Json -Depth 4 | Set-Content -Path $Out -Encoding UTF8; exit }
function Note($t) { $script:res.steps += $t }

try {
    $g = '{' + $Device.Trim('{}').ToLower() + '}'
    $ep = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render\$g"
    $fx = "$ep\FxProperties"
    $child = "HKLM:\SOFTWARE\EqualizerAPO\Child APOs\$g"
    if (-not (Test-Path $ep)) { throw "playback device $g not found" }
    $props = Get-ItemProperty "$ep\Properties"
    $name = "$($props.'{a45c254e-df1c-4efd-8020-67d146a850e0},2') $($props.'{b3f8fa53-0004-438e-9003-51a46e139bfc},6')"
    if ($name -match 'Hands-Free') { throw "refusing to touch a Hands-Free (call) device: $name" }
    $res.name = $name.Trim()

    $PRE = '{EACD2258-FCAC-4FF4-B36D-419E924A6D79}'; $POST = '{EC1CC9CE-FAED-4822-828A-82A81A6F018F}'
    $F = '{d04e05a6-594b-4fb6-a80d-01af5eed7d1d}'
    $LFX = "$F,1"; $GFX = "$F,2"; $SFX = "$F,5"; $MFX = "$F,6"; $EFX = "$F,7"
    $ALL = @($LFX, $GFX, $SFX, $MFX, $EFX)
    $MODES = @{ $SFX = '{d3993a3f-99c2-4402-b5ec-a92a0367664b},5'; $MFX = '{d3993a3f-99c2-4402-b5ec-a92a0367664b},6'; $EFX = '{d3993a3f-99c2-4402-b5ec-a92a0367664b},7' }
    $DEFAULT_MODE = '{C18E2F7E-933D-4965-B7D1-1EEF228D2AF3}'
    $DISABLE = '{1da5d803-d492-4edd-8c23-e0c0ffee7f0e},5'

    function Get-Val($path, $n) { $i = Get-Item $path -ErrorAction SilentlyContinue; if ($i -and ($i.GetValueNames() -contains $n)) { return $i.GetValue($n) }; return $null }
    function Is-Eapo($v) { "$v".ToUpper() -in @($PRE, $POST) }
    # the endpoint keys only grant Administrators SetValue + QueryValues; PowerShell's *-ItemProperty asks for more and is
    # refused ("Requested registry access is not allowed"), so write them through .NET with exactly those rights
    $MMD = "SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render\$g"
    function Open-W($sub) {
        $k = [Microsoft.Win32.Registry]::LocalMachine.OpenSubKey("$MMD\$sub", [Microsoft.Win32.RegistryKeyPermissionCheck]::ReadWriteSubTree,
            [System.Security.AccessControl.RegistryRights]'SetValue, QueryValues')
        if (-not $k) { throw "cannot open $sub of the device" }; return $k
    }
    function EpSet($sub, $n, $v, $kind) { $k = Open-W $sub; try { $k.SetValue($n, $v, [Microsoft.Win32.RegistryValueKind]$kind) } finally { $k.Close() } }
    function EpDel($sub, $n) { $k = Open-W $sub; try { if ($k.GetValueNames() -contains $n) { $k.DeleteValue($n) } } finally { $k.Close() } }

    if (Test-Path $fx) {
        $bkDir = Join-Path $Root 'backups'; New-Item -ItemType Directory -Force $bkDir | Out-Null
        $bk = Join-Path $bkDir ("eapo-$Action-" + $Device.Trim('{}') + '-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.reg')
        & reg.exe export ($fx -replace '^HKLM:', 'HKLM') $bk /y | Out-Null
        $res.backup = $bk
    }

    if ($Action -eq 'attach') {
        # the two checks Device Selector runs at start-up (protected audiodg off, APO COM registration present)
        $dg = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Audio'
        if ((Get-Val $dg 'DisableProtectedAudioDG') -ne 1) { if (-not (Test-Path $dg)) { New-Item $dg -Force | Out-Null }; Set-ItemProperty $dg 'DisableProtectedAudioDG' 1 -Type DWord }
        if (-not (Test-Path "Registry::HKEY_CLASSES_ROOT\CLSID\$PRE") -or -not (Test-Path "Registry::HKEY_CLASSES_ROOT\CLSID\$POST")) {
            Start-Process regsvr32.exe -ArgumentList '/s', '"C:\Program Files\EqualizerAPO\EqualizerAPO.dll"' -Wait
        }
        $installed = (Test-Path $fx) -and ($ALL | Where-Object { Is-Eapo (Get-Val $fx $_) })
        if ($installed) { Note 'Equalizer APO was already attached'; $res.ok = $true; Done }

        New-Item -Path $child -Force | Out-Null
        $orig = @{}
        if (-not (Test-Path $fx)) {
            throw 'this device has no effects key at all; use Equalizer APO Device Selector for it'
        } else {
            foreach ($n in $ALL) { $v = Get-Val $fx $n; $o = if ($null -eq $v -or (Is-Eapo $v)) { '!VALUE' } else { "$v" }; $orig[$n] = $o; Set-ItemProperty $child $n $o }
        }

        # install mode, as Device Selector picks it for a new device
        $hasNew = $false; foreach ($n in @($SFX, $MFX, $EFX, "$F,13", "$F,14", "$F,15")) { if ($null -ne (Get-Val $fx $n)) { $hasNew = $true } }
        $hasOld = ($null -ne (Get-Val $fx $LFX)) -or ($null -ne (Get-Val $fx $GFX))
        $combined = $null -ne (Get-Val "$ep\Properties" '{b3f8fa53-0004-438e-9003-51a46e139bfc},41')   # Win11 combined Bluetooth device
        $mode = if ($hasOld -and -not $hasNew) { 'LFX_GFX' } elseif ($combined) { 'SFX_MFX' } else { 'SFX_EFX' }
        $res.mode = $mode

        function Pick($a, $b, $fallback) { if ($orig[$a] -eq '!VALUE' -and $orig[$b] -eq '!VALUE') { $fallback } else { $orig[$a] } }
        switch ($mode) {
            'LFX_GFX' { $preO = $orig[$LFX]; $postO = $orig[$GFX]; if ($orig[$LFX] -eq '!VALUE' -and $orig[$GFX] -eq '!VALUE') { $preO = $orig[$SFX]; $postO = $orig[$MFX] } }
            'SFX_MFX' { $preO = Pick $SFX $MFX $orig[$LFX]; $postO = if ($orig[$SFX] -eq '!VALUE' -and $orig[$MFX] -eq '!VALUE') { $orig[$GFX] } else { $orig[$MFX] } }
            'SFX_EFX' { $preO = Pick $SFX $EFX $orig[$LFX]; $postO = if ($orig[$SFX] -eq '!VALUE' -and $orig[$EFX] -eq '!VALUE') { $orig[$GFX] } else { $orig[$EFX] } }
        }
        if (-not $KeepOriginal) { $preO = ''; $postO = '' }
        if ($preO -in '!KEY', '!VALUE') { $preO = '' }; if ($postO -in '!KEY', '!VALUE') { $postO = '' }
        Set-ItemProperty $child 'PreMixChild' $preO
        Set-ItemProperty $child 'PostMixChild' $postO
        Set-ItemProperty $child 'AllowSilentBufferModification' 'false'
        Remove-ItemProperty $child 'DisableAutomaticAdjustment' -ErrorAction SilentlyContinue
        Set-ItemProperty $child 'Version' '2'
        $res.kept = @($preO, $postO) | Where-Object { $_ }

        function Put($n) { EpSet 'FxProperties' $n $(if ($n -in $LFX, $SFX) { $PRE } else { $POST }) 'String' }
        function PutMode($n) { if ($null -eq (Get-Val $fx $MODES[$n])) { EpSet 'FxProperties' $MODES[$n] ([string[]]@($DEFAULT_MODE)) 'MultiString' } }
        switch ($mode) {
            'LFX_GFX' { Put $LFX; Put $GFX; foreach ($n in $SFX, $MFX, $EFX) { EpDel 'FxProperties' $n } }
            'SFX_MFX' { foreach ($n in $LFX, $GFX) { EpDel 'FxProperties' $n }; Put $SFX; PutMode $SFX; Put $MFX; PutMode $MFX }
            'SFX_EFX' { foreach ($n in $LFX, $GFX) { EpDel 'FxProperties' $n }; Put $SFX; PutMode $SFX; Put $EFX; PutMode $EFX }
        }
        # enhancements must be on for any APO to run (Device Selector does the same)
        EpDel 'FxProperties' $DISABLE
        if ($null -ne (Get-Val "$ep\Properties" $DISABLE)) { EpSet 'Properties' $DISABLE 0 'DWord' }
        Note "Equalizer APO attached ($mode)"
    } else {
        if (-not (Test-Path $child)) { Note 'Equalizer APO was not attached'; $res.ok = $true; Done }
        $first = Get-Val $child $LFX
        if ($first -eq '!KEY') { throw 'this device was attached by Device Selector without an effects key; detach it there' }
        else {
            foreach ($n in $ALL) {
                $o = Get-Val $child $n
                if ($o -eq '!VALUE') { EpDel 'FxProperties' $n }
                elseif ($o) { EpSet 'FxProperties' $n $o 'String' }
            }
        }
        Remove-Item $child -Recurse -Force
        $parent = 'HKLM:\SOFTWARE\EqualizerAPO\Child APOs'
        if ((Test-Path $parent) -and -not (Get-ChildItem $parent) -and -not (Get-Item $parent).ValueCount) { Remove-Item $parent -Force }
        Note 'Equalizer APO detached, original effects restored'
    }

    if (-not $NoRestart) {
        Restart-Service -Name Audiosrv -Force
        Note 'Windows Audio restarted'
    }
    $res.ok = $true
} catch { $res.error = "$($_.Exception.Message)" }
Done
