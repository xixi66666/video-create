import json
import hashlib
import time
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import create_app
from app.models import FixtureModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "isolated-fixture-test-token"


def request(run="run_fixture_0001"):
    nodes = json.loads((ROOT / "specs/nodes.json").read_text(encoding="utf-8"))["nodes"]
    return {"id": run, "projectId": "test", "mode": "FIXTURE", "node": next(n for n in nodes if n["id"] == "N08"),
        "input": {"brief": "测试创作想法", "dependencies": {}}, "models": {}, "inputFingerprint": "test",
        "executionMode": "GENERATE_TEXT", "limits": {"maxModelCalls": 30, "maxTotalTokens": 10000,
        "maxOutputTokens": 1200, "maxSeconds": 60, "maxReworks": 1}}


def wait(client, run, status):
    for _ in range(200):
        body = client.get(f"/runs/{run}").json()
        if body["status"] in status:
            return body
        time.sleep(.05)
    raise AssertionError(body)


def test_real_delegation_review_rework_and_resume(tmp_path):
    app = create_app(tmp_path, TOKEN)
    with TestClient(app, headers={"X-Creator-Token": TOKEN}) as c:
        body = request()
        response = c.post("/runs", json=body)
        assert response.status_code == 202, response.text
        run = wait(c, body["id"], {"WAITING_ACCEPTANCE", "FAILED", "UNKNOWN"})
        assert run["status"] == "WAITING_ACCEPTANCE", run
        events = c.get(f"/runs/{body['id']}/events").json()
        assert any(e["kind"] == "TOOL_STARTED" and e["data"]["tool"] == "task" for e in events)
        assert any(e["role"] == "TOPIC_RESEARCH" and e["kind"] == "AGENT_STARTED" for e in events)
        assert [e["data"]["verdict"] for e in events if e["kind"] == "REVIEW_FINISHED"] == ["REVISE", "PASS"]
        assert len([a for a in run["artifacts"] if a["kind"] == "CANDIDATE"]) == 2
        assert c.post("/runs", json=body).status_code == 202  # 幂等重投，不重复执行
        before = len(events)
        assert len(c.get(f"/runs/{body['id']}/events").json()) == before
        assert c.post(f"/runs/{body['id']}/decision", json={"decision": "ACCEPT"}).status_code == 200
        assert wait(c, body["id"], {"ACCEPTED", "FAILED"})["status"] == "ACCEPTED"
        assert c.post(f"/runs/{body['id']}/decision", json={"decision": "ACCEPT"}).status_code == 200


def test_expert_continues_after_claiming_completion_without_submitting(tmp_path, monkeypatch):
    original = FixtureModel._generate
    def ends_early(self, messages, stop=None, run_manager=None, **kwargs):
        has_input = any(isinstance(m, ToolMessage) and m.name == 'read_inputs' for m in messages)
        prompted = any(isinstance(m, HumanMessage) and '尚未成功提交候选' in str(m.content) for m in messages)
        if self.role not in {'SUPERVISOR', 'REVIEWER'} and has_input and not prompted:
            message = AIMessage(content='已完成。')
            message.usage_metadata = {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}
            return ChatResult(generations=[ChatGeneration(message=message)])
        return original(self, messages, stop=stop, run_manager=run_manager, **kwargs)
    monkeypatch.setattr(FixtureModel, '_generate', ends_early)
    body = request('run_continued_expert')
    body['fixtureRework'] = False
    with TestClient(create_app(tmp_path, TOKEN), headers={'X-Creator-Token': TOKEN}) as c:
        assert c.post('/runs', json=body).status_code == 202
        result = wait(c, body['id'], {'WAITING_ACCEPTANCE', 'FAILED', 'UNKNOWN'})
        assert result['status'] == 'WAITING_ACCEPTANCE', result
        events = c.get(f"/runs/{body['id']}/events").json()
        assert any(e['kind'] == 'AGENT_CONTINUED' and e['role'] == 'TOPIC_RESEARCH' for e in events)
        assert any(e['kind'] == 'TOOL_FINISHED' and e['data'].get('tool') == 'submit_candidate' for e in events)


def test_supervisor_continues_after_ending_without_delegation(tmp_path, monkeypatch):
    original = FixtureModel._generate
    def ends_early(self, messages, stop=None, run_manager=None, **kwargs):
        reads = sum(isinstance(m, ToolMessage) and m.name == 'read_file' for m in messages)
        prompted = any(isinstance(m, HumanMessage) and '尚无专家候选' in str(m.content) for m in messages)
        if self.role == 'SUPERVISOR' and reads >= 2 and not prompted:
            message = AIMessage(content='已完成。')
            message.usage_metadata = {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}
            return ChatResult(generations=[ChatGeneration(message=message)])
        return original(self, messages, stop=stop, run_manager=run_manager, **kwargs)
    monkeypatch.setattr(FixtureModel, '_generate', ends_early)
    body = request('run_continued_supervisor')
    body['fixtureRework'] = False
    with TestClient(create_app(tmp_path, TOKEN), headers={'X-Creator-Token': TOKEN}) as c:
        assert c.post('/runs', json=body).status_code == 202
        result = wait(c, body['id'], {'WAITING_ACCEPTANCE', 'FAILED', 'UNKNOWN'})
        assert result['status'] == 'WAITING_ACCEPTANCE', result
        events = c.get(f"/runs/{body['id']}/events").json()
        assert any(e['kind'] == 'AGENT_CONTINUED' and e['role'] == 'SUPERVISOR' for e in events)
        assert any(e['kind'] == 'TOOL_STARTED' and e['data'].get('tool') == 'task' for e in events)


