param([string]$JavaHome = '')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runRoot = Join-Path $projectRoot '.run'
New-Item -ItemType Directory -Path $runRoot -Force | Out-Null

function Test-LocalPort([int]$port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try { return $client.ConnectAsync('127.0.0.1', $port).Wait(400) -and $client.Connected } catch { return $false } finally { $client.Dispose() }
}
function Find-Java21 {
    $candidates = @($JavaHome, $env:JAVA_HOME)
    $javaCommand = Get-Command java.exe -ErrorAction SilentlyContinue
    if ($javaCommand) { $candidates += Split-Path -Parent (Split-Path -Parent $javaCommand.Source) }
    $extensionRoot = Join-Path $env:USERPROFILE '.vscode\extensions'
    if (Test-Path -LiteralPath $extensionRoot) {
        Get-ChildItem -Path (Join-Path $extensionRoot 'redhat.java-*\jre\*') -Directory -ErrorAction SilentlyContinue | ForEach-Object { $candidates += $_.FullName }
    }
    foreach ($candidate in $candidates | Where-Object { $_ } | Select-Object -Unique) {
        $release = Join-Path $candidate 'release'
        $executable = Join-Path $candidate 'bin\java.exe'
        if ((Test-Path -LiteralPath $release) -and (Test-Path -LiteralPath $executable)) {
            $version = Get-Content -LiteralPath $release -Raw
            if ($version -match 'JAVA_VERSION="(\d+)') { if ([int]$Matches[1] -ge 21) { return $executable } }
        }
    }
    throw 'Java 21+ was not found. Set JAVA_HOME or pass -JavaHome to this script.'
}

if ((Test-LocalPort 5178) -or (Test-LocalPort 8088) -or (Test-LocalPort 8090)) { throw 'Port 5178, 8088 or 8090 is in use. Stop the previous instance before starting.' }
$javaExecutable = Find-Java21
$nodeExecutable = (Get-Command node.exe -ErrorAction Stop).Source
$jarPath = Join-Path $projectRoot 'backend\target\creator-workbench-0.2.0.jar'
$vitePath = Join-Path $projectRoot 'frontend\node_modules\vite\bin\vite.js'
if (-not (Test-Path -LiteralPath $jarPath)) { throw 'Build the backend first: cd backend; mvn test package' }
if (-not (Test-Path -LiteralPath $vitePath)) { throw 'Install frontend dependencies first: cd frontend; npm ci' }
& $nodeExecutable (Join-Path $projectRoot 'scripts\sync-catalog.mjs')
if ($LASTEXITCODE -ne 0) { throw 'Catalog synchronization failed. No services were started.' }

$runtimePython = Join-Path $projectRoot 'agent-runtime\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $runtimePython)) { throw 'Install the runtime first: scripts/install-agent-runtime.ps1 -PythonExecutable <Python 3.12 path>' }
& $runtimePython -c 'import deepagents, langgraph, fastapi, uvicorn'
if ($LASTEXITCODE -ne 0) { throw 'Runtime dependencies are incomplete. Finish scripts/install-agent-runtime.ps1 before starting.' }
$previousToken = $env:CREATOR_RUNTIME_TOKEN
$previousLiveFlag = $env:CREATOR_ENABLE_LIVE_MODELS
$previousDeepseekKey = $env:DEEPSEEK_API_KEY
$privateVoiceNames = @('CREATOR_VOICE_DB_PASSWORD', 'MIMO_API_KEY')
$privateVoiceValues = @{}
foreach ($name in $privateVoiceNames) { $privateVoiceValues[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
$bytes = New-Object byte[] 32
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$rng.GetBytes($bytes)
$rng.Dispose()
$env:CREATOR_RUNTIME_TOKEN = [Convert]::ToBase64String($bytes)
$env:CREATOR_ENABLE_LIVE_MODELS = 'false'
# 此入口只运行 FIXTURE，子进程不需要 DeepSeek 凭据。
[Environment]::SetEnvironmentVariable('DEEPSEEK_API_KEY', $null, 'Process')
$started = @()
try {
    $runtimeProcess = Start-Process -FilePath $runtimePython -ArgumentList @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8090','--no-access-log') -WorkingDirectory (Join-Path $projectRoot 'agent-runtime') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runRoot 'runtime.log') -RedirectStandardError (Join-Path $runRoot 'runtime-error.log') -PassThru
    $started += $runtimeProcess
    # 数据库和 MiMo 凭据只交给语音运行服务。
    foreach ($name in $privateVoiceNames) { [Environment]::SetEnvironmentVariable($name, $null, 'Process') }
    $backendProcess = Start-Process -FilePath $javaExecutable -ArgumentList @('-jar',('"'+$jarPath+'"')) -WorkingDirectory (Join-Path $projectRoot 'backend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runRoot 'backend.log') -RedirectStandardError (Join-Path $runRoot 'backend-error.log') -PassThru
    $started += $backendProcess
    # Vite 仅代理 HTTP 请求，不需要内部令牌。
    [Environment]::SetEnvironmentVariable('CREATOR_RUNTIME_TOKEN', $null, 'Process')
    [Environment]::SetEnvironmentVariable('CREATOR_ENABLE_LIVE_MODELS', $null, 'Process')
    $frontendProcess = Start-Process -FilePath $nodeExecutable -ArgumentList @(('"'+$vitePath+'"'),'--host','127.0.0.1','--port','5178','--strictPort') -WorkingDirectory (Join-Path $projectRoot 'frontend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runRoot 'frontend.log') -RedirectStandardError (Join-Path $runRoot 'frontend-error.log') -PassThru
    $started += $frontendProcess
    $records = $started | ForEach-Object { [pscustomobject]@{pid=$_.Id;executable=$_.Path;startTicks=$_.StartTime.ToUniversalTime().Ticks} }
    $records | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runRoot 'processes.json') -Encoding UTF8
    for ($attempt=0; $attempt -lt 80; $attempt++) {
        try {
            $health=Invoke-RestMethod -Uri 'http://127.0.0.1:8088/api/v1/health' -TimeoutSec 1
            $runtimeHealth=Invoke-RestMethod -Uri 'http://127.0.0.1:8088/api/v1/agent-runs/readiness' -TimeoutSec 2
            if ($health.data.status -eq 'UP' -and $runtimeHealth.data.online -and (Test-LocalPort 5178)) { Write-Output 'Ready: http://127.0.0.1:5178/'; Write-Output 'Backend: http://127.0.0.1:8088/api/v1/health'; return }
        } catch { }
        Start-Sleep -Milliseconds 400
    }
    throw 'Startup did not finish. Inspect .run/backend.log and .run/frontend.log.'
} catch {
    # 仅回滚本次成功启动的进程，避免部分启动失败后留下无法管理的孤儿。
    foreach ($process in $started) {
        if (-not $process.HasExited) { Stop-Process -InputObject $process -ErrorAction SilentlyContinue }
    }
    throw
} finally {
    [Environment]::SetEnvironmentVariable('CREATOR_RUNTIME_TOKEN', $previousToken, 'Process')
    [Environment]::SetEnvironmentVariable('CREATOR_ENABLE_LIVE_MODELS', $previousLiveFlag, 'Process')
    [Environment]::SetEnvironmentVariable('DEEPSEEK_API_KEY', $previousDeepseekKey, 'Process')
    foreach ($name in $privateVoiceNames) { [Environment]::SetEnvironmentVariable($name, $privateVoiceValues[$name], 'Process') }
}
