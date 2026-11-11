# 启动 voicelib 操作台
#   .\start.ps1
# 优先用 D:\venvs\voicelib(装了 yt-dlp / demucs / torch),否则退回系统 Python。

$venv = 'D:\venvs\voicelib\Scripts\python.exe'
$py = if (Test-Path $venv) { $venv } else { 'python' }

Write-Host "使用解释器: $py" -ForegroundColor DarkGray
if (-not (Test-Path $venv)) {
    Write-Host "提示:未找到 venv,采集功能将降级(无 yt-dlp / demucs)" -ForegroundColor Yellow
}

& $py (Join-Path $PSScriptRoot 'server.py')