def test_completed_delegation_cannot_be_repeated():
    from types import SimpleNamespace
    from app.engine import Guard
    class ExecutionStub:
        delegate_completed = True
        payload = {'node': {'agentRole': 'POSITIONING'}}
        def check(self): pass
        def emit(self, *args, **kwargs): pass
    request = SimpleNamespace(tool_call={'name': 'task', 'args': {'subagent_type': 'POSITIONING'}, 'id': 'duplicate'})
    result = Guard(ExecutionStub(), 'SUPERVISOR').wrap_tool_call(request, lambda _: pytest.fail('重复委派不应执行'))
    assert isinstance(result, ToolMessage) and result.status == 'error'


def test_prerequisite_errors_recover_without_skipping_actual_reads(tmp_path, monkeypatch):
    """模型先越过前置步骤，再读完后重试；委派、候选和评审不得提前执行。"""
    original = FixtureModel._generate

    def violate_once(self, messages, stop=None, run_manager=None, **kwargs):
        name = 'task' if self.role == 'SUPERVISOR' else 'submit_review' if self.role == 'REVIEWER' else 'submit_candidate'
        if not any(isinstance(m, ToolMessage) and m.name == name and m.status == 'error' for m in messages):
            args = ({'subagent_type': self.node['agentRole'], 'description': '执行当前任务'} if name == 'task' else
                    {'verdict': 'PASS', 'issues': [], 'summary': '通过'} if name == 'submit_review' else
                    {'fields': {k: '候选' for k in self.node['output']['requiredFields']}, 'body': '候选', 'sources': [], 'uncertainties': []})
            message = AIMessage(content='', tool_calls=[{'name': name, 'args': args, 'id': 'deliberate-'+name}])
            message.usage_metadata = {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}
            return ChatResult(generations=[ChatGeneration(message=message)])
        clean = [m for m in messages if not (isinstance(m, ToolMessage) and m.status == 'error')]
        return original(self, clean, stop=stop, run_manager=run_manager, **kwargs)

    monkeypatch.setattr(FixtureModel, '_generate', violate_once)
    body = request('run_prerequisite_0001')
    body['node'] = next(n for n in NODES if n['id'] == 'N02')
    body['fixtureRework'] = False
    with TestClient(create_app(tmp_path, TOKEN), headers={'X-Creator-Token': TOKEN}) as c:
        assert c.post('/runs', json=body).status_code == 202
        result = wait(c, body['id'], {'WAITING_ACCEPTANCE', 'FAILED', 'UNKNOWN'})
        assert result['status'] == 'WAITING_ACCEPTANCE', result
        events = c.get(f"/runs/{body['id']}/events").json()
        for role, target in [('SUPERVISOR', 'task'), ('POSITIONING', 'submit_candidate'), ('REVIEWER', 'submit_review')]:
            role_events = [e for e in events if e['role'] == role]
            blocked = next(i for i, e in enumerate(role_events) if e['kind'] == 'TOOL_BLOCKED' and e['data']['tool'] == target)
            executed = next(i for i, e in enumerate(role_events) if e['kind'] == 'TOOL_STARTED' and e['data']['tool'] == target)
            prior = role_events[blocked + 1:executed]
            assert sum(e['kind'] == 'TOOL_FINISHED' and e['data']['tool'] == 'read_file' for e in prior) >= 2
            if role == 'POSITIONING':
                assert any(e['kind'] == 'TOOL_FINISHED' and e['data']['tool'] == 'read_inputs' for e in prior)


def test_failed_file_read_never_satisfies_precondition():
    from types import SimpleNamespace
    from app.engine import Guard
    class ExecutionStub:
        def __init__(self):
            self.reads = set()
            self.payload = {'node': {'agentRole': 'POSITIONING'}}
        def check(self): pass
        def emit(self, *args, **kwargs): pass
    execution = ExecutionStub()
    guard = Guard(execution, 'SUPERVISOR')
    req = SimpleNamespace(tool_call={'name': 'read_file', 'args': {'file_path': '/skills/SUPERVISOR/SKILL.md'}, 'id': 'bad-read'})
    error = ToolMessage(content='not found', name='read_file', tool_call_id='bad-read', status='error')
    guard.wrap_tool_call(req, lambda _: error)
    assert not execution.reads


