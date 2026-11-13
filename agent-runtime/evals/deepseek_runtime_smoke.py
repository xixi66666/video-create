"""一次受控的真实供应商与专家运行时试验，不构成领域认证。

在项目根目录：
  $env:DEEPSEEK_API_KEY = Read-Host 'DeepSeek API Key'
  agent-runtime/.venv/Scripts/python.exe agent-runtime/evals/deepseek_runtime_smoke.py --output smoke-result.json
  # 运行其他虚构场景时显式指定 --case，例如 offline-quality-adversarial。

运行会产生供应商费用；运行结束后可执行 Remove-Item Env:DEEPSEEK_API_KEY。
密钥只从当前进程环境读取，不写入配置、请求体或结果文件。项目不再限制 token；
调用次数和时间限制不能保证人民币费用上限，费用以供应商实际计量为准。
"""
import argparse
import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path
from expert_scenarios import CASES, SPECIALIST_CASES, ADVERSARIAL_CASES

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent-runtime"))


def resolve_case(case_id):
    """只允许执行评测目录内的固定虚构场景，不接收任意用户输入。"""
    groups = ((CASES, ""), (SPECIALIST_CASES, "-specialist"), (ADVERSARIAL_CASES, "-adversarial"))
    for cases, suffix in groups:
        for role, node_id, task_input, expected, forbidden in cases:
            if case_id == f"offline-{role.lower()}{suffix}":
                return {"id": case_id, "role": role, "nodeId": node_id, "input": task_input,
                        "humanReviewExpected": expected, "humanReviewForbidden": forbidden}
    raise ValueError("未知评测场景；请通过 expert_scenarios.py 查看可用 ID")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="非敏感结果 JSON；不覆盖已有文件")
    parser.add_argument("--case", default="offline-analyst-specialist", help="虚构评测场景 ID；默认 ANALYST 专项场景")
    args = parser.parse_args()
    try:
        case = resolve_case(args.case)
    except ValueError as exc:
        parser.error(str(exc))
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        parser.error("请先在当前进程设置 DEEPSEEK_API_KEY")
    if args.output.exists():
        parser.error("输出文件已存在，请选择新文件")
    if not args.output.parent.is_dir():
        parser.error("输出目录不存在")

    # 禁止继承外部工具和遥测开关。SQLite 与运行快照仅存在于临时目录。
    with tempfile.TemporaryDirectory(prefix="creator-deepseek-smoke-") as data_dir:
        os.environ.update(CREATOR_RUNTIME_DATA=data_dir, CREATOR_ENABLE_LIVE_MODELS="true",
                          CREATOR_APPROVED_AGENT_MODELS="deepseek-smoke", CREATOR_RESEARCH_ENABLED="false",
                          CREATOR_LOCAL_MEDIA_ENABLED="false", LANGCHAIN_TRACING_V2="false",
                          LANGSMITH_TRACING="false")
        from fastapi.testclient import TestClient
        from app.main import app as default_app, create_app
        from app.profiles import load_profiles

        nodes = json.loads((ROOT / "specs/nodes.json").read_text(encoding="utf-8"))["nodes"]
        node = next(n for n in nodes if n["id"] == case["nodeId"] and n["agentRole"] == case["role"])
        profiles = load_profiles()
        model = {"id": "deepseek-smoke", "remoteModelId": "deepseek-flash",
                 "protocol": "CHAT_COMPLETIONS_COMPATIBLE", "baseUrl": "https://api.deepseek.com",
                 "credentialRef": "DEEPSEEK_API_KEY", "parameters": {"temperature": 0, "reasoning_effort": "none"}}
        limits = {"maxModelCalls": 30,
                  "maxSeconds": 300, "maxReworks": 0}
        run_id = "run_smoke_" + uuid.uuid4().hex
        body = {"id": run_id, "projectId": "isolated-smoke", "mode": "LIVE", "node": node,
                "input": {"brief": case["input"], "dependencies": {}},
                "models": {role: dict(model) for role in ("supervisor", "worker", "reviewer")},
                "inputFingerprint": case["id"], "executionMode": "GENERATE_TEXT" if node.get("executorKind") == "AGENT" else "PLAN_ONLY",
                "limits": limits, "fixtureRework": False}
        token = uuid.uuid4().hex
        result = {"caseId": case["id"], "scenario": case, "runId": run_id, "model": model["remoteModelId"],
                  "modelParameters": model["parameters"], "limits": limits,
                  "profiles": {r: {k: profiles[r][k] for k in ("version", "sha256", "domainVerified")}
                               for r in ("SUPERVISOR", case["role"], "REVIEWER")},
                  "notice": "单次真实试验，不是独立领域专家评分；不修改 domainVerified。"
                            "费用由供应商计量，调用次数和时间限制不保证货币费用上限。"}
        test_app = create_app(data_dir, token)
        try:
            with TestClient(test_app, headers={"X-Creator-Token": token}) as client:
                response = client.post("/runs", json=body)
                result["httpStatus"] = response.status_code
                if response.status_code == 202:
                    deadline = time.monotonic() + 360
                    terminal = {"WAITING_ACCEPTANCE", "REWORK_EXHAUSTED", "UNKNOWN", "FAILED", "CANCELLED"}
                    while time.monotonic() < deadline:
                        run = client.get(f"/runs/{run_id}").json()
                        if run["status"] in terminal:
                            break
                        time.sleep(1)
                    else:
                        client.post(f"/runs/{run_id}/cancel")
                        run = client.get(f"/runs/{run_id}").json()
                    result["status"] = run.get("status")
                    result["artifacts"] = run.get("artifacts", [])
                    result["events"] = client.get(f"/runs/{run_id}/events").json()
                    safe_errors = {"达到 token 使用上限", "达到模型调用次数上限", "达到运行时间上限",
                                   "执行异常，请查看脱敏事件；没有自动重试模型调用。"}
                    if run.get("error"):
                        result["error"] = run["error"] if run["error"] in safe_errors else "运行失败，详情未记录以避免泄露敏感信息。"
                    # 不复制供应商异常文本，也不自动采纳候选。
                else:
                    result["status"] = "NOT_ACCEPTED"
        except Exception as exc:
            result.update(status="SCRIPT_ERROR", errorType=type(exc).__name__)
        finally:
            # 模块默认 app 也会打开 SQLite，Windows 下移除临时目录前须关闭两组连接。
            for application in (test_app, default_app):
                application.state.engine.connection.close()
                application.state.store.db.close()

        # 不保存任何意外出现在响应里的密钥或内部鉴权令牌。
        encoded = json.dumps(result, ensure_ascii=False, indent=2).replace(key, "[REDACTED]").replace(token, "[REDACTED]")
        with args.output.open("x", encoding="utf-8") as output:
            output.write(encoded + "\n")
    print(f"试验结果已保存：{args.output}；状态：{result.get('status')}")
    return 0 if result.get("status") in {"WAITING_ACCEPTANCE", "REWORK_EXHAUSTED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
