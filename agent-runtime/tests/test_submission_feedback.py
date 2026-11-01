from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.engine import Guard
from app.main import create_app
from app.models import FixtureModel
from test_runtime import NODES, TOKEN, request, wait


class StubExecution:
    def __init__(self, role):
        self.reads = {(role, f'/skills/{role}/SKILL.md'), (role, f'/knowledge/{role}.md'), (role, 'INPUTS')}
        self.payload = {'node': {'agentRole': 'POSITIONING', 'output': {'requiredFields': ['skills', 'resources']}}}
        self.events = []
    def check(self): pass
    def emit(self, kind, role, **data): self.events.append((kind, role, data))


@pytest.mark.parametrize('role,tool,error,expected', [
    ('POSITIONING', 'submit_candidate', '缺少必填交付字段', 'skills'),
    ('REVIEWER', 'submit_review', '评审结构不合法', 'verdict'),
])
def test_recoverable_tool_validation_errors_are_returned_to_model(role, tool, error, expected):
    execution = StubExecution(role)
    req = SimpleNamespace(tool_call={'name': tool, 'args': {}, 'id': 'invalid'})
    def fail(_): raise ValueError(error)
    response = Guard(execution, role).wrap_tool_call(req, fail)
    assert isinstance(response, ToolMessage)
    assert response.status == 'error'
    assert response.tool_call_id == 'invalid'
    assert expected in response.content
    assert execution.events[-1][0] == 'TOOL_BLOCKED'


def test_timeout_remains_fatal_and_is_not_turned_into_a_retry():
    execution = StubExecution('POSITIONING')
    req = SimpleNamespace(tool_call={'name': 'submit_candidate', 'args': {}, 'id': 'timeout'})
    def fail(_): raise ValueError('达到运行时间上限')
    with pytest.raises(ValueError, match='运行时间上限'):
        Guard(execution, 'POSITIONING').wrap_tool_call(req, fail)


def test_model_corrects_invalid_candidate_and_review_without_fake_submission(tmp_path, monkeypatch):
    original = FixtureModel._generate

    def bad_then_correct(self, messages, stop=None, run_manager=None, **kwargs):
        name = 'submit_review' if self.role == 'REVIEWER' else 'submit_candidate'
        used = [m.name for m in messages if isinstance(m, ToolMessage)]
        ready = used.count('read_file') >= 2 and (self.role == 'REVIEWER' or 'read_inputs' in used)
        failed = any(isinstance(m, ToolMessage) and m.name == name and m.status == 'error' for m in messages)
        if self.role != 'SUPERVISOR' and ready and not failed and name not in used:
            args = ({'verdict': 'PASS', 'issues': [], 'summary': ''} if self.role == 'REVIEWER' else
                    {'fields': {}, 'body': '内容', 'sources': [], 'uncertainties': []})
            message = AIMessage(content='', tool_calls=[{'name': name, 'args': args, 'id': 'invalid-'+name}])
            return ChatResult(generations=[ChatGeneration(message=message)])
        cleaned = [m for m in messages if not (isinstance(m, ToolMessage) and m.status == 'error')]
        return original(self, cleaned, stop=stop, run_manager=run_manager, **kwargs)

    monkeypatch.setattr(FixtureModel, '_generate', bad_then_correct)
    body = request('run_invalid_then_fix')
    body['node'] = next(n for n in NODES if n['id'] == 'N02')
    body['fixtureRework'] = False
    with TestClient(create_app(tmp_path, TOKEN), headers={'X-Creator-Token': TOKEN}) as client:
        assert client.post('/runs', json=body).status_code == 202
        run = wait(client, body['id'], {'WAITING_ACCEPTANCE', 'FAILED', 'UNKNOWN'})
        assert run['status'] == 'WAITING_ACCEPTANCE', run
        events = client.get('/runs/' + body['id'] + '/events').json()
        blocked = [(e['role'], e['data']['tool']) for e in events if e['kind'] == 'TOOL_BLOCKED']
        assert ('POSITIONING', 'submit_candidate') in blocked
        assert ('REVIEWER', 'submit_review') in blocked
        assert len([a for a in run['artifacts'] if a['kind'] == 'CANDIDATE']) == 1
        assert len([a for a in run['artifacts'] if a['kind'] == 'REVIEW']) == 1
