param(
    [Parameter(Mandatory = $true)][string]$ComfyHome,
    [string]$PythonExecutable = '',
    [string]$ModelDirectory = '',
    [ValidateRange(1024, 65535)][int]$Port = 8192
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runRoot = Join-Path $projectRoot '.run\comfyui-video'
$main = Join-Path $ComfyHome 'main.py'
if (-not $PythonExecutable) { $PythonExecutable = Join-Path $ComfyHome '.venv-rocm\Scripts\python.exe' }
if (-not $ModelDirectory) { $ModelDirectory = Join-Path $ComfyHome 'models' }
foreach ($path in @($main, $PythonExecutable, $ModelDirectory)) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Required path does not exist: $path" }
}
$main = (Resolve-Path -LiteralPath $main).Path
$PythonExecutable = (Resolve-Path -LiteralPath $PythonExecutable).Path
$ModelDirectory = (Resolve-Path -LiteralPath $ModelDirectory).Path
$recordPath = Join-Path $runRoot 'process.json'
if (Test-Path -LiteralPath $recordPath) {
    try { $records = @(Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json) } catch { throw 'The existing process record is unreadable; inspect it before starting another instance.' }
    foreach ($record in $records) {
        $running = Get-Process -Id $record.pid -ErrorAction SilentlyContinue
        if ($running -and $running.Path -eq $record.executable -and $running.StartTime.ToUniversalTime().Ticks -eq $record.startTicks) {
            throw 'The recorded ComfyUI instance is already running; stop it before starting another instance.'
        }
    }
}
$probe = [System.Net.Sockets.TcpClient]::new()
try { $occupied = $probe.ConnectAsync('127.0.0.1', $Port).Wait(500) -and $probe.Connected } catch { $occupied = $false } finally { $probe.Dispose() }
if ($occupied) { throw "Port $Port is already in use; no process was changed." }
foreach ($dir in @('models', 'user', 'input', 'output', 'temp', 'cache')) { New-Item -ItemType Directory -Force -Path (Join-Path $runRoot $dir) | Out-Null }
# Paths are encoded as YAML-safe quoted strings. Existing model files are only read.
$modelPathYaml = ($ModelDirectory -replace '\\', '/') | ConvertTo-Json -Compress
@("creator_local:", "  base_path: $modelPathYaml", '  diffusion_models: diffusion_models', '  text_encoders: text_encoders', '  vae: vae') | Set-Content -LiteralPath (Join-Path $runRoot 'models.yaml') -Encoding UTF8
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONNOUSERSITE = '1'
$env:PYTHONPATH = ''
$env:TEMP = Join-Path $runRoot 'temp'
$env:TMP = $env:TEMP
$env:HF_HOME = Join-Path $runRoot 'cache\huggingface'
$env:TORCH_HOME = Join-Path $runRoot 'cache\torch'
$env:XDG_CACHE_HOME = Join-Path $runRoot 'cache'
$database = 'sqlite:///' + ((Join-Path $runRoot 'user\comfyui.db') -replace '\\', '/')
$argsList = @('"'+$main+'"', '--base-directory', '"'+$runRoot+'"', '--extra-model-paths-config', '"'+(Join-Path $runRoot 'models.yaml')+'"', '--listen', '127.0.0.1', '--port', "$Port", '--reserve-vram', '3', '--database-url', $database, '--disable-all-custom-nodes', '--disable-api-nodes', '--disable-auto-launch')
$launcher = Start-Process -FilePath $PythonExecutable -ArgumentList $argsList -WorkingDirectory $runRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runRoot 'stdout.log') -RedirectStandardError (Join-Path $runRoot 'stderr.log') -PassThru
[pscustomobject]@{pid=$launcher.Id;executable=$launcher.Path;startTicks=$launcher.StartTime.ToUniversalTime().Ticks;port=$Port} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runRoot 'process.json') -Encoding UTF8
$stats = $null
for ($i = 0; $i -lt 90; $i++) {
    Start-Sleep -Seconds 1
    try { $stats = Invoke-RestMethod "http://127.0.0.1:$Port/system_stats" -TimeoutSec 2; if ($stats.system.comfyui_version) { break } } catch {}
    if ($launcher.HasExited) { throw 'ComfyUI exited; inspect .run/comfyui-video/stderr.log.' }
}
if (-not $stats -or -not $stats.system.comfyui_version) { throw 'ComfyUI did not become ready; inspect .run/comfyui-video/stderr.log.' }
$basePython = (& $PythonExecutable -B -c 'import sys; print(sys._base_executable)').Trim()
$pattern = '^\s*TCP\s+127\.0\.0\.1:' + $Port + '\s+\S+\s+LISTENING\s+\d+\s*$'
$line = netstat -ano -p tcp | Select-String $pattern | Select-Object -First 1
if (-not $line) { throw 'Could not identify the ComfyUI listener; inspect the process record.' }
$listenerId = [int](($line.ToString().Trim() -split '\s+')[-1])
$listener = Get-Process -Id $listenerId -ErrorAction Stop
if ($listener.Path -ne $basePython -or $listener.StartTime -lt $launcher.StartTime) { throw 'Listener identity does not match the launched Python process.' }
@($listener, $launcher) | ForEach-Object { [pscustomobject]@{pid=$_.Id;executable=$_.Path;startTicks=$_.StartTime.ToUniversalTime().Ticks;port=$Port} } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runRoot 'process.json') -Encoding UTF8
Write-Output "Ready: http://127.0.0.1:$Port/"
