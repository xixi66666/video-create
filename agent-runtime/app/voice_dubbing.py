"""根据作品选角批量生成配音，保留每句音频和完整音轨。"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import uuid
import wave

from fastapi import HTTPException
from . import voice_database

ROOT = Path(__file__).resolve().parents[2]
STORAGE = ROOT / '.voice-data' / 'project-dubs'
ID = re.compile(r'^[a-zA-Z0-9_-]{1,90}$')


def parse_script(script):
    """读取结构化台词或带说话人前缀的文本；未标注的文本视为旁白。"""
    if isinstance(script, str):
        text = script.strip()
        if not text:
            raise HTTPException(400, '作品脚本为空')
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        if isinstance(parsed, (dict, list)):
            return parse_script(parsed)
        result = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            match = re.match(r'^([^：:]{1,100})[：:]\s*(.+)$', line)
            result.append({'speaker': match.group(1).strip() if match else '旁白',
                           'text': match.group(2).strip() if match else line})
        return result
    if isinstance(script, dict):
        if 'spokenScript' in script:
            return parse_script(script['spokenScript'])
        if 'segments' in script:
            return parse_script(script['segments'])
    if isinstance(script, list):
        if all(isinstance(item, dict) and isinstance(item.get('text'), str) and
               isinstance(item.get('speaker', '旁白'), str) for item in script):
            return [{'speaker': item.get('speaker', '旁白').strip() or '旁白', 'text': item['text'].strip()}
                    for item in script]
    raise HTTPException(400, '脚本格式无法识别，请提供文本、spokenScript 或带 speaker 和 text 的 segments')


def auto_cast(lines, roles, previous=None):
    """优先复用有效绑定，再匹配角色名称，最后稳定分配可用声音。"""
    available = {r['id']: r for r in roles if r.get('id') and r.get('selected') and r.get('version')}
    if not available:
        raise HTTPException(409, '声音库没有已定档的声音角色，无法自动配音')
    existing = {entry.get('speaker'): entry for entry in (previous or []) if isinstance(entry, dict)}
    used, result = set(), []
    speakers = list(dict.fromkeys(line.get('speaker', '').strip() for line in lines))
    for speaker in speakers:
        if not speaker:
            raise HTTPException(400, '脚本中存在空说话人')
        saved = existing.get(speaker, {})
        role = available.get(saved.get('roleId'))
        if role and saved.get('version') == role['version']:
            reason = '沿用已有选角'
        else:
            # 声库目前只有名称和参考音频，名称能匹配时优先使用，不能假称识别了音色属性。
            def rank(item):
                name = str(item.get('name') or '').strip()
                exact = bool(name and (speaker in name or name in speaker))
                narration = speaker == '旁白' and any(word in name for word in ('旁白', '朗诵', '叙述'))
                digest = hashlib.sha256((speaker + '\0' + item['id']).encode('utf-8')).hexdigest()
                return (exact or narration, item['id'] not in used, digest)
            role = max(available.values(), key=rank)
            name = str(role.get('name') or '')
            reason = '名称匹配' if speaker in name or (speaker == '旁白' and any(w in name for w in ('旁白', '朗诵', '叙述'))) else '稳定分配'
        used.add(role['id'])
        result.append({'speaker': speaker, 'roleId': role['id'], 'name': role.get('name', role['id']),
                       'version': role['version'], 'selectionReason': reason})
    return result


def project_path(project_id):
    if not isinstance(project_id, str) or not ID.fullmatch(project_id):
        raise HTTPException(400, '作品编号无效')
    return STORAGE / project_id


def prepare(data, roles):
    project_id = data.get('projectId')
    project_path(project_id)
    lines, cast = data.get('lines'), data.get('cast')
    if not isinstance(lines, list) or not 1 <= len(lines) <= 100 or not isinstance(cast, list):
        raise HTTPException(400, '台词须为 1–100 段，请先添加台词并为说话人选角')
    bindings = {}
    for item in cast:
        if not isinstance(item, dict) or not isinstance(item.get('speaker'), str) or not isinstance(item.get('roleId'), str):
            raise HTTPException(400, '选角信息无效')
        speaker = item['speaker'].strip()
        if not speaker or speaker in bindings:
            raise HTTPException(400, '说话人为空或重复')
        bindings[speaker] = item
    available = {r['id']: r for r in roles}
    result = []
    for index, line in enumerate(lines, 1):
        if not isinstance(line, dict) or not isinstance(line.get('speaker'), str) or not isinstance(line.get('text'), str):
            raise HTTPException(400, f'第 {index} 段台词格式无效')
        speaker, text = line['speaker'].strip(), line['text'].strip()
        if not text or len(text) > 1000 or not speaker:
            raise HTTPException(400, f'第 {index} 段说话人或台词无效')
        binding = bindings.get(speaker)
        if not binding:
            raise HTTPException(400, f'说话人「{speaker}」尚未选角')
        role = available.get(binding['roleId'])
        if not role or not role.get('selected') or not role.get('version'):
            raise HTTPException(400, f'说话人「{speaker}」绑定的声音不存在或未定档')
        if role['version'] != binding.get('version'):
            raise HTTPException(409, f'说话人「{speaker}」的声音版本已变化，请重新选角')
        result.append({'speaker': speaker, 'text': text, 'roleId': role['id'], 'version': role['version']})
    if sum(len(x['text']) for x in result) > 12000:
        raise HTTPException(400, '配音文本总长度不能超过 12000 字')
    return project_id, result


def paragraphs(text):
    # MiMo 每次不超过 40 个非空白字符，按标点优先拆分。
    parts = re.split(r'(?<=[。！？；.!?;])', text.replace('\n', ' '))
    chunks, current = [], ''
    for part in parts:
        while part:
            room = 40 - len(current)
            current += part[:room]
            part = part[room:]
            if len(current) == 40 or (current and not part and re.search(r'[。！？；.!?;]$', current)):
                chunks.append(current.strip())
                current = ''
    if current.strip():
        chunks.append(current.strip())
    return '\n\n'.join(x for x in chunks if x)


def write_manifest(folder, record):
    temp = folder / 'manifest.tmp'
    temp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, folder / 'manifest.json')
    if voice_database.enabled():
        # 清单与新增音轨在同一事务写入；远端不可用时绝不报告成功。
        with voice_database.connect() as db:
            with db.cursor() as cur:
                cur.execute('SELECT project_id FROM creator_dub_run WHERE id=%s FOR UPDATE', (record['id'],))
                prior = cur.fetchone()
                if prior and prior['project_id'] != record['projectId']:
                    raise ValueError('配音任务编号冲突')
                cur.execute('INSERT INTO creator_dub_run(id,project_id,manifest_json) VALUES(%s,%s,%s) '
                            'ON DUPLICATE KEY UPDATE manifest_json=VALUES(manifest_json)',
                            (record['id'], record['projectId'], json.dumps(record, ensure_ascii=False)))
                audio = [(line.get('audio'), line.get('sha256')) for line in record.get('lines', []) if line.get('audio')]
                if record.get('status') == 'done':
                    audio.append(('combined.wav', record.get('sha256')))
                for name, sha in audio:
                    if not re.fullmatch(r'(combined|\d{3})\.wav', name) or not sha:
                        raise ValueError('音轨清单无效')
                    cur.execute('SELECT sha256 FROM creator_dub_audio WHERE run_id=%s AND file_name=%s', (record['id'], name))
                    existing = cur.fetchone()
                    if existing:
                        if existing['sha256'] != sha:
                            raise ValueError('数据库音轨和清单不一致')
                        continue
                    raw = (folder / name).read_bytes()
                    if hashlib.sha256(raw).hexdigest() != sha:
                        raise ValueError('音轨校验失败')
                    cur.execute('INSERT INTO creator_dub_audio(run_id,file_name,sha256,content) VALUES(%s,%s,%s,%s)',
                                (record['id'], name, sha, raw))
            db.commit()


def create(project_id, lines):
    folder = project_path(project_id) / uuid.uuid4().hex
    folder.mkdir(parents=True)
    record = {'id': folder.name, 'projectId': project_id, 'status': 'queued', 'lines': lines,
              'message': '等待处理', 'completed': 0}
    write_manifest(folder, record)
    return folder, record


def run(folder, record, python, library, progress):
    record.update(status='running', message='正在生成配音')
    write_manifest(folder, record)
    try:
        with tempfile.TemporaryDirectory(dir=folder) as tmp:
            temp = Path(tmp)
            for role_id in dict.fromkeys(line['roleId'] for line in record['lines']):
                if voice_database.enabled():
                    role = voice_database.materialize(role_id, temp)
                else:
                    source = library / role_id
                    if not (source / 'character.json').is_file():
                        raise ValueError('角色参考音频不存在')
                    role = temp / role_id
                    role.mkdir()
                    for name in ('manifest.json', 'character.json'):
                        shutil.copy2(source / name, role / name)
                    selected = json.loads((role / 'character.json').read_text(encoding='utf-8'))
                    reference = selected.get('reference', '')
                    if not re.fullmatch(r'\d{2}-vocals\.wav', reference):
                        raise ValueError('角色参考音频无效')
                    shutil.copy2(source / reference, role / reference)
                # 同一任务使用固定快照，避免中途变更选角。
                card = json.loads((role / 'character.json').read_text(encoding='utf-8'))
                if any(x['version'] != card.get('version') for x in record['lines'] if x['roleId'] == role_id):
                    raise ValueError('声音角色版本已变化，请重新选角')
                for line in record['lines']:
                    if line['roleId'] == role_id:
                        line['referenceSha1'] = card.get('sha1')
                        line['candidate'] = card.get('candidate')
            record['model'] = os.getenv('CREATOR_MIMO_VOICECLONE_MODEL', 'mimo-v2.5-tts-voiceclone')
            write_manifest(folder, record)
            rate = None
            with wave.open(str(folder / 'combined.pending.wav'), 'wb') as combined:
                for index, line in enumerate(record['lines'], 1):
                    textfile = temp / 'text.txt'
                    textfile.write_text(paragraphs(line['text']), encoding='utf-8')
                    output = folder / f'{index:03}.wav'
                    env = dict(os.environ, VOICELIB_HOME=str(temp), PYTHONIOENCODING='utf-8')
                    for key in ('CREATOR_VOICE_DB_HOST', 'CREATOR_VOICE_DB_PORT', 'CREATOR_VOICE_DB_USER',
                                'CREATOR_VOICE_DB_PASSWORD', 'CREATOR_VOICE_DB_NAME', 'CREATOR_RUNTIME_TOKEN'):
                        env.pop(key, None)
                    result = subprocess.run([python, str(ROOT / 'voicelib' / 'voice.py'), 'speak', line['roleId'],
                                             '--text-file', str(textfile), '--out', str(output)],
                                            capture_output=True, text=True, encoding='utf-8', errors='replace',
                                            timeout=1800, env=env)
                    if result.returncode:
                        raise ValueError(f'第 {index} 段合成失败：' + (result.stderr or result.stdout).strip().splitlines()[-1][:200])
                    with wave.open(str(output), 'rb') as audio:
                        if audio.getnchannels() != 1 or audio.getsampwidth() != 2:
                            raise ValueError(f'第 {index} 段音频格式不兼容')
                        if rate is None:
                            rate = audio.getframerate()
                            combined.setnchannels(1); combined.setsampwidth(2); combined.setframerate(rate)
                        if rate != audio.getframerate():
                            raise ValueError('各段音频采样率不一致')
                        if index > 1:
                            combined.writeframes(b'\0\0' * round(rate * .35))
                        combined.writeframes(audio.readframes(audio.getnframes()))
                    line['audio'] = output.name
                    line['sha256'] = hashlib.sha256(output.read_bytes()).hexdigest()
                    record['completed'] = index
                    record['message'] = f'已完成 {index}/{len(record["lines"])} 段'
                    write_manifest(folder, record); progress(record['message'])
        (folder / 'combined.pending.wav').replace(folder / 'combined.wav')
        record.update(status='done', message='配音已生成', audio='combined.wav',
                      sha256=hashlib.sha256((folder / 'combined.wav').read_bytes()).hexdigest())
    except Exception as exc:
        record.update(status='failed', message=str(exc)[:350])
    write_manifest(folder, record)
    return record


def list_runs(project_id):
    path = project_path(project_id)
    if voice_database.enabled():
        with voice_database.connect() as db:
            with db.cursor() as cur:
                cur.execute('SELECT manifest_json FROM creator_dub_run WHERE project_id=%s ORDER BY updated_at DESC,id DESC', (project_id,))
                rows = cur.fetchall()
        return [json.loads(row['manifest_json']) for row in rows]
    if not path.exists():
        return []
    records = []
    for file in sorted(path.glob('*/manifest.json'), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            record = json.loads(file.read_text(encoding='utf-8'))
            if record.get('projectId') == project_id and record.get('id') == file.parent.name:
                if record.get('status') in ('queued', 'running'):
                    record['message'] = '任务执行中，服务重启后需重新生成'
                records.append(record)
        except (OSError, ValueError):
            continue
    return records


def get_audio(project_id, run_id, name):
    if not isinstance(run_id, str) or not re.fullmatch(r'[a-f0-9]{32}', run_id):
        raise HTTPException(400, '配音任务编号无效')
    if not isinstance(name, str) or not re.fullmatch(r'(combined|\d{3})\.wav', name):
        raise HTTPException(400, '音轨名称无效')
    folder = project_path(project_id) / run_id
    if voice_database.enabled():
        with voice_database.connect() as db:
            with db.cursor() as cur:
                cur.execute('SELECT r.manifest_json,a.sha256,a.content FROM creator_dub_run r '
                            'JOIN creator_dub_audio a ON a.run_id=r.id '
                            'WHERE r.project_id=%s AND r.id=%s AND a.file_name=%s', (project_id, run_id, name))
                row = cur.fetchone()
        if not row:
            raise HTTPException(404, '音轨不存在')
        record = json.loads(row['manifest_json'])
        expected = record.get('sha256') if name == 'combined.wav' and record.get('status') == 'done' else next(
            (line.get('sha256') for line in record.get('lines', []) if line.get('audio') == name), None)
        data = bytes(row['content'])
        if len(data) > 12 * 1024 * 1024:
            raise HTTPException(413, '音轨过大，暂不支持在线播放')
        if not expected or expected != row['sha256'] or hashlib.sha256(data).hexdigest() != expected:
            raise HTTPException(409, '音轨校验失败，请重新生成')
        return {'audioBase64': base64.b64encode(data).decode('ascii')}
    try:
        record = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
        allowed = {line.get('audio') for line in record.get('lines', [])}
        if record.get('status') == 'done': allowed.add('combined.wav')
        if name not in allowed: raise HTTPException(404, '音轨尚未生成')
        path = folder / name
        if path.stat().st_size > 12 * 1024 * 1024: raise HTTPException(413, '音轨过大，暂不支持在线播放')
        data = path.read_bytes()
        expected = record.get('sha256') if name == 'combined.wav' else next(
            (line.get('sha256') for line in record.get('lines', []) if line.get('audio') == name), None)
        if not expected or hashlib.sha256(data).hexdigest() != expected:
            raise HTTPException(409, '音轨校验失败，请重新生成')
        return {'audioBase64': base64.b64encode(data).decode('ascii')}
    except (OSError, ValueError):
        raise HTTPException(404, '音轨不存在') from None
