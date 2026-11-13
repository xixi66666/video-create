"""会诊隔离与预算测试：使用离线测试模型，不代表专业评测。"""
import json
import time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.main import create_app

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "consultation-test-token"
NODES = json.loads((ROOT / "specs/nodes.json").read_text(encoding="utf-8"))["nodes"]


def request(run="run_consultation_001"):
    return {"id": run, "projectId": "test", "mode": "FIXTURE",
            "node": next(n for n in NODES if n["id"] == "N08"),
            "input": {"brief": "会诊测试", "dependencies": {}}, "models": {},
            "inputFingerprint": "test", "executionMode": "GENERATE_TEXT",
            "fixtureRework": False, "consultationRoles": ["FACT_CHECK", "WRITER"],
            "limits": {"maxModelCalls": 50, "maxTotalTokens": 10000, "maxOutputTokens": 1200,
                       "maxSeconds": 60, "maxReworks": 0}}


def wait(client, run):
    for _ in range(300):
        result = client.get(f"/runs/{run}").json()
        if result["status"] in {"WAITING_ACCEPTANCE", "FAILED", "UNKNOWN"}:
            return result
        time.sleep(.05)
    raise AssertionError(result)


def test_consultations_run_and_candidate_preserves_opinions(tmp_path, monkeypatch):
    from app.models import FixtureModel
    from langchain_core.messages import ToolMessage

    original = FixtureModel._generate
    inputs_seen, reviewer_seen = {}, []

    def capture(self, messages, stop=None, run_manager=None, **kwargs):
        for message in messages:
            if isinstance(message, ToolMessage) and message.name == "read_inputs":
                inputs_seen[self.role] = json.loads(message.content)
            if self.role == "REVIEWER" and getattr(message, "type", None) == "human":
                reviewer_seen.append(json.loads(message.content))
        return original(self, messages, stop=stop, run_manager=run_manager, **kwargs)

    monkeypatch.setattr(FixtureModel, "_generate", capture)
    body = request()
    with TestClient(create_app(tmp_path, TOKEN), headers={"X-Creator-Token": TOKEN}) as c:
        assert c.post("/runs", json=body).status_code == 202
        run = wait(c, body["id"])
        assert run["status"] == "WAITING_ACCEPTANCE", run
        artifacts = {a["kind"]: a["content"] for a in run["artifacts"]}
        opinions = artifacts["CONSULTATION"]
        assert [o["role"] for o in opinions] == ["FACT_CHECK", "WRITER"]
        assert all(len(o["sha256"]) == len(o["profileHash"]) == 64 for o in opinions)
        assert artifacts["CANDIDATE"]["consultations"] == opinions
        assert "consultations" not in inputs_seen["FACT_CHECK"]
        assert "consultations" not in inputs_seen["WRITER"]
        assert inputs_seen["TOPIC_RESEARCH"]["consultations"] == opinions
        assert reviewer_seen[-1]["candidate"]["consultations"] == opinions
        events = c.get(f"/runs/{body['id']}/events").json()
        assert [e["role"] for e in events if e["kind"] == "CONSULTATION_FINISHED"] == ["FACT_CHECK", "WRITER"]
        assert sum(e["kind"] == "MODEL_STARTED" for e in events) <= 50
        assert c.post("/runs", json=body).status_code == 202


def test_consultations_repeat_with_rework(tmp_path):
    body = request("run_consultation_rework")
    body["consultationRoles"] = ["FACT_CHECK"]
    body["fixtureRework"] = True
    body["limits"]["maxReworks"] = 1
    with TestClient(create_app(tmp_path, TOKEN), headers={"X-Creator-Token": TOKEN}) as c:
        assert c.post("/runs", json=body).status_code == 202
        run = wait(c, body["id"])
        assert run["status"] == "WAITING_ACCEPTANCE", run
        opinions = [a for a in run["artifacts"] if a["kind"] == "CONSULTATION"]
        assert [a["version"] for a in opinions] == [1, 2]


