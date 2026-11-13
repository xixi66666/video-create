"""实时参数的离线合同测试，不发送模型请求。"""
import pytest
from langchain_core.messages import HumanMessage

from app.models import build_model


@pytest.fixture
def snapshot(monkeypatch):
    monkeypatch.setenv("CREATOR_ENABLE_LIVE_MODELS", "true")
    monkeypatch.setenv("CREATOR_TEST_REASONING_KEY", "test-only")
    monkeypatch.delenv("CREATOR_CREDENTIAL_HOST_GUARDS", raising=False)
    return {"protocol": "CHAT_COMPLETIONS_COMPATIBLE", "baseUrl": "https://example.invalid",
            "credentialRef": "CREATOR_TEST_REASONING_KEY", "remoteModelId": "test-model", "parameters": {}}


def build(snapshot):
    return build_model(snapshot, "WRITER", {"mode": "LIVE", "limits": {"maxOutputTokens": 100}})


def test_explicit_none_is_a_top_level_chat_completion_parameter(snapshot):
    snapshot["parameters"] = {"reasoning_effort": "none", "temperature": 0}
    model = build(snapshot)
    request = model._get_request_payload([HumanMessage(content="离线测试")])
    assert request["reasoning_effort"] == "none"
    assert request["temperature"] == 0
    assert model.max_retries == 0


def test_unset_does_not_change_default_payload(snapshot):
    request = build(snapshot)._get_request_payload([HumanMessage(content="离线测试")])
    assert "reasoning_effort" not in request
    assert "max_tokens" not in request and "max_completion_tokens" not in request


@pytest.mark.parametrize("value", ["low", "high", "max", "", None, {}, 0, False])
def test_unsupported_values_rejected(snapshot, value):
    snapshot["parameters"] = {"reasoning_effort": value}
    with pytest.raises(ValueError, match="reasoning_effort"):
        build(snapshot)


def test_responses_protocol_rejects_effort(snapshot):
    snapshot["protocol"] = "RESPONSES"
    snapshot["parameters"] = {"reasoning_effort": "none"}
    with pytest.raises(ValueError, match="reasoning_effort"):
        build(snapshot)
