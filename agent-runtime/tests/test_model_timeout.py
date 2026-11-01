from app import models


def test_local_cpu_timeout_does_not_change_remote_timeout(monkeypatch):
    monkeypatch.setenv('CREATOR_ENABLE_LIVE_MODELS', 'true')
    monkeypatch.setenv('CREATOR_TEST_LOCAL_REF', 'YOUR_TOKEN_HERE')
    calls = []
    monkeypatch.setattr(models, 'ChatOpenAI', lambda **kwargs: calls.append(kwargs) or object())
    snapshot = {'protocol': 'CHAT_COMPLETIONS_COMPATIBLE', 'credentialRef': 'CREATOR_TEST_LOCAL_REF',
                'remoteModelId': 'test-model', 'baseUrl': 'http://127.0.0.1:1234/v1', 'parameters': {}}
    payload = {'mode': 'LIVE', 'limits': {'maxOutputTokens': 1200}}
    models.build_model(snapshot, 'POSITIONING', payload)
    assert calls[-1]['timeout'] == 90
    snapshot['baseUrl'] = 'https://provider.example.invalid/v1'
    models.build_model(snapshot, 'POSITIONING', payload)
    assert calls[-1]['timeout'] == 45