def test_two_consultants_with_workbench_budget_and_rework(tmp_path):
    body = request("run_consultation_workbench_budget")
    body["fixtureRework"] = True
    body["limits"].update(maxModelCalls=60, maxReworks=1)
    with TestClient(create_app(tmp_path, TOKEN), headers={"X-Creator-Token": TOKEN}) as c:
        assert c.post("/runs", json=body).status_code == 202
        run = wait(c, body["id"])
        assert run["status"] == "WAITING_ACCEPTANCE", run
        assert len([a for a in run["artifacts"] if a["kind"] == "CONSULTATION"]) == 2


def test_consultation_role_validation_and_budget(tmp_path):
    with TestClient(create_app(tmp_path, TOKEN), headers={"X-Creator-Token": TOKEN}) as c:
        for roles in (["FACT_CHECK", "FACT_CHECK"], ["TOPIC_RESEARCH"], ["SUPERVISOR"], ["NOT_A_ROLE"]):
            body = request("run_invalid_" + str(len(roles)))
            body["consultationRoles"] = roles
            assert c.post("/runs", json=body).status_code == 400
        body = request("run_over_budget")
        body["limits"]["maxModelCalls"] = 3
        assert c.post("/runs", json=body).status_code == 202
        assert wait(c, body["id"])["status"] == "FAILED"
        events = c.get(f"/runs/{body['id']}/events").json()
        assert sum(e["kind"] == "MODEL_STARTED" for e in events) == 3


def test_each_consultant_uses_its_own_snapshot_and_old_run_falls_back(tmp_path, monkeypatch):
    from app import engine

    original = engine.build_model
    seen = {}

    def capture(snapshot, role, payload, attempt=0):
        seen[role] = snapshot.get("id")
        return original(snapshot, role, payload, attempt)

    monkeypatch.setattr(engine, "build_model", capture)
    body = request("run_consultant_snapshots")
    body["models"] = {"worker": {"id": "worker-model"}, "consultant_FACT_CHECK": {"id": "fact-model"}}
    with TestClient(create_app(tmp_path, TOKEN), headers={"X-Creator-Token": TOKEN}) as c:
        assert c.post("/runs", json=body).status_code == 202
        assert wait(c, body["id"])["status"] == "WAITING_ACCEPTANCE"
    assert seen["TOPIC_RESEARCH"] == "worker-model"
    assert seen["FACT_CHECK"] == "fact-model"
    # 未提供新快照的旧请求始终沿用 worker，不能静默替换为其他角色模型。
    assert seen["WRITER"] == "worker-model"


def test_live_consultant_model_must_be_explicitly_authorized(tmp_path, monkeypatch):
    from app import models

    monkeypatch.setenv("CREATOR_ENABLE_LIVE_MODELS", "true")
    monkeypatch.setenv("CREATOR_APPROVED_AGENT_MODELS", "allowed")
    # 这里只验证请求受理，避免触网和真实模型调用。
    monkeypatch.setattr(models, "build_model", lambda *args, **kwargs: None)
    body = request("run_unapproved_consultant")
    body["mode"] = "LIVE"
    body["models"] = {role: {"id": "allowed"} for role in ("worker", "supervisor", "reviewer")}
    body["models"]["consultant_FACT_CHECK"] = {"id": "not-authorized"}
    with TestClient(create_app(tmp_path, TOKEN), headers={"X-Creator-Token": TOKEN}) as c:
        response = c.post("/runs", json=body)
        assert response.status_code == 409
        assert c.get("/runs/" + body["id"]).status_code == 404


