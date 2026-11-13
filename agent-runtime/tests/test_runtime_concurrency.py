"""对恢复和并发决定的回归测试，不调用真实模型。"""
from concurrent.futures import ThreadPoolExecutor
import sqlite3
from threading import Barrier, RLock
from types import SimpleNamespace

import pytest

from app.engine import Engine, Execution
from app.storage import Store


def test_recovery_includes_old_running_tasks_outside_recent_list(tmp_path):
    store = Store(tmp_path)
    store.create("old-running", {})
    store.status("old-running", "RUNNING")
    store.create("old-queued", {})
    store.create("old-waiting", {})
    store.status("old-waiting", "WAITING_ACCEPTANCE")
    assert store.claim_decision("old-waiting", "ACCEPT") == "RECORDED"
    with store.lock, store.db:
        store.db.execute("UPDATE runs SET created_at=? WHERE id IN (?,?,?)",
                         ("2000-01-01", "old-running", "old-queued", "old-waiting"))
        for i in range(205):
            store.db.execute("INSERT INTO runs(id,payload,status,created_at,updated_at) VALUES(?,?,?,?,?)",
                             (f"finished-{i}", "{}", "ACCEPTED", f"2025-{i:03}", "2025"))
    assert "old-running" not in {row["id"] for row in store.list()}
    store.recover()
    assert store.get("old-running")["status"] == "UNKNOWN"
    assert {row["id"] for row in store.recoverable()} == {"old-queued", "old-waiting"}
    store.db.close()


def test_queue_limit_is_atomic_and_retry_remains_idempotent(tmp_path):
    from app.storage import QueueFull
    store = Store(tmp_path)
    gate = Barrier(52)
    def insert(i):
        gate.wait()
        try:
            return store.create(f"run-{i}", {"i": i}, max_pending=50)
        except QueueFull:
            return False
    with ThreadPoolExecutor(max_workers=52) as pool:
        outcomes = list(pool.map(insert, range(52)))
    assert sum(outcomes) == 50
    saved = store.db.execute("SELECT id,payload FROM runs LIMIT 1").fetchone()
    import json
    assert store.create(saved["id"], json.loads(saved["payload"]), max_pending=50) is False


def test_run_creation_and_audit_event_share_transaction(tmp_path):
    store = Store(tmp_path)
    with store.lock, store.db:
        store.db.execute("CREATE TRIGGER reject_created BEFORE INSERT ON events "
                         "WHEN NEW.kind='RUN_CREATED' BEGIN SELECT RAISE(ABORT, 'test'); END")
    with pytest.raises(sqlite3.IntegrityError):
        store.create("run-atomic", {"mode": "FIXTURE"}, created_event={"mode": "FIXTURE"})
    with pytest.raises(KeyError):
        store.get("run-atomic")
    with store.lock, store.db:
        store.db.execute("DROP TRIGGER reject_created")
    assert store.create("run-atomic", {"mode": "FIXTURE"}, created_event={"mode": "FIXTURE"})
    assert not store.create("run-atomic", {"mode": "FIXTURE"}, created_event={"mode": "FIXTURE"})
    assert [event["kind"] for event in store.events("run-atomic")] == ["RUN_CREATED"]
    store.db.close()


def test_conflicting_decisions_cannot_overwrite_each_other(tmp_path):
    store = Store(tmp_path)
    store.create("run-decision", {})
    store.status("run-decision", "WAITING_ACCEPTANCE")
    gate = Barrier(2)
    def decide(value):
        gate.wait()
        return store.claim_decision("run-decision", value)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(decide, ("ACCEPT", "REJECT")))
    assert sorted(results) == ["CONFLICT", "RECORDED"]
    assert store.get("run-decision")["decision"] in {"ACCEPT", "REJECT"}


def test_cancel_cannot_erase_recorded_human_decision(tmp_path):
    store = Store(tmp_path)
    store.create("run-decided", {})
    store.status("run-decided", "WAITING_ACCEPTANCE")
    assert store.claim_decision("run-decided", "ACCEPT") == "RECORDED"
    assert store.cancel("run-decided") is False
    assert store.get("run-decided")["decision"] == "ACCEPT"
    assert store.get("run-decided")["status"] == "WAITING_ACCEPTANCE"


