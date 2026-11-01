$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$recordPath = Join-Path $projectRoot '.run\comfyui-video\process.json'
if (-not (Test-Path -LiteralPath $recordPath)) { Write-Output 'No recorded ComfyUI process.'; exit 0 }
$records = @(Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json)
$owned = @($records | ForEach-Object {
    $process = Get-Process -Id $_.pid -ErrorAction SilentlyContinue
    if ($process -and $process.Path -eq $_.executable -and $process.StartTime.ToUniversalTime().Ticks -eq $_.startTicks) { $process }
})
if ($owned.Count -eq 0) { Write-Output 'No matching ComfyUI process is running.'; exit 0 }
try { $queue = Invoke-RestMethod ("http://127.0.0.1:{0}/queue" -f $records[0].port) -TimeoutSec 3 } catch { throw 'Cannot verify the queue; no process was stopped.' }
if (@($queue.queue_running).Count -gt 0 -or @($queue.queue_pending).Count -gt 0) { throw 'ComfyUI has running or queued jobs; no process was stopped.' }
foreach ($process in $owned) { Stop-Process -Id $process.Id -ErrorAction Stop; Write-Output ('Stopped recorded process ' + $process.Id) }
