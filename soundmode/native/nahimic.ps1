# nahimic.ps1 - stop / start the Nahimic background app (service + scheduled tasks + tray processes).
# Run elevated by gui/api.py (one UAC prompt). Writes a JSON result to -Out. Nothing else on the system is touched.
#   -Action stop   : remember service start type + enabled tasks in -Out, set service Manual, stop it, disable tasks, end processes
#   -Action start  : put back the start type / tasks given in -StartType / -Tasks, start service + tasks
param([ValidateSet('stop', 'start')][string]$Action, [string]$Out, [string]$StartType = 'Automatic', [string]$Tasks = '')
$res = [ordered]@{ ok = $true; action = $Action; steps = @() }
function Step($name, [scriptblock]$b) {
    try { & $b; $script:res.steps += [ordered]@{ step = $name; ok = $true } }
    catch { $script:res.ok = $false; $script:res.steps += [ordered]@{ step = $name; ok = $false; error = "$($_.Exception.Message)" } }
}
$svc = Get-Service NahimicService -ErrorAction SilentlyContinue
if ($Action -eq 'stop') {
    $res.start_type = if ($svc) { "$($svc.StartType)" } else { '' }
    $res.tasks = @(Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object { $_.TaskName -like 'Nahimic*' -and $_.State -ne 'Disabled' } | ForEach-Object { $_.TaskPath + $_.TaskName })
    Step 'tasks' { Get-ScheduledTask | Where-Object { $_.TaskName -like 'Nahimic*' } | ForEach-Object { Stop-ScheduledTask -InputObject $_ -ErrorAction SilentlyContinue; Disable-ScheduledTask -InputObject $_ -ErrorAction Stop | Out-Null } }
    if ($svc) { Step 'service' { Set-Service NahimicService -StartupType Manual -ErrorAction Stop; Stop-Service NahimicService -Force -ErrorAction Stop } }
    Step 'processes' { Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'Nahimic*' } | Stop-Process -Force -ErrorAction SilentlyContinue }
} else {
    if ($svc) { Step 'service' { Set-Service NahimicService -StartupType $StartType -ErrorAction Stop; Start-Service NahimicService -ErrorAction Stop } }
    foreach ($t in ($Tasks -split '\|' | Where-Object { $_ })) {
        $i = $t.LastIndexOf('\'); $path = $t.Substring(0, $i + 1); $name = $t.Substring($i + 1)
        Step "task $name" { Enable-ScheduledTask -TaskPath $path -TaskName $name -ErrorAction Stop | Out-Null; Start-ScheduledTask -TaskPath $path -TaskName $name -ErrorAction SilentlyContinue }
    }
}
$res | ConvertTo-Json -Depth 4 | Set-Content -Path $Out -Encoding UTF8
