"""本机声音角色库与异步采集任务。"""
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException
from . import local_voice_config, voice_database, voice_dubbing

ROOT = Path(__file__).resolve().parents[2]
LIBRARY = Path(os.getenv("VOICELIB_HOME") or ROOT / ".voice-data").expanduser().resolve()
JOBS = {}
LOCK = threading.Lock()
POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="voice-console")
ROLE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,31}$")


def role_path(role_id):
    if not isinstance(role_id, str) or not ROLE_PATTERN.fullmatch(role_id):
        raise HTTPException(400, "角色 ID 须为 3–32 位小写字母、数字或下划线")
    path = LIBRARY / role_id
    if path.resolve().parent != LIBRARY:
        raise HTTPException(400, "角色路径无效")
    return path


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HTTPException(404, "角色数据不存在或无法读取") from None


def roles():
    if voice_database.enabled():
        return voice_database.list_roles()
    if not LIBRARY.exists():
        return []
    items = []
    for path in sorted(LIBRARY.iterdir()):
        if not path.is_dir() or not ROLE_PATTERN.fullmatch(path.name):
            continue
        try:
            manifest = read_json(path / "manifest.json")
            if manifest.get("character_id") != path.name:
                continue
            card = read_json(path / "character.json") if (path / "character.json").is_file() else None
            items.append({"id": path.name, "name": card.get("name", path.name) if card else manifest.get("name", path.name),
                          "version": card.get("version") if card else None, "selected": card.get("candidate") if card else None,
                          "clips": manifest.get("clips", []),
                          "samples": [{"file": p.name} for p in sorted((path / "samples").glob("*.wav")) if p.is_file()] if (path / "samples").is_dir() else []})
        except HTTPException:
            continue
    return items


def audio(role_id, kind, name):
    role = role_path(role_id)
    if voice_database.enabled():
        with voice_database.connect() as db:
            row = voice_database.get_record(db, role_id)
            manifest = voice_database.parse_manifest(row)
            if kind == "sample":
                if not isinstance(name, str) or Path(name).name != name or not name.lower().endswith(".wav"):
                    raise HTTPException(400, "音频名称无效")
                filename = name
            else:
                if kind not in {"original", "vocals"} or not isinstance(name, int) or not 1 <= name <= len(manifest.get("clips", [])):
                    raise HTTPException(400, "候选编号无效")
                filename = f"{name:02}-{kind}.wav"
                if manifest["clips"][name - 1].get(kind) != filename:
                    raise HTTPException(400, "候选文件记录无效")
            content = voice_database.get_audio(db, role_id, filename)
        return {"audioBase64": base64.b64encode(content).decode("ascii")}
    manifest = read_json(role / "manifest.json")
    if kind == "sample":
        if not isinstance(name, str) or Path(name).name != name or not name.lower().endswith(".wav"):
            raise HTTPException(400, "音频名称无效")
        path = role / "samples" / name
    else:
        if kind not in {"original", "vocals"} or not isinstance(name, int) or not 1 <= name <= len(manifest.get("clips", [])):
            raise HTTPException(400, "候选编号无效")
        filename = manifest["clips"][name - 1].get(kind)
        if filename != f"{name:02}-{kind}.wav":
            raise HTTPException(400, "候选文件记录无效")
        path = role / filename
    if not path.is_file() or not path.resolve().is_relative_to(role.resolve()):
        raise HTTPException(404, "音频文件不存在")
    if path.stat().st_size > 12 * 1024 * 1024:
        raise HTTPException(413, "音频过大，请使用本地文件播放")
    return {"audioBase64": base64.b64encode(path.read_bytes()).decode("ascii")}


def python_command():
    configured = os.getenv("VOICELIB_PYTHON")
    if configured:
        return configured
    python = ROOT / ".venv-voice" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return str(python) if python.is_file() else sys.executable