def test_profile_snapshot_includes_concrete_prerequisite_instructions():
    from app.profiles import load_profiles
    profiles = load_profiles()
    for role in ('SUPERVISOR', 'POSITIONING', 'REVIEWER'):
        item = profiles[role].copy()
        expected = item.pop('sha256')
        assert f'/skills/{role}/SKILL.md' in item['prompt']
        assert f'/knowledge/{role}.md' in item['prompt']
        assert hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest() == expected


def test_auth_and_live_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("CREATOR_ENABLE_LIVE_MODELS", "false")
    with TestClient(create_app(tmp_path, TOKEN)) as c:
        assert c.get("/health").status_code == 401
        c.headers["X-Creator-Token"] = TOKEN
        body = request()
        body["mode"] = "LIVE"
        assert c.post("/runs", json=body).status_code == 409
        body["mode"] = "FIXTURE"
        body["limits"]["maxModelCalls"] = 999
        assert c.post("/runs", json=body).status_code == 400


def test_live_requires_explicit_model_allowlist_without_network(tmp_path, monkeypatch):
    monkeypatch.setenv("CREATOR_ENABLE_LIVE_MODELS", "true")
    monkeypatch.delenv("CREATOR_APPROVED_AGENT_MODELS", raising=False)
    with TestClient(create_app(tmp_path, TOKEN), headers={"X-Creator-Token": TOKEN}) as c:
        body = request("run_unauthorized_live")
        body["mode"] = "LIVE"
        assert c.post("/runs", json=body).status_code == 409


def test_checkpoint_survives_restart_and_usage_limit(tmp_path):
    body = request("run_restart_0001")
    with TestClient(create_app(tmp_path, TOKEN), headers={"X-Creator-Token": TOKEN}) as c:
        c.post("/runs", json=body)
        assert wait(c, body["id"], {"WAITING_ACCEPTANCE", "FAILED"})["status"] == "WAITING_ACCEPTANCE"
    with TestClient(create_app(tmp_path, TOKEN), headers={"X-Creator-Token": TOKEN}) as c:
        assert c.post(f"/runs/{body['id']}/decision", json={"decision": "REJECT"}).status_code == 200
        assert wait(c, body["id"], {"REJECTED", "FAILED"})["status"] == "REJECTED"
        limited = request("run_limited_0001")
        limited["limits"]["maxModelCalls"] = 3
        c.post("/runs", json=limited)
        result = wait(c, limited["id"], {"FAILED", "WAITING_ACCEPTANCE"})
        assert result["status"] == "FAILED"
        events = c.get(f"/runs/{limited['id']}/events").json()
        assert len([e for e in events if e["kind"] == "MODEL_STARTED"]) == 3


def test_unlimited_tokens_and_saved_explicit_limit(tmp_path, monkeypatch):
    """累计 token 为零时不拦截，旧快照中的正数上限仍会执行。"""
    original = FixtureModel._generate
    def usage_heavy(self, messages, stop=None, run_manager=None, **kwargs):
        result = original(self, messages, stop=stop, run_manager=run_manager, **kwargs)
        result.generations[0].message.usage_metadata = {'input_tokens': 20000, 'output_tokens': 10, 'total_tokens': 20010}
        return result
    monkeypatch.setattr(FixtureModel, '_generate', usage_heavy)
    with TestClient(create_app(tmp_path, TOKEN), headers={'X-Creator-Token': TOKEN}) as c:
        unlimited = request('run_unlimited_tokens')
        unlimited['limits']['maxTotalTokens'] = 0
        unlimited['fixtureRework'] = False
        assert c.post('/runs', json=unlimited).status_code == 202
        assert wait(c, unlimited['id'], {'WAITING_ACCEPTANCE', 'FAILED'})['status'] == 'WAITING_ACCEPTANCE'
        limited = request('run_legacy_token_cap')
        limited['limits']['maxTotalTokens'] = 20000
        assert c.post('/runs', json=limited).status_code == 202
        assert wait(c, limited['id'], {'WAITING_ACCEPTANCE', 'FAILED'})['status'] == 'FAILED'


NODES = json.loads((ROOT / "specs/nodes.json").read_text(encoding="utf-8"))["nodes"]


@pytest.mark.parametrize("node", NODES, ids=lambda n: n["id"])
def test_all_node_contracts_and_independent_role_packages(tmp_path, node):
    """49 节点框架合同验收，输入为隔离夹具，不等同于跨节点业务或领域验收。"""
    body = request("run_contract_" + node["id"])
    body["node"], body["fixtureRework"] = node, False
    with TestClient(create_app(tmp_path, TOKEN), headers={"X-Creator-Token": TOKEN}) as c:
        assert c.post("/runs", json=body).status_code == 202
        run = wait(c, body["id"], {"WAITING_ACCEPTANCE", "FAILED"})
        assert run["status"] == "WAITING_ACCEPTANCE", run
        candidate = next(a["content"] for a in run["artifacts"] if a["kind"] == "CANDIDATE")
        assert set(node["output"]["requiredFields"]) <= candidate["fields"].keys()
        assert candidate["fixture"] is True
