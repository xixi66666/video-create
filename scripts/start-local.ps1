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
$previousAllowedModels = $env:CREATOR_APPROVED_AGENT_MODELS
$previousDeepSeekKey = $env:DEEPSEEK_API_KEY
$previousMiMoKey = $env:MIMO_API_KEY
$userDeepSeekKey = [Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY', 'User')
$userMiMoKey = [Environment]::GetEnvironmentVariable('MIMO_API_KEY', 'User')
if ($userDeepSeekKey) { $env:DEEPSEEK_API_KEY = $userDeepSeekKey }
if ($userMiMoKey) { $env:MIMO_API_KEY = $userMiMoKey }
$bytes = New-Object byte[] 32
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$rng.GetBytes($bytes)
$rng.Dispose()
$env:CREATOR_RUNTIME_TOKEN = [Convert]::ToBase64String($bytes)
if ($env:DEEPSEEK_API_KEY) {
    # 用户已选择 DeepSeek；启动本身不发出模型请求。
    $env:CREATOR_ENABLE_LIVE_MODELS = 'true'
    $env:CREATOR_APPROVED_AGENT_MODELS = 'model_deepseek_flash'
} else {
    $env:CREATOR_ENABLE_LIVE_MODELS = 'false'
    $env:CREATOR_APPROVED_AGENT_MODELS = ''
}
try {
$runtimeProcess = Start-Process -FilePath $runtimePython -ArgumentList @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8090','--no-access-log') -WorkingDirectory (Join-Path $projectRoot 'agent-runtime') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runRoot 'runtime.log') -RedirectStandardError (Join-Path $runRoot 'runtime-error.log') -PassThru
$backendProcess = Start-Process -FilePath $javaExecutable -ArgumentList @('-jar',('"'+$jarPath+'"')) -WorkingDirectory (Join-Path $projectRoot 'backend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runRoot 'backend.log') -RedirectStandardError (Join-Path $runRoot 'backend-error.log') -PassThru
$frontendProcess = Start-Process -FilePath $nodeExecutable -ArgumentList @(('"'+$vitePath+'"'),'--host','127.0.0.1','--port','5178','--strictPort') -WorkingDirectory (Join-Path $projectRoot 'frontend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runRoot 'frontend.log') -RedirectStandardError (Join-Path $runRoot 'frontend-error.log') -PassThru
} finally {
    $env:CREATOR_RUNTIME_TOKEN = $previousToken
    $env:CREATOR_ENABLE_LIVE_MODELS = $previousLiveFlag
    $env:CREATOR_APPROVED_AGENT_MODELS = $previousAllowedModels
    $env:DEEPSEEK_API_KEY = $previousDeepSeekKey
    $env:MIMO_API_KEY = $previousMiMoKey
    $userDeepSeekKey = $null
    $userMiMoKey = $null
}
$records = @($runtimeProcess,$backendProcess,$frontendProcess) | ForEach-Object { [pscustomobject]@{pid=$_.Id;executable=$_.Path;startTicks=$_.StartTime.ToUniversalTime().Ticks} }
$records | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runRoot 'processes.json') -Encoding UTF8
for ($attempt=0; $attempt -lt 80; $attempt++) {
    try {
        $health=Invoke-RestMethod -Uri 'http://127.0.0.1:8088/api/v1/health' -TimeoutSec 1
        $runtimeHealth=Invoke-RestMethod -Uri 'http://127.0.0.1:8088/api/v1/agent-runs/readiness' -TimeoutSec 2
        if ($health.data.status -eq 'UP' -and $runtimeHealth.data.online -and (Test-LocalPort 5178)) { Write-Output 'Ready: http://127.0.0.1:5178/'; Write-Output 'Backend: http://127.0.0.1:8088/api/v1/health'; exit 0 }
    } catch { }
    Start-Sleep -Milliseconds 400
}
throw 'Startup did not finish. Inspect .run/backend.log and .run/frontend.log, then use scripts/stop-local.ps1.'
