param(
    [Parameter(Mandatory = $true)][string[]]$ApprovedModelId,
    [Parameter(Mandatory = $true)][switch]$EnableLive,
    [string]$JavaHome = ''
)

# 独立启动入口：默认启动脚本仍保持关闭真实模型。密钥只进入运行时子进程环境。
$ErrorActionPreference = 'Stop'
if (-not $EnableLive) { throw '必须显式传入 -EnableLive 才能启用真实模型。' }
if (-not $ApprovedModelId -or @($ApprovedModelId | Where-Object { $_ -notmatch '^[A-Za-z0-9_.-]{1,90}$' }).Count -gt 0) { throw 'ApprovedModelId 必须是一个或多个已配置的模型档案 ID。' }
Write-Warning 'LIVE startup can resume queued or pending work and incur model charges. Check existing tasks before starting.'
$projectRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'workspace-database.ps1')
$runRoot = Join-Path $projectRoot '.run'

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
            if ($version -match 'JAVA_VERSION="(\d+)' -and [int]$Matches[1] -ge 21) { return $executable }
        }
    }
    throw 'Java 21+ was not found. Set JAVA_HOME or pass -JavaHome.'
}

if ((Test-LocalPort 5178) -or (Test-LocalPort 8088) -or (Test-LocalPort 8090)) { throw 'Port 5178, 8088 or 8090 is in use. Stop the previous instance first.' }
$javaExecutable = Find-Java21
$nodeExecutable = (Get-Command node.exe -ErrorAction Stop).Source
$jarPath = Join-Path $projectRoot 'backend\target\creator-workbench-0.2.0.jar'
$vitePath = Join-Path $projectRoot 'frontend\node_modules\vite\bin\vite.js'
$runtimePython = Join-Path $projectRoot 'agent-runtime\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $jarPath)) { throw 'Build the backend first: cd backend; mvn test package' }
if (-not (Test-Path -LiteralPath $vitePath)) { throw 'Install frontend dependencies first: cd frontend; npm ci' }
if (-not (Test-Path -LiteralPath $runtimePython)) { throw 'Install the agent runtime first.' }
& $nodeExecutable (Join-Path $projectRoot 'scripts\sync-catalog.mjs')
if ($LASTEXITCODE -ne 0) { throw 'Catalog synchronization failed. No services were started.' }
& $runtimePython -c 'import deepagents, langgraph, fastapi, uvicorn'
if ($LASTEXITCODE -ne 0) { throw 'Runtime dependencies are incomplete.' }