def test_decision_arriving_before_active_run_released_is_not_lost(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.create("run-race", {"mode": "FIXTURE"})
    engine = Engine(store, tmp_path)
    calls = []
    class FakeGraph:
        def invoke(self, arg, config):
            calls.append(arg)
            return {"__interrupt__": [object()]} if len(calls) == 1 else {"accepted": True}
    monkeypatch.setattr(Execution, "graph", lambda *args: FakeGraph())
    original = store.transition
    def transition(run_id, status, kind, *args, **kwargs):
        result = original(run_id, status, kind, *args, **kwargs)
        if kind == "HUMAN_ACCEPTANCE_REQUIRED":
            store.claim_decision(run_id, "ACCEPT")
            engine.run(run_id, "ACCEPT")  # 此时原工作线程尚在 active 中。
        return result
    monkeypatch.setattr(store, "transition", transition)
    engine.run("run-race")
    assert len(calls) == 2
    assert store.get("run-race")["status"] == "ACCEPTED"
    engine.connection.close()
    store.db.close()


def test_call_limit_counts_events_beyond_display_pagination(tmp_path):
    from app.engine import Guard
    store = Store(tmp_path)
    store.create("run-many-events", {})
    store.status("run-many-events", "RUNNING")
    for _ in range(501):
        store.event("run-many-events", "TOOL_STARTED")
    for _ in range(3):
        store.event("run-many-events", "MODEL_STARTED")
    execution = SimpleNamespace(id="run-many-events", store=store, lock=RLock(),
                                payload={"limits": {"maxModelCalls": 3}}, check=lambda: None,
                                emit=lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match="模型调用次数上限"):
        Guard(execution, "WRITER").wrap_model_call(None, lambda request: pytest.fail("超过调用限制时不能调用模型"))
    store.db.close()


def test_cancel_before_model_reservation_prevents_provider_call(tmp_path, monkeypatch):
    from app.engine import Guard
    store = Store(tmp_path)
    store.create("run-cancel-reserve", {})
    store.status("run-cancel-reserve", "RUNNING")
    original = store.reserve_model_call
    def cancel_first(*args, **kwargs):
        assert store.cancel("run-cancel-reserve")
        return original(*args, **kwargs)
    monkeypatch.setattr(store, "reserve_model_call", cancel_first)
    execution = SimpleNamespace(id="run-cancel-reserve", store=store, lock=RLock(),
                                payload={"limits": {"maxModelCalls": 3}}, check=lambda: None,
                                emit=lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match="取消|运行状态"):
        Guard(execution, "WRITER").wrap_model_call(None, lambda request: pytest.fail("取消后不可预留新调用"))
    assert [e["kind"] for e in store.events("run-cancel-reserve")] == ["CANCELLED"]
    store.db.close()


def test_model_reservation_preceding_cancel_remains_a_started_call(tmp_path):
    from app.engine import Guard
    store = Store(tmp_path)
    store.create("run-reserve-cancel", {})
    store.status("run-reserve-cancel", "RUNNING")
    execution = SimpleNamespace(id="run-reserve-cancel", store=store, lock=RLock(),
                                payload={"mode": "FIXTURE", "limits": {"maxModelCalls": 3}},
                                check=lambda: None, emit=lambda kind, role, **data: store.event("run-reserve-cancel", kind, role, **data))
    def provider(request):
        assert store.cancel("run-reserve-cancel")
        return SimpleNamespace(result=[])
    Guard(execution, "WRITER").wrap_model_call(None, provider)
    assert [e["kind"] for e in store.events("run-reserve-cancel")] == ["MODEL_STARTED", "CANCELLED", "MODEL_FINISHED"]
    store.db.close()


def test_live_idempotent_retry_survives_later_shutdown(tmp_path, monkeypatch):
    """重投已有运行只返回持久状态，即使操作者后来关闭 LIVE 也不能误报未受理。"""
    from fastapi.testclient import TestClient
    from app.main import create_app
    from test_runtime import request
    monkeypatch.setenv("CREATOR_ENABLE_LIVE_MODELS", "true")
    monkeypatch.setenv("CREATOR_APPROVED_AGENT_MODELS", "test-model")
    monkeypatch.setattr("app.models.build_model", lambda *args, **kwargs: None)
    app = create_app(tmp_path, "test-token")
    monkeypatch.setattr(app.state.engine, "run", lambda *args, **kwargs: None)
    body = request("run_retry_live_0001")
    body.update(mode="LIVE", models={key: {"id": "test-model"} for key in ("supervisor", "worker", "reviewer")})
    with TestClient(app, headers={"X-Creator-Token": "test-token"}) as client:
        assert client.post("/runs", json=body).status_code == 202
        monkeypatch.setenv("CREATOR_ENABLE_LIVE_MODELS", "false")
        assert client.post("/runs", json=body).status_code == 202
        body["input"]["brief"] = "different"
        assert client.post("/runs", json=body).status_code == 400


def test_input_limit_counts_utf8_bytes_not_json_escape_length(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from test_runtime import request
    app = create_app(tmp_path, "test-token")
    monkeypatch.setattr(app.state.engine, "run", lambda *args, **kwargs: None)
    with TestClient(app, headers={"X-Creator-Token": "test-token"}) as client:
        body = request("run_utf8_test_0001")
        body["input"]["brief"] = "中" * 70000
        assert client.post("/runs", json=body).status_code == 202
        body["id"] = "run_utf8_test_0002"
        body["input"]["brief"] = "中" * 140000
        assert client.post("/runs", json=body).status_code == 400


def test_untrusted_valueerror_does_not_leak_to_run_error(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.create("run-valueerror", {"mode": "LIVE"})
    engine = Engine(store, tmp_path)
    class FailingGraph:
        def invoke(self, *args):
            raise ValueError("provider data contains test-private-key")
    monkeypatch.setattr(Execution, "graph", lambda *args: FailingGraph())
    engine.run("run-valueerror")
    run = store.get("run-valueerror")
    assert run["status"] == "UNKNOWN"
    assert "test-private-key" not in run["error"]
    engine.connection.close()
    store.db.close()


def test_untrusted_model_configuration_failure_is_sanitized(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from test_runtime import request
    monkeypatch.setenv("CREATOR_ENABLE_LIVE_MODELS", "true")
    monkeypatch.setenv("CREATOR_APPROVED_AGENT_MODELS", "test-model")
    def bad_model(*args, **kwargs):
        raise ValueError("provider supplied test-private-key")
    monkeypatch.setattr("app.models.build_model", bad_model)
    body = request("run_invalid_model_0001")
    body.update(mode="LIVE", models={key: {"id": "test-model"} for key in ("supervisor", "worker", "reviewer")})
    with TestClient(create_app(tmp_path, "test-token"), headers={"X-Creator-Token": "test-token"}) as client:
        response = client.post("/runs", json=body)
        assert response.status_code == 400
        assert "test-private-key" not in response.text


def test_cancelled_run_does_not_emit_late_success_or_wait_event(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.create("run-cancelled", {"mode": "FIXTURE"})
    engine = Engine(store, tmp_path)
    class Graph:
        def invoke(self, *args):
            assert store.cancel("run-cancelled")
            return {"accepted": True}
    monkeypatch.setattr(Execution, "graph", lambda *args: Graph())
    engine.run("run-cancelled")
    assert store.get("run-cancelled")["status"] == "CANCELLED"
    assert [e["kind"] for e in store.events("run-cancelled")] == ["CANCELLED"]
    engine.connection.close()
    store.db.close()


def test_invalid_decision_and_live_model_shapes_return_client_errors(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from test_runtime import request
    app = create_app(tmp_path, "test-token")
    app.state.store.create("run_bad_decision", {})
    app.state.store.status("run_bad_decision", "WAITING_ACCEPTANCE")
    monkeypatch.setenv("CREATOR_ENABLE_LIVE_MODELS", "true")
    monkeypatch.setenv("CREATOR_APPROVED_AGENT_MODELS", "test-model")
    with TestClient(app, headers={"X-Creator-Token": "test-token"}) as client:
        assert client.post("/runs/run_bad_decision/decision", json={"decision": []}).status_code == 400
        body = request("run_bad_model_0001")
        body.update(mode="LIVE", models={"worker": {}, "supervisor": [], "reviewer": {}})
        assert client.post("/runs", json=body).status_code in {400, 409}


def test_recovered_live_queued_run_checks_current_model_authorization(tmp_path, monkeypatch):
    """已受理任务重启后也不能调用已撤销授权的模型。"""
    from app.models import FixtureModel
    from app.profiles import load_profiles
    from test_runtime import request
    body = request("run_recovered_live")
    body.pop("id")
    body.update(mode="LIVE", models={key: {"id": "previously-approved"}
                                     for key in ("supervisor", "worker", "reviewer")})
    profiles = load_profiles()
    body["profiles"] = {role: profiles[role] for role in ("SUPERVISOR", "REVIEWER", body["node"]["agentRole"])}
    store = Store(tmp_path)
    store.create("run_recovered_live", body)
    monkeypatch.setenv("CREATOR_ENABLE_LIVE_MODELS", "true")
    monkeypatch.setenv("CREATOR_APPROVED_AGENT_MODELS", "different-model")
    monkeypatch.setattr("app.engine.build_model", lambda snapshot, role, payload, attempt: FixtureModel(role=role, node=payload["node"]))
    monkeypatch.setattr(FixtureModel, "_generate", lambda *args, **kwargs: pytest.fail("未授权模型不能被调用"))
    engine = Engine(store, tmp_path)
    engine.run("run_recovered_live")
    result = store.get("run_recovered_live")
    assert result["status"] == "UNKNOWN"
    assert "白名单" in result["error"]
    assert store.count_events("run_recovered_live", "MODEL_STARTED") == 0
    engine.connection.close()
    store.db.close()


def test_consultant_call_checks_its_own_model_authorization(tmp_path, monkeypatch):
    from app.engine import Guard
    store = Store(tmp_path)
    store.create("run-consultant", {})
    monkeypatch.setenv("CREATOR_ENABLE_LIVE_MODELS", "true")
    monkeypatch.setenv("CREATOR_APPROVED_AGENT_MODELS", "worker-allowed")
    payload = {"mode": "LIVE", "limits": {"maxModelCalls": 10}, "consultationRoles": ["FACT_CHECK"],
               "models": {"worker": {"id": "worker-allowed"}, "consultant_FACT_CHECK": {"id": "consultant-revoked"}}}
    execution = SimpleNamespace(id="run-consultant", store=store, lock=RLock(), payload=payload,
                                check=lambda: None, emit=lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match="白名单"):
        Guard(execution, "FACT_CHECK").wrap_model_call(None, lambda request: pytest.fail("会诊模型未经授权"))
    assert store.count_events("run-consultant", "MODEL_STARTED") == 0
    store.db.close()


def test_live_switch_is_rechecked_before_each_model_call(tmp_path, monkeypatch):
    from app.engine import Guard
    store = Store(tmp_path)
    store.create("run-switch", {})
    monkeypatch.setenv("CREATOR_ENABLE_LIVE_MODELS", "false")
    monkeypatch.setenv("CREATOR_APPROVED_AGENT_MODELS", "approved")
    payload = {"mode": "LIVE", "limits": {"maxModelCalls": 10}, "models": {"worker": {"id": "approved"}}}
    execution = SimpleNamespace(id="run-switch", store=store, lock=RLock(), payload=payload,
                                check=lambda: None, emit=lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match="开关关闭"):
        Guard(execution, "WRITER").wrap_model_call(None, lambda request: pytest.fail("开关关闭后不可调用模型"))
    assert store.count_events("run-switch", "MODEL_STARTED") == 0
    store.db.close()