def test_six_serial_consultants_and_explicit_empty_comparison(tmp_path):
    body = request("run_six_consultants")
    body["consultationRoles"] = ["FACT_CHECK", "WRITER", "QUALITY", "AUDIO", "IMAGE", "VIDEO"]
    body["consultationComparison"] = True
    body["limits"].update(maxModelCalls=60, maxSeconds=120)
    with TestClient(create_app(tmp_path, TOKEN), headers={"X-Creator-Token": TOKEN}) as c:
        assert c.post("/runs", json=body).status_code == 202
        run = wait(c, body["id"])
        assert run["status"] == "WAITING_ACCEPTANCE", run
        candidate = next(a["content"] for a in run["artifacts"] if a["kind"] == "CANDIDATE")
        assert [o["role"] for o in candidate["consultations"]] == body["consultationRoles"]
        assert candidate["consultationComparison"]["differences"] == []
        assert "不代表意见完全一致" in candidate["consultationComparison"]["notice"]
        events = c.get(f"/runs/{body['id']}/events").json()
        assert [e["role"] for e in events if e["kind"] == "CONSULTATION_FINISHED"] == body["consultationRoles"]


def test_invalid_comparison_preserves_candidate_but_marks_human_review(tmp_path, monkeypatch):
    from app.models import FixtureModel

    original = FixtureModel._generate

    def with_invalid_quote(self, messages, stop=None, run_manager=None, **kwargs):
        result = original(self, messages, stop=stop, run_manager=run_manager, **kwargs)
        for call in result.generations[0].message.tool_calls:
            if call["name"] == "submit_candidate":
                call["args"]["consultation_comparison"] = {"summary": "主责的摘要", "differences": [{"topic": "测试", "positions": [
                    {"role": "FACT_CHECK", "quote": "伪造引用"}, {"role": "WRITER", "quote": "测试会诊意见"}]}]}
        return result

    monkeypatch.setattr(FixtureModel, "_generate", with_invalid_quote)
    body = request("run_invalid_comparison")
    body["consultationComparison"] = True
    with TestClient(create_app(tmp_path, TOKEN), headers={"X-Creator-Token": TOKEN}) as c:
        assert c.post("/runs", json=body).status_code == 202
        run = wait(c, body["id"])
        assert run["status"] == "WAITING_ACCEPTANCE", run
        candidate = next(a["content"] for a in run["artifacts"] if a["kind"] == "CANDIDATE")
        assert candidate["consultationComparison"]["status"] == "NEEDS_REVIEW"
        assert candidate["consultationComparison"]["differences"] == []
        assert len(candidate["consultations"]) == 2
        events = c.get(f"/runs/{body['id']}/events").json()
        assert any(e["kind"] == "CONSULTATION_COMPARISON_INCOMPLETE" for e in events)


def test_comparison_requires_auditable_distinct_role_quotes():
    from app.consultation import validate_comparison

    opinions = [
        {"role": "FACT_CHECK", "analysis": "证据尚不充分，建议复核", "sources": [], "uncertainties": [], "sha256": "a" * 64},
        {"role": "WRITER", "analysis": "可以先写成假设", "sources": ["材料B"], "uncertainties": [], "sha256": "b" * 64},
    ]
    base = {"summary": "需要人判断", "differences": [{"topic": "证据", "positions": [
        {"role": "FACT_CHECK", "quote": "证据尚不充分"}, {"role": "WRITER", "quote": "材料B"}]}]}
    result = validate_comparison(base, opinions)
    assert result["differences"][0]["positions"][0]["opinionHash"] == "a" * 64
    assert validate_comparison({"summary": "未列出分歧", "differences": []}, opinions)["differences"] == []
    for role, quote in [("FACT_CHECK", "证据尚不充分"), ("WRITER", ""), ("WRITER", "伪造文本"), ("UNKNOWN", "材料B")]:
        bad = json.loads(json.dumps(base, ensure_ascii=False))
        bad["differences"][0]["positions"][1].update(role=role, quote=quote)
        with pytest.raises(ValueError):
            validate_comparison(bad, opinions)
    with pytest.raises(ValueError):
        validate_comparison({"summary": " ", "differences": []}, opinions)