def start_job(role_id, args, upload=None):
    role_path(role_id)
    with LOCK:
        if any(j["status"] in ("queued", "running") for j in JOBS.values()):
            raise HTTPException(409, "已有配音任务正在处理，请等待完成")
        job_id = uuid.uuid4().hex
        JOBS[job_id] = {"id": job_id, "role": role_id, "status": "queued", "message": "等待处理"}

    def run():
        JOBS[job_id].update(status="running", message="正在处理，请稍候")
        try:
            remote = voice_database.enabled()
            if remote and args[0] == "select":
                voice_database.select(role_id, int(args[2]), args[4])
                JOBS[job_id].update(status="done", message="处理完成")
                return
            LIBRARY.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=LIBRARY) as tmp:
                temporary_library = Path(tmp) / "library"
                temporary_library.mkdir()
                cmd = [python_command(), str(ROOT / "voicelib" / "voice.py"), *args]
                if remote and args[0] == "speak":
                    role = voice_database.materialize(role_id, temporary_library)
                    output = role / "samples" / (uuid.uuid4().hex + ".wav")
                    cmd[cmd.index("--out") + 1] = str(output)
                if upload is not None:
                    source = Path(tmp) / "upload.media"
                    source.write_bytes(upload)
                    cmd = [str(source) if arg == "__UPLOAD__" else arg for arg in cmd]
                env = dict(os.environ, VOICELIB_HOME=str(temporary_library if remote else LIBRARY), PYTHONIOENCODING="utf-8")
                for key in ("CREATOR_VOICE_DB_HOST", "CREATOR_VOICE_DB_PORT", "CREATOR_VOICE_DB_USER",
                            "CREATOR_VOICE_DB_PASSWORD", "CREATOR_VOICE_DB_NAME", "CREATOR_RUNTIME_TOKEN"):
                    env.pop(key, None)
                if args[0] != "speak":
                    env.pop("MIMO_API_KEY", None)
                result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                        errors="replace", timeout=7200, env=env)
                if result.returncode:
                    message = (result.stderr or result.stdout).strip().splitlines()
                    raise ValueError(message[-1][:350] if message else "任务失败，请检查本机配音环境")
                if remote and args[0] == "extract":
                    voice_database.import_role(temporary_library / role_id)
                if remote and args[0] == "speak":
                    voice_database.save_sample(role_id, output.name, output.read_bytes())
            JOBS[job_id].update(status="done", message="处理完成")
        except Exception as exc:
            JOBS[job_id].update(status="failed", message=str(exc)[:350])

    POOL.submit(run)
    return JOBS[job_id]