# 读取当前 Windows 用户的通用凭据；绝不输出凭据内容或将其写入文件。
if (-not ('CreatorWorkbench.CredentialReader' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace CreatorWorkbench {
    public static class CredentialReader {
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct Credential {
            public uint Flags, Type;
            public IntPtr TargetName, Comment;
            public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
            public uint CredentialBlobSize;
            public IntPtr CredentialBlob;
            public uint Persist, AttributeCount;
            public IntPtr Attributes, TargetAlias, UserName;
        }
        [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool CredRead(string target, uint type, uint flags, out IntPtr credential);
        [DllImport("advapi32.dll")]
        private static extern void CredFree(IntPtr credential);
        public static string Read(string target) {
            IntPtr pointer;
            if (!CredRead(target, 1, 0, out pointer)) throw new InvalidOperationException("无法读取指定的 Windows 通用凭据。请确认当前用户已配置凭据。");
            try {
                var item = (Credential)Marshal.PtrToStructure(pointer, typeof(Credential));
                if (item.CredentialBlob == IntPtr.Zero || item.CredentialBlobSize == 0 || item.CredentialBlobSize % 2 != 0) throw new InvalidOperationException("凭据为空或不是 UTF-16LE 文本。 ");
                return Marshal.PtrToStringUni(item.CredentialBlob, (int)item.CredentialBlobSize / 2).TrimEnd('\0');
            } finally { CredFree(pointer); }
        }
    }
}
'@
}
New-Item -ItemType Directory -Path $runRoot -Force | Out-Null
$previous = @{}
$privateVoiceNames = @('CREATOR_VOICE_DB_PASSWORD', 'MIMO_API_KEY', 'CREATOR_DB_URL', 'CREATOR_DB_USER', 'CREATOR_DB_PASSWORD', 'SPRING_PROFILES_ACTIVE', 'CREATOR_WORKSPACE_REMOTE_REQUIRED')
foreach ($name in (@('CREATOR_RUNTIME_TOKEN','CREATOR_ENABLE_LIVE_MODELS','CREATOR_APPROVED_AGENT_MODELS','CREATOR_CREDENTIAL_HOST_GUARDS','DEEPSEEK_API_KEY') + $privateVoiceNames)) {
    $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$started = @()
try {
    $key = [CreatorWorkbench.CredentialReader]::Read('creator-workbench-deepseek')
    if ([string]::IsNullOrWhiteSpace($key)) { throw 'Windows 通用凭据为空。' }
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $env:CREATOR_RUNTIME_TOKEN = [Convert]::ToBase64String($bytes)
    $env:CREATOR_ENABLE_LIVE_MODELS = 'true'
    $env:CREATOR_APPROVED_AGENT_MODELS = $ApprovedModelId -join ','
    $env:CREATOR_CREDENTIAL_HOST_GUARDS = '{"DEEPSEEK_API_KEY":["api.deepseek.com"]}'
    $env:DEEPSEEK_API_KEY = $key
    foreach ($name in @('CREATOR_DB_URL','CREATOR_DB_USER','CREATOR_DB_PASSWORD','SPRING_PROFILES_ACTIVE')) { [Environment]::SetEnvironmentVariable($name, $null, 'Process') }
    $env:CREATOR_WORKSPACE_REMOTE_REQUIRED = 'true'
    $runtimeProcess = Start-Process -FilePath $runtimePython -ArgumentList @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8090','--no-access-log') -WorkingDirectory (Join-Path $projectRoot 'agent-runtime') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runRoot 'runtime.log') -RedirectStandardError (Join-Path $runRoot 'runtime-error.log') -PassThru
    $started += $runtimeProcess
    foreach ($name in @('CREATOR_VOICE_DB_PASSWORD','MIMO_API_KEY','CREATOR_WORKSPACE_REMOTE_REQUIRED')) { [Environment]::SetEnvironmentVariable($name, $null, 'Process') }
    # 后续 Java 和前端进程不继承 DeepSeek 密钥。
    [Environment]::SetEnvironmentVariable('DEEPSEEK_API_KEY', $null, 'Process')
    [Environment]::SetEnvironmentVariable('CREATOR_CREDENTIAL_HOST_GUARDS', $null, 'Process')
    $key = $null
    foreach ($name in @('CREATOR_DB_URL','CREATOR_DB_USER','CREATOR_DB_PASSWORD','SPRING_PROFILES_ACTIVE')) { [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process') }
    Set-CreatorWorkspaceDatabase $projectRoot
    $backendProcess = Start-Process -FilePath $javaExecutable -ArgumentList @('-jar',('"'+$jarPath+'"')) -WorkingDirectory (Join-Path $projectRoot 'backend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runRoot 'backend.log') -RedirectStandardError (Join-Path $runRoot 'backend-error.log') -PassThru
    $started += $backendProcess
    foreach ($name in @('CREATOR_DB_URL','CREATOR_DB_USER','CREATOR_DB_PASSWORD','SPRING_PROFILES_ACTIVE')) { [Environment]::SetEnvironmentVariable($name, $null, 'Process') }
    # 前端只代理 HTTP 请求，不需要内部令牌和模型授权配置。
    foreach ($name in @('CREATOR_RUNTIME_TOKEN','CREATOR_ENABLE_LIVE_MODELS','CREATOR_APPROVED_AGENT_MODELS')) {
        [Environment]::SetEnvironmentVariable($name, $null, 'Process')
    }
    $frontendProcess = Start-Process -FilePath $nodeExecutable -ArgumentList @(('"'+$vitePath+'"'),'--host','127.0.0.1','--port','5178','--strictPort') -WorkingDirectory (Join-Path $projectRoot 'frontend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runRoot 'frontend.log') -RedirectStandardError (Join-Path $runRoot 'frontend-error.log') -PassThru
    $started += $frontendProcess
    $records = $started | ForEach-Object { [pscustomobject]@{pid=$_.Id;executable=$_.Path;startTicks=$_.StartTime.ToUniversalTime().Ticks} }
    $records | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runRoot 'processes.json') -Encoding UTF8
    for ($attempt=0; $attempt -lt 80; $attempt++) {
        try {
            $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8088/api/v1/health' -TimeoutSec 1
            $runtimeHealth = Invoke-RestMethod -Uri 'http://127.0.0.1:8088/api/v1/agent-runs/readiness' -TimeoutSec 2
            if ($health.data.status -eq 'UP' -and $runtimeHealth.data.online -and $runtimeHealth.data.liveModelsEnabled -and (Test-LocalPort 5178)) {
                Write-Output 'Ready with LIVE models enabled: http://127.0.0.1:5178/'
                Write-Output 'LIVE startup may resume queued or pending work and incur model charges. Stop with scripts/stop-local.ps1.'
                return
            }
        } catch { }
        Start-Sleep -Milliseconds 400
    }
    throw 'Startup did not finish. Inspect .run logs.'
} catch {
    foreach ($process in $started) { if (-not $process.HasExited) { Stop-Process -InputObject $process -ErrorAction SilentlyContinue } }
    throw
} finally {
    $key = $null
    foreach ($name in $previous.Keys) { [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process') }
}
