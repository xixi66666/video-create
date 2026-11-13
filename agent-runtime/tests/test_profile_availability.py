from fastapi.testclient import TestClient
from app.main import create_app
import json
import time
from pathlib import Path
from app.profiles import load_profiles


def test_profiles_distinguish_declared_and_registered_tools(tmp_path, monkeypatch):
    monkeypatch.setenv('CREATOR_ENABLE_LIVE_MODELS', 'true')
    monkeypatch.setenv('CREATOR_RESEARCH_ENABLED', 'true')
    monkeypatch.delenv('CREATOR_RESEARCH_ALLOWED_HOSTS', raising=False)
    monkeypatch.delenv('CREATOR_RESEARCH_SEARCH_URL', raising=False)
    monkeypatch.delenv('CREATOR_RESEARCH_PROVIDER', raising=False)
    app = create_app(tmp_path, 'test-token')
    with TestClient(app, headers={'X-Creator-Token': 'test-token'}) as client:
        profiles = {p['id']: p for p in client.get('/profiles').json()}
        for role in ('PACKAGING', 'PUBLISHER', 'BUSINESS'):
            p = profiles[role]
            assert 'read_research_page' in p['declaredTools']
            assert 'read_research_page' not in p['availableTools']['FIXTURE']
            assert 'read_research_page' not in p['availableTools']['LIVE']
            assert p['tools'] == p['availableTools']['FIXTURE']
        monkeypatch.setenv('CREATOR_RESEARCH_ALLOWED_HOSTS', 'docs.example,search.example')
        monkeypatch.setenv('CREATOR_RESEARCH_SEARCH_URL', 'https://search.example/search')
        profiles = {p['id']: p for p in client.get('/profiles').json()}
        for role in ('PACKAGING', 'PUBLISHER', 'BUSINESS'):
            assert {'read_research_page', 'search_research_sources'} <= set(profiles[role]['availableTools']['LIVE'])
        monkeypatch.setenv('CREATOR_ENABLE_LIVE_MODELS', 'false')
        assert not next(p for p in client.get('/profiles').json() if p['id'] == 'BUSINESS')['availableTools']['LIVE']


def test_legacy_skill_snapshot_still_executes(tmp_path, monkeypatch):
    profiles = load_profiles()
    legacy_names = {'SUPERVISOR': 'production-supervisor', 'REVIEWER': 'independent-review', 'ANALYST': 'analyst-production'}
    for role, old_name in legacy_names.items():
        current = role.lower().replace('_', '-') + '-skill'
        profiles[role]['skill'] = profiles[role]['skill'].replace(f'name: {current}\n', f'name: {old_name}\n', 1)
    monkeypatch.setattr('app.main.load_profiles', lambda: profiles)
    root = Path(__file__).resolve().parents[2]
    nodes = json.loads((root / 'specs/nodes.json').read_text(encoding='utf-8'))['nodes']
    node = next(n for n in nodes if n['agentRole'] == 'ANALYST')
    payload = {'id': 'run_legacy_skill_0001', 'projectId': 'test', 'mode': 'FIXTURE',
               'node': node, 'input': {'brief': '测试旧快照', 'dependencies': {}},
               'models': {}, 'inputFingerprint': 'legacy', 'executionMode': 'GENERATE_TEXT',
               'limits': {'maxModelCalls': 30, 'maxSeconds': 60, 'maxReworks': 1}}
    with TestClient(create_app(tmp_path, 'token'), headers={'X-Creator-Token': 'token'}) as client:
        assert client.post('/runs', json=payload).status_code == 202
        for _ in range(200):
            result = client.get('/runs/' + payload['id']).json()
            if result['status'] in {'WAITING_ACCEPTANCE', 'FAILED', 'UNKNOWN'}:
                break
            time.sleep(.05)
        assert result['status'] == 'WAITING_ACCEPTANCE', result