def action(data):
    local_voice_config.load()
    action_name = data.get("action")
    role_id = data.get("role", "")
    if action_name == "list":
        return {"roles": roles(), "mimoConfigured": bool(os.getenv("MIMO_API_KEY")),
                "storage": "mysql" if voice_database.enabled() else "local"}
    if action_name == "job":
        job = JOBS.get(data.get("id"))
        if not job:
            raise HTTPException(404, "任务不存在，服务可能已重启")
        return dict(job)
    if action_name == "dub_list":
        runs = voice_dubbing.list_runs(data.get("projectId"))
        for record in runs:
            if record["status"] in ("queued", "running") and record["id"] not in JOBS:
                record.update(status="interrupted", message="服务已重启，任务中断；请检查已完成的段落后重新生成")
        return {"runs": runs}
    if action_name == "dub_audio":
        return voice_dubbing.get_audio(data.get("projectId"), data.get("id"), data.get("name"))
    if action_name in {"dub_start", "dub_auto_start"}:
        if not os.getenv("MIMO_API_KEY"):
            raise HTTPException(503, "未配置 MiMo 凭据")
        available = roles()
        if action_name == "dub_auto_start":
            parsed = data.get("lines") if data.get("lines") is not None else voice_dubbing.parse_script(data.get("script"))
            if not isinstance(parsed, list) or any(not isinstance(line, dict) or not isinstance(line.get('speaker'), str) or not isinstance(line.get('text'), str) for line in parsed):
                raise HTTPException(400, "自动配音台词格式无效")
            previous = next((r.get("cast", []) for r in voice_dubbing.list_runs(data.get("projectId"))
                             if r.get("status") == "done" and r.get("cast")), [])
            existing = {entry.get("speaker"): entry for entry in previous if isinstance(entry, dict)}
            supplied = data.get("cast", [])
            if not isinstance(supplied, list):
                raise HTTPException(400, "已有选角格式无效")
            existing.update({entry.get("speaker"): entry for entry in supplied if isinstance(entry, dict)})
            cast = voice_dubbing.auto_cast(parsed, available, list(existing.values()))
            data = {**data, "lines": parsed, "cast": cast}
        project_id, lines = voice_dubbing.prepare(data, available)
        with LOCK:
            if any(j["status"] in ("queued", "running") for j in JOBS.values()):
                raise HTTPException(409, "已有配音任务正在处理，请等待完成")
            folder, record = voice_dubbing.create(project_id, lines)
            if action_name == "dub_auto_start":
                record['cast'] = cast
                voice_dubbing.write_manifest(folder, record)
            job_id = record["id"]
            JOBS[job_id] = {"id": job_id, "role": "", "status": "queued", "message": "等待处理"}

        def dub_run():
            JOBS[job_id].update(status="running", message="正在生成配音")
            result = voice_dubbing.run(folder, record, python_command(), LIBRARY,
                                       lambda message: JOBS[job_id].update(message=message))
            JOBS[job_id].update(status=result["status"], message=result["message"])

        POOL.submit(dub_run)
        return dict(JOBS[job_id])
    if action_name == "audio":
        return audio(role_id, data.get("kind"), data.get("name"))
    if action_name == "rename":
        name = data.get("name")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
            raise HTTPException(400, "角色名称须为 1–100 个字符")
        role = role_path(role_id)
        with LOCK:
            if any(j["role"] == role_id and j["status"] in ("queued", "running") for j in JOBS.values()):
                raise HTTPException(409, "该角色正在处理任务，请稍后修改名称")
            if voice_database.enabled():
                return voice_database.rename(role_id, name.strip())
            manifest = read_json(role / "manifest.json")
            if manifest.get("character_id") != role_id:
                raise HTTPException(400, "角色数据不匹配")
            card_path = role / "character.json"
            target = card_path if card_path.is_file() else role / "manifest.json"
            record = read_json(target)
            if record.get("character_id") != role_id:
                raise HTTPException(400, "角色数据不匹配")
            record["name"] = name.strip()
            temp_path = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=role, delete=False) as temp:
                    temp_path = Path(temp.name)
                    json.dump(record, temp, ensure_ascii=False, indent=2)
                os.replace(temp_path, target)
            finally:
                if temp_path is not None:
                    temp_path.unlink(missing_ok=True)
        return {"id": role_id, "name": record["name"]}
    if action_name == "extract":
        role = role_path(role_id)
        existing = any(v["id"] == role_id for v in roles()) if voice_database.enabled() else role.exists()
        if existing:
            raise HTTPException(409, "角色 ID 已存在，请更换")
        source = data.get("source", "")
        upload = None
        encoded = data.get("fileBase64")
        if encoded:
            try:
                upload = base64.b64decode(encoded, validate=True)
            except (ValueError, TypeError):
                raise HTTPException(400, "上传文件格式无效") from None
            if not upload or len(upload) > 20 * 1024 * 1024:
                raise HTTPException(413, "上传文件须小于 20 MB")
            source = "__UPLOAD__"
        elif not isinstance(source, str) or len(source) > 2048 or urlsplit(source).scheme not in {"http", "https"} or not urlsplit(source).hostname:
            raise HTTPException(400, "请输入有效的音视频链接或上传文件")
        args = ["extract", role_id, source]
        for key, flag in (("start", "--start"), ("seconds", "--seconds")):
            if data.get(key) is not None:
                try:
                    value = float(data[key])
                except (ValueError, TypeError):
                    raise HTTPException(400, "时间范围无效") from None
                args += [flag, str(value)]
        if data.get("clean"):
            args.append("--clean")
        return start_job(role_id, args, upload)
    if action_name == "select":
        number, name = data.get("number"), data.get("name")
        if not isinstance(number, int) or not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise HTTPException(400, "请填写角色名称并选择候选")
        return start_job(role_id, ["select", role_id, str(number), "--name", name.strip()])
    if action_name == "speak":
        text = data.get("text", "")
        if not isinstance(text, str) or not text.strip() or len(text) > 3000:
            raise HTTPException(400, "请输入不超过 3000 字的台词")
        if not os.getenv("MIMO_API_KEY"):
            raise HTTPException(503, "未配置 MIMO_API_KEY，请配置后重启本机服务")
        role = role_path(role_id)
        if voice_database.enabled():
            with voice_database.connect() as db:
                if not voice_database.get_record(db, role_id)["selected_candidate"]:
                    raise HTTPException(400, "请先选定角色参考音频")
            output = Path("placeholder.wav")
        else:
            if not (role / "character.json").is_file():
                raise HTTPException(400, "请先选定角色参考音频")
            samples = role / "samples"
            samples.mkdir(exist_ok=True)
            output = samples / (uuid.uuid4().hex + ".wav")
        style = data.get("style", "")
        if not isinstance(style, str) or len(style) > 500:
            raise HTTPException(400, "语气要求不能超过 500 字")
        return start_job(role_id, ["speak", role_id, "--text", text, "--style", style, "--out", str(output)])
    raise HTTPException(400, "不支持的操作")
