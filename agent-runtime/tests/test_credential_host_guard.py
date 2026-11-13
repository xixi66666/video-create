import json

import pytest

from app import models


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setenv("CREATOR_ENABLE_LIVE_MODELS", "true")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-credential")
    monkeypatch.setenv("OTHER_PROVIDER_KEY", "other-test-credential")
    monkeypatch.setenv("CREATOR_CREDENTIAL_HOST_GUARDS", json.dumps({"DEEPSEEK_API_KEY": ["api.deepseek.com"]}))
    calls = []
    monkeypatch.setattr(models, "ChatOpenAI", lambda **kwargs: calls.append(kwargs) or kwargs)
    return calls


def snapshot(url, credential="DEEPSEEK_API_KEY"):
    return {"protocol": "CHAT_COMPLETIONS_COMPATIBLE", "baseUrl": url,
            "credentialRef": credential, "remoteModelId": "test-model"}


def build(url, credential="DEEPSEEK_API_KEY"):
    return models.build_model(snapshot(url, credential), "WRITER",
                              {"mode": "LIVE", "limits": {"maxOutputTokens": 100}})


def test_guarded_host_accepts_https_and_disables_redirects(live):
    result = build("https://api.deepseek.com/v1")
    assert result["api_key"] == "test-credential"
    assert result["http_client"].follow_redirects is False
    assert result["http_async_client"].follow_redirects is False
    result["http_client"].close()


@pytest.mark.parametrize("url", [
    "https://example.com/v1", "https://api.deepseek.com.example.com/v1",
    "https://api.deepseek.com@example.com/v1", "http://api.deepseek.com/v1",
    "https://api.deepseek.com:8443/v1", "https://api.deepseek.com/v1?key=x",
    "https://api.deepseek.com:invalid/v1",
])
def test_guarded_credential_never_constructs_client_for_other_destinations(live, url):
    with pytest.raises(ValueError, match="凭据目的地"):
        build(url)
    assert live == []


def test_other_providers_and_unconfigured_guard_keep_existing_behavior(live, monkeypatch):
    other = build("https://other-provider.example/v1", "OTHER_PROVIDER_KEY")
    assert "http_client" not in other
    monkeypatch.delenv("CREATOR_CREDENTIAL_HOST_GUARDS")
    unguarded = build("http://localhost:1234/v1")
    assert "http_client" not in unguarded


def test_invalid_guard_config_fails_closed(live, monkeypatch):
    monkeypatch.setenv("CREATOR_CREDENTIAL_HOST_GUARDS", "not-json")
    with pytest.raises(ValueError, match="目的地限制配置无效"):
        build("https://api.deepseek.com/v1")
    assert live == []
