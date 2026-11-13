"""在隔离目录中模拟启动失败，确认已启动进程会被回滚。"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "nt" or not shutil.which("pwsh"), reason="需要 Windows PowerShell 7")
@pytest.mark.parametrize("fail_on, expected_stopped", [(2, [1]), (3, [1, 2]), (4, [1, 2, 3]), (0, [])])
@pytest.mark.parametrize("mode", ["fixture", "live"])
def test_start_rolls_back_partial_failure_and_restores_environment(tmp_path, fail_on, expected_stopped, mode):
    root = Path(__file__).resolve().parents[2]
    script_name = "start-local.ps1" if mode == "fixture" else "start-local-deepseek.ps1"
    source = (root / "scripts" / script_name).read_text(encoding="utf-8")
    # 只隔离与本机端口、已安装依赖有关的检查；实际进程管理逻辑原样执行。
    port_check = "if ((Test-LocalPort 5178) -or (Test-LocalPort 8088) -or (Test-LocalPort 8090))"
    preflight = "& $runtimePython -c 'import deepagents, langgraph, fastapi, uvicorn'"
    assert port_check in source and preflight in source
    source = source.replace(port_check, "if ($false)")
    source = source.replace(preflight, "$global:LASTEXITCODE = 0")
    source = source.replace("-and (Test-LocalPort 5178)", "-and $true")
    for directory in ("scripts", "backend/target", "frontend/node_modules/vite/bin",
                      "agent-runtime/.venv/Scripts", "java/bin"):
        (tmp_path / directory).mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts" / script_name).write_text(source, encoding="utf-8")
    (tmp_path / "scripts/sync-catalog.mjs").write_text("process.exit(0);", encoding="utf-8")
    (tmp_path / "backend/target/creator-workbench-0.2.0.jar").touch()
    (tmp_path / "frontend/node_modules/vite/bin/vite.js").touch()
    (tmp_path / "agent-runtime/.venv/Scripts/python.exe").touch()
    (tmp_path / "java/bin/java.exe").touch()
    (tmp_path / "java/release").write_text('JAVA_VERSION="21"', encoding="utf-8")
    harness = r'''
param([string]$Root, [int]$FailOn, [string]$Mode)
$global:counter = 0
$global:stopped = @()
$global:tokenPresent = @()
$global:keyPresent = @()
function global:Start-Process {
    param($FilePath, $ArgumentList, $WorkingDirectory, $WindowStyle, $RedirectStandardOutput, $RedirectStandardError, [switch]$PassThru)
    $global:counter++
    $global:tokenPresent += [bool]$env:CREATOR_RUNTIME_TOKEN
    $global:keyPresent += [bool]$env:DEEPSEEK_API_KEY
    if ($global:counter -eq $FailOn) { throw 'synthetic startup failure' }
    return [pscustomobject]@{Id=$global:counter; Path=$FilePath; StartTime=[datetime]::UtcNow; HasExited=$false}
}
function global:Stop-Process { param($InputObject); $global:stopped += $InputObject.Id }
function global:Invoke-RestMethod { param($Uri, $TimeoutSec); return @{data=@{status=$(if($FailOn -eq 4){'DOWN'}else{'UP'});online=($FailOn -ne 4);liveModelsEnabled=$true}} }
function global:Start-Sleep { param($Milliseconds) }
if ($Mode -eq 'live') {
    Add-Type -TypeDefinition 'namespace CreatorWorkbench { public static class CredentialReader { public static string Read(string target) { return "test-key"; } } }'
}
$env:CREATOR_RUNTIME_TOKEN = 'existing-token'
$env:CREATOR_ENABLE_LIVE_MODELS = 'existing-flag'
$env:DEEPSEEK_API_KEY = 'local-test-value'
$failed = $false
try {
    if ($Mode -eq 'live') { & (Join-Path $Root 'scripts/start-local-deepseek.ps1') -EnableLive -ApprovedModelId 'test-model' -JavaHome (Join-Path $Root 'java') | Out-Null }
    else { & (Join-Path $Root 'scripts/start-local.ps1') -JavaHome (Join-Path $Root 'java') | Out-Null }
} catch { $failed = $true }
@{failed=$failed; stopped=@($global:stopped); tokenPresent=@($global:tokenPresent);keyPresent=@($global:keyPresent);
  tokenRestored=($env:CREATOR_RUNTIME_TOKEN -eq 'existing-token');
  flagRestored=($env:CREATOR_ENABLE_LIVE_MODELS -eq 'existing-flag');keyRestored=($env:DEEPSEEK_API_KEY -eq 'local-test-value')} | ConvertTo-Json -Compress
'''
    harness_path = tmp_path / "harness.ps1"
    harness_path.write_text(harness, encoding="utf-8")
    completed = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-File", str(harness_path),
                                "-Root", str(tmp_path), "-FailOn", str(fail_on), "-Mode", mode],
                               check=True, capture_output=True, text=True, encoding="utf-8", timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["failed"] is (fail_on != 0)
    assert result["stopped"] == expected_stopped
    assert result["tokenRestored"] and result["flagRestored"] and result["keyRestored"]
    if mode == "fixture":
        assert not any(result["keyPresent"])
    else:
        assert result["keyPresent"][0] is True
        assert not any(result["keyPresent"][1:])
    assert result["tokenPresent"][:2] == [True, True]
    if fail_on in (0, 4):
        assert result["tokenPresent"][2] is False
