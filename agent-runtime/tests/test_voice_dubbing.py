import base64
import json
from types import SimpleNamespace
import wave

import pytest
from fastapi import HTTPException

from app import voice_console, voice_dubbing


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(voice_dubbing, 'STORAGE', tmp_path / 'dubs')
    monkeypatch.setattr(voice_dubbing.voice_database, 'enabled', lambda: False)
    roles = tmp_path / 'voices'
    for role_id in ('narrator', 'hero'):
        role = roles / role_id
        role.mkdir(parents=True)
        (role / 'manifest.json').write_text('{}', encoding='utf-8')
        (role / 'character.json').write_text(json.dumps({'version': '1.0.0', 'reference': '01-vocals.wav'}), encoding='utf-8')
        (role / '01-vocals.wav').write_bytes(b'reference')
    return roles


def sample():
    roles = [{'id': 'narrator', 'version': '1.0.0', 'selected': 1}, {'id': 'hero', 'version': '1.0.0', 'selected': 1}]
    data = {'projectId': 'project-1', 'cast': [{'speaker': '旁白', 'roleId': 'narrator', 'version': '1.0.0'},
                                              {'speaker': '小明', 'roleId': 'hero', 'version': '1.0.0'}],
            'lines': [{'speaker': '旁白', 'text': '天亮了。'}, {'speaker': '小明', 'text': '出发吧。'}]}
    return data, roles


def test_batch_validates_all_speakers_and_versions_before_generation(library):
    data, roles = sample()
    data['lines'][1]['speaker'] = '陌生人'
    with pytest.raises(HTTPException, match='尚未选角'):
        voice_dubbing.prepare(data, roles)
    data, roles = sample()
    data['cast'][0]['version'] = 'old'
    with pytest.raises(HTTPException, match='版本已变化'):
        voice_dubbing.prepare(data, roles)


def test_batch_saves_individual_and_combined_audio(library, monkeypatch):
    data, roles = sample()
    project, lines = voice_dubbing.prepare(data, roles)
    folder, record = voice_dubbing.create(project, lines)
    calls = []

    def synthesize(command, **kwargs):
        calls.append(command[3])
        with wave.open(command[-1], 'wb') as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000)
            wav.writeframes(b'\x01\x00' * 2400)
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(voice_dubbing.subprocess, 'run', synthesize)
    result = voice_dubbing.run(folder, record, 'python', library, lambda _: None)
    assert result['status'] == 'done' and result['completed'] == 2
    assert calls == ['narrator', 'hero']
    with wave.open(str(folder / 'combined.wav'), 'rb') as wav:
        assert wav.getnframes() == 2400 * 2 + round(24000 * .35)
    assert len(voice_dubbing.list_runs(project)) == 1
    assert base64.b64decode(voice_dubbing.get_audio(project, result['id'], '001.wav')['audioBase64']) == (folder / '001.wav').read_bytes()


def test_failed_segment_never_publishes_complete_track(library, monkeypatch):
    data, roles = sample()
    project, lines = voice_dubbing.prepare(data, roles)
    folder, record = voice_dubbing.create(project, lines)
    monkeypatch.setattr(voice_dubbing.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=1, stdout='', stderr='供应商失败'))
    result = voice_dubbing.run(folder, record, 'python', library, lambda _: None)
    assert result['status'] == 'failed' and not (folder / 'combined.wav').exists()
    with pytest.raises(HTTPException):
        voice_dubbing.get_audio(project, result['id'], 'combined.wav')


def test_auto_cast_reuses_binding_matches_narration_and_is_stable(library):
    roles = [{'id': 'narrator', 'name': '古诗旁白', 'version': '1.0.0', 'selected': 1},
             {'id': 'hero', 'name': '青年', 'version': '1.0.0', 'selected': 1},
             {'id': 'draft', 'name': '青年', 'version': None, 'selected': None}]
    lines = voice_dubbing.parse_script('旁白：天亮了。\n青年：出发吧。\n旁白：我们走。')
    cast = voice_dubbing.auto_cast(lines, roles)
    assert [(x['speaker'], x['roleId']) for x in cast] == [('旁白', 'narrator'), ('青年', 'hero')]
    assert voice_dubbing.auto_cast(lines, list(reversed(roles))) == cast
    fixed = [{'speaker': '旁白', 'roleId': 'hero', 'version': '1.0.0'}]
    assert voice_dubbing.auto_cast(lines, roles, fixed)[0]['roleId'] == 'hero'


def test_auto_cast_falls_back_without_manual_input_and_rejects_empty_library(library):
    roles = [{'id': 'one', 'name': '声音一', 'version': '1.0.0', 'selected': 1},
             {'id': 'two', 'name': '声音二', 'version': '1.0.0', 'selected': 1}]
    lines = voice_dubbing.parse_script({'segments': [{'speaker': '角色甲', 'text': '你好'}, {'speaker': '角色乙', 'text': '再见'}]})
    cast = voice_dubbing.auto_cast(lines, roles)
    assert len({item['roleId'] for item in cast}) == 2
    assert all(item['selectionReason'] == '稳定分配' for item in cast)
    assert voice_dubbing.auto_cast(lines, roles) == cast
    with pytest.raises(HTTPException, match='没有已定档'):
        voice_dubbing.auto_cast(lines, [])


def test_auto_start_accepts_script_without_cast_and_records_selection(library, monkeypatch):
    data, roles = sample()
    monkeypatch.setattr(voice_console.local_voice_config, 'load', lambda: None)
    monkeypatch.setattr(voice_console, 'roles', lambda: roles)
    monkeypatch.setenv('MIMO_API_KEY', 'test-key')
    monkeypatch.setattr(voice_console, 'JOBS', {})
    monkeypatch.setattr(voice_console.POOL, 'submit', lambda fn: None)
    job = voice_console.action({'action': 'dub_auto_start', 'projectId': data['projectId'],
                                'script': '旁白：天亮了。\n小明：出发吧。'})
    runs = voice_dubbing.list_runs(data['projectId'])
    assert runs[0]['id'] == job['id']
    assert [line['speaker'] for line in runs[0]['lines']] == ['旁白', '小明']
    assert len(runs[0]['cast']) == 2


def test_formal_workspace_rejects_local_dubbing_when_remote_not_configured(monkeypatch):
    monkeypatch.setenv('CREATOR_WORKSPACE_REMOTE_REQUIRED', 'true')
    monkeypatch.setattr(voice_console.local_voice_config, 'load', lambda: None)
    monkeypatch.setattr(voice_console.voice_database, 'enabled', lambda: False)
    with pytest.raises(HTTPException, match='远端数据库'):
        voice_console.action({'action': 'dub_list', 'projectId': 'project-1'})
