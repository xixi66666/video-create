param(
    [Parameter(Mandatory=$true)][string]$TextFile,
    [Parameter(Mandatory=$true)][string]$Output,
    [string]$Voice = '茉莉',
    [string]$Context = '自然、克制、有情绪层次的中文纪录片旁白'
)
$ErrorActionPreference = 'Stop'
$previousKey = $env:MIMO_API_KEY
$userKey = [Environment]::GetEnvironmentVariable('MIMO_API_KEY', 'User')
try {
    if ($userKey) { $env:MIMO_API_KEY = $userKey }
    if (-not $env:MIMO_API_KEY) { throw '未配置 MIMO_API_KEY 环境变量。' }
    $script = Join-Path $PSScriptRoot 'mimo_tts.py'
    & python $script --text-file $TextFile --output $Output --voice $Voice --context $Context
    if ($LASTEXITCODE -ne 0) { throw 'MiMo 语音生成失败。' }
} finally {
    $env:MIMO_API_KEY = $previousKey
    $userKey = $null
}
