"""voicelib 本地操作台(零依赖:标准库 + pyyaml + jsonschema)

启动:
    python voicelib/console/server.py
    浏览器打开 http://127.0.0.1:8767

设计原则:
  - 只监听 127.0.0.1,单人使用,无鉴权
  - 保存时自动同步 registry.json 与 catalog.md(消灭手工双写)
  - 不删除历史:删除仅限 draft 且无参考音频的角色
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import threading
import traceback
import uuid
import wave
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("缺少 pyyaml:pip install pyyaml")

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None

ROOT = Path(__file__).resolve().parent.parent
CHAR_DIR = ROOT / "characters"
SCHEMA_DIR = ROOT / "schema"
STATIC_DIR = Path(__file__).resolve().parent / "static"
REGISTRY = ROOT / "registry.json"
CATALOG = ROOT / "catalog.md"
RULES = ROOT / "rules.yaml"
WORK_ROOT = ROOT / ".work"

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
import harvest  # noqa: E402
import synth as tts_adapter  # noqa: E402

REF_KINDS = ("calm", "intense", "whisper")
STATUS_ICON = {"draft": "🟡", "active": "🟢", "retired": "⚪"}
STATUS_CN = {"draft": "draft", "active": "active", "retired": "retired"}


# ────────────────────────────── 文件读写 ──────────────────────────────
def read_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def write_yaml(path: Path, data: dict, header: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False, width=100)
    text = (header + "\n" if header else "") + body
    path.write_text(text, encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ────────────────────────────── 音频探测 ──────────────────────────────
def wav_info(path: Path) -> dict | None:
    """只解析 WAV 头,不需要 ffmpeg。"""
    try:
        with wave.open(str(path), "rb") as w:
            frames, rate = w.getnframes(), w.getframerate()
            return {
                "duration": round(frames / rate, 2) if rate else 0,
                "sample_rate": rate,
                "channels": w.getnchannels(),
                "bit_depth": w.getsampwidth() * 8,
                "bytes": path.stat().st_size,
            }
    except Exception:
        return None


def ref_status(char_dir: Path) -> dict:
    out = {}
    for kind in REF_KINDS:
        p = char_dir / "refs" / f"{kind}.wav"
        if not p.is_file():
            p = char_dir / "refs" / f"{kind}.flac"
        if not p.is_file():
            out[kind] = {"present": False, "ok": False, "reason": "缺失"}
            continue
        info = wav_info(p) if p.suffix == ".wav" else None
        if not info:
            out[kind] = {"present": True, "ok": False, "reason": "非 WAV,无法解析"}
            continue
        dur, sr = info["duration"], info["sample_rate"]
        problems = []
        if not (10 <= dur <= 15):
            problems.append(f"时长 {dur}s,要求 10–14s(硬上限 15s)")
        if sr < 44100:
            problems.append(f"采样率 {sr}Hz,要求 ≥44100")
        if info["channels"] > 1:
            problems.append(f"{info['channels']} 声道,要求单声道")
        out[kind] = {
            "present": True,
            "ok": not problems,
            "reason": ";".join(problems) or "合规",
            **info,
        }
    return out


# ────────────────────────────── 校验 ──────────────────────────────
def validate_doc(data: dict, schema_name: str) -> list[str]:
    if jsonschema is None:
        return ["jsonschema 未安装,跳过结构校验"]
    schema = json.loads((SCHEMA_DIR / schema_name).read_text(encoding="utf-8"))
    errors = []
    for err in sorted(jsonschema.Draft7Validator(schema).iter_errors(data), key=lambda e: list(e.path)):
        loc = ".".join(str(x) for x in err.path) or "(根)"
        errors.append(f"{loc}: {err.message}")
    return errors


def validate_character(char_dir: Path) -> dict:
    card_path = char_dir / "voice_card.yaml"
    presets_path = char_dir / "presets.yaml"
    result = {"card": [], "presets": [], "rules": []}

    if not card_path.is_file():
        result["card"].append("voice_card.yaml 不存在")
    else:
        result["card"] = validate_doc(read_yaml(card_path), "voice_card.schema.json")

    if not presets_path.is_file():
        result["presets"].append("presets.yaml 不存在")
    else:
        result["presets"] = validate_doc(read_yaml(presets_path), "presets.schema.json")

    # 规则层(对应 rules.yaml,这里只做能在本机判定的部分)
    card = read_yaml(card_path)
    presets = (read_yaml(presets_path) or {}).get("presets") or {}
    refs = ref_status(char_dir)

    if not any(r["ok"] for r in refs.values()):
        result["rules"].append("L2-06 没有合规的参考音频(10–14s,≥44.1k,单声道)")
    if card.get("status") == "active" and not all(r["ok"] for r in refs.values()):
        result["rules"].append("active 状态要求三条参考音频全部合规")

    emo_bad = [
        f"{k} 和={round(sum(v.get('emo', {}).values()), 2)}"
        for k, v in presets.items()
        if isinstance(v, dict) and sum(v.get("emo", {}).values()) > 0.8
    ]
    if emo_bad:
        result["rules"].append("L2-02 情绪权重和超 0.8:" + ", ".join(emo_bad))

    pauses = {round(v.get("pause_after", -1), 3) for v in presets.values() if isinstance(v, dict)}
    if len(presets) >= 2 and len(pauses) == 1:
        result["rules"].append("L2-04 所有预设 pause_after 相同,停顿会机械")

    if not (ROOT / str(card.get("source", {}).get("license_ref", "x"))).is_file():
        result["rules"].append("E2002 授权文件不存在:" + str(card.get("source", {}).get("license_ref")))

    valid_until = str(card.get("source", {}).get("valid_until") or "")
    if valid_until and valid_until < date.today().isoformat():
        result["rules"].append(f"E2002 授权已过期:{valid_until}")

    return result


# ────────────────────────────── 索引同步 ──────────────────────────────
def scan_characters() -> list[dict]:
    out = []
    if not CHAR_DIR.is_dir():
        return out
    for d in sorted(CHAR_DIR.iterdir()):
        if not d.is_dir():
            continue
        card = read_yaml(d / "voice_card.yaml")
        if not card.get("character_id"):
            continue
        refs = ref_status(d)
        out.append(
            {
                "character_id": card.get("character_id", d.name),
                "display_name": card.get("display_name", ""),
                "version": str(card.get("version", "")),
                "status": card.get("status", "draft"),
                "gender": card.get("profile", {}).get("gender", ""),
                "age_range": card.get("profile", {}).get("age_range", ""),
                "timbre_tags": card.get("profile", {}).get("timbre_tags", []) or [],
                "archetype": card.get("profile", {}).get("archetype", ""),
                "refs_ok": sum(1 for r in refs.values() if r["ok"]),
                "path": f"characters/{d.name}",
                "voice_card": f"characters/{d.name}/voice_card.yaml",
                "presets": f"characters/{d.name}/presets.yaml",
                "preset_keys": list((read_yaml(d / "presets.yaml").get("presets") or {}).keys()),
                "refs_complete": all(r["ok"] for r in refs.values()),
                "providers": list((card.get("providers") or {}).keys()),
                "fallback_order": card.get("fallback_order") or [],
                "license_ref": card.get("source", {}).get("license_ref", ""),
                "license_valid_until": str(card.get("source", {}).get("valid_until", "")),
                "checksum": None,
            }
        )
    return out


def sync_registry(entries: list[dict]) -> None:
    old = read_json(REGISTRY) if REGISTRY.is_file() else {}
    data = {
        "schema_version": old.get("schema_version", "1.0"),
        "library_version": old.get("library_version", "0.2.0"),
        "spec": old.get("spec", "SPEC.md"),
        "generated_at": date.today().isoformat(),
        "note": old.get("note", "本文件为索引,由 voicelib/console 生成。未在此登记的角色视为不存在。"),
        "characters": entries,
        "shared": old.get("shared", {}),
        "schemas": old.get("schemas", {}),
    }
    write_json(REGISTRY, data)


def catalog_row(e: dict) -> str:
    tags = "、".join(e["timbre_tags"]) or "—"
    presets = " / ".join(e["preset_keys"]) or "—"
    icon = STATUS_ICON.get(e["status"], "🟡")
    return (
        f"| `{e['character_id']}` | {e['display_name']} | {_cn_gender(e['gender'])} / {e['age_range']} "
        f"| {tags} | {e['archetype'] or '—'} | {presets} | {icon} {e['status']} | {e['version']} |"
    )


def _cn_gender(g: str) -> str:
    return {"male": "男", "female": "女", "neutral": "中性"}.get(g, g or "—")


def sync_catalog(entries: list[dict]) -> None:
    """只重写表格数据行,保留周围说明文字。"""
    if not CATALOG.is_file():
        return
    lines = CATALOG.read_text(encoding="utf-8").splitlines()
    try:
        head = next(i for i, ln in enumerate(lines) if ln.strip().startswith("| character_id |"))
    except StopIteration:
        return
    sep = head + 1
    end = sep + 1
    while end < len(lines) and lines[end].startswith("|"):
        end += 1
    new_rows = [catalog_row(e) for e in entries]
    lines[head + 1 : end] = [lines[sep]] + new_rows
    CATALOG.write_text("\n".join(lines) + "\n", encoding="utf-8")


def sync_all() -> list[dict]:
    entries = scan_characters()
    sync_registry(entries)
    sync_catalog(entries)
    return entries


# ────────────────────────────── 采集任务 ──────────────────────────────
JOBS: dict[str, dict] = {}
JOB_LOCK = threading.Lock()


def job_patch(jid: str, **kw) -> None:
    with JOB_LOCK:
        JOBS.setdefault(jid, {}).update(kw)


def job_log(jid: str, msg: str) -> None:
    with JOB_LOCK:
        job = JOBS.setdefault(jid, {"log": []})
        job.setdefault("log", []).append(str(msg)[:300])
        if len(job["log"]) > 500:
            del job["log"][:-500]


def harvest_worker(jid: str, src: str, cookies: str, separate: bool) -> None:
    job_patch(jid, state="running")
    try:
        work = WORK_ROOT / jid
        res = harvest.harvest(src, work, lambda m: job_log(jid, m), cookies=cookies, separate=separate)
        job_patch(jid, state="done", result=res)
    except Exception as exc:
        job_log(jid, "✗ " + str(exc))
        job_patch(jid, state="error", error=str(exc))


# ────────────────────────────── HTTP ──────────────────────────────
class Handler(BaseHTTPRequestHandler):
    server_version = "voicelib-console/1.0"

    def log_message(self, fmt, *args):  # 安静运行
        pass

    # ---- helpers ----
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code: int = 200) -> None:
        self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _err(self, msg: str, code: int = 400) -> None:
        self._json({"ok": False, "error": msg}, code)

    def _body_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    # ---- routing ----
    def do_GET(self):
        try:
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            path = url.path
            if path in ("/", "/index.html"):
                return self._file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            if path.startswith("/static/"):
                return self._file(STATIC_DIR / path[len("/static/") :], None)
            if path == "/api/state":
                entries = scan_characters()
                return self._json({"ok": True, "characters": entries, "count": len(entries)})
            if path == "/api/character":
                cid = q.get("id", "")
                d = CHAR_DIR / cid
                if not re.fullmatch(r"[a-z][a-z0-9_]{2,31}", cid) or not d.is_dir():
                    return self._err("角色不存在", 404)
                return self._json(
                    {
                        "ok": True,
                        "card": read_yaml(d / "voice_card.yaml"),
                        "presets": read_yaml(d / "presets.yaml"),
                        "refs": ref_status(d),
                        "validation": validate_character(d),
                    }
                )
            if path == "/api/rules":
                doc = read_yaml(RULES)
                return self._json({"ok": True, "version": doc.get("version"), "rules": doc.get("rules", [])})
            if path == "/api/env":
                return self._json({"ok": True, "deps": harvest.deps()})
            if path == "/api/job":
                jid = q.get("id", "")
                with JOB_LOCK:
                    job = JOBS.get(jid)
                    job = json.loads(json.dumps(job)) if job else None
                if not job:
                    return self._err("任务不存在", 404)
                return self._json({"ok": True, "job": job})
            if path == "/api/clip":
                jid, i = q.get("id", ""), int(q.get("i", "0"))
                with JOB_LOCK:
                    job = JOBS.get(jid)
                if not job or job.get("state") != "done":
                    return self._err("任务不可用", 404)
                cands = job["result"]["candidates"]
                if not (0 <= i < len(cands)):
                    return self._err("候选不存在", 404)
                p = WORK_ROOT / jid / cands[i]["file"]
                if not p.is_file():
                    return self._err("片段已清理", 404)
                return self._send(200, p.read_bytes(), "audio/wav")
            if path == "/api/synth/providers":
                return self._json({"ok": True, "providers": tts_adapter.provider_status()})
            if path == "/api/synth/audio":
                name = q.get("f", "")
                p = WORK_ROOT / "synth" / name
                if not re.fullmatch(r"[a-f0-9]{32}\.wav", name) or not p.is_file():
                    return self._err("音频不存在", 404)
                return self._send(200, p.read_bytes(), "audio/wav")
            if path == "/api/check":
                entries = scan_characters()
                report = {e["character_id"]: validate_character(CHAR_DIR / e["character_id"]) for e in entries}
                return self._json({"ok": True, "report": report, "count": len(entries)})
            return self._err("未知路径", 404)
        except Exception:
            traceback.print_exc()
            return self._err("服务器内部错误", 500)

    def do_POST(self):
        try:
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            path = url.path

            if path == "/api/character":
                return self._save_character(self._body_json())

            if path == "/api/upload":
                cid, kind = q.get("id", ""), q.get("kind", "")
                if kind not in REF_KINDS:
                    return self._err("kind 必须是 calm/intense/whisper")
                d = CHAR_DIR / cid
                if not d.is_dir():
                    return self._err("角色不存在", 404)
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                if len(raw) < 44 or raw[:4] != b"RIFF":
                    return self._err("只接受 WAV 文件(必须是无损干声)")
                refs = d / "refs"
                refs.mkdir(parents=True, exist_ok=True)
                (refs / f"{kind}.wav").write_bytes(raw)
                sync_all()
                return self._json({"ok": True, "refs": ref_status(d)})

            if path == "/api/harvest":
                body = self._body_json()
                src = str(body.get("url") or "").strip()
                if len(src) < 3:
                    return self._err("请填视频链接或本地文件路径")
                jid = uuid.uuid4().hex[:12]
                with JOB_LOCK:
                    JOBS[jid] = {"id": jid, "state": "queued", "log": [], "src": src,
                                 "separate": bool(body.get("separate", True))}
                threading.Thread(
                    target=harvest_worker,
                    args=(jid, src, str(body.get("cookies") or ""), bool(body.get("separate", True))),
                    daemon=True,
                ).start()
                return self._json({"ok": True, "job": jid})

            if path == "/api/commit":
                return self._commit(self._body_json())

            if path == "/api/synth":
                return self._synth(self._body_json())

            if path == "/api/delete":
                return self._delete(q.get("id", ""))

            if path == "/api/sync":
                entries = sync_all()
                return self._json({"ok": True, "count": len(entries)})

            return self._err("未知路径", 404)
        except Exception:
            traceback.print_exc()
            return self._err("服务器内部错误", 500)

    # ---- 具体动作 ----
    def _file(self, p: Path, ctype: str | None):
        if not p.is_file():
            return self._err("文件不存在", 404)
        if ctype is None:
            ctype = {
                ".css": "text/css; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".html": "text/html; charset=utf-8",
                ".svg": "image/svg+xml",
            }.get(p.suffix, "application/octet-stream")
        self._send(200, p.read_bytes(), ctype)

    def _save_character(self, payload: dict):
        card = payload.get("card") or {}
        presets_doc = payload.get("presets") or {}
        cid = str(card.get("character_id") or "").strip()
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,31}", cid):
            return self._err("character_id 必须匹配 ^[a-z][a-z0-9_]{2,31}$")

        d = CHAR_DIR / cid
        is_new = not d.is_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / "refs").mkdir(exist_ok=True)
        (d / "bench").mkdir(exist_ok=True)

        stamp = date.today().isoformat()
        write_yaml(
            d / "voice_card.yaml",
            card,
            header=f"# 由操作台生成于 {stamp}。手工编辑请保持结构;schema 见 schema/voice_card.schema.json",
        )
        presets_doc["character_id"] = cid
        write_yaml(
            d / "presets.yaml",
            presets_doc,
            header=f"# 由操作台生成于 {stamp}。emo 各键之和须 ≤0.8(L2-02)",
        )

        entries = sync_all()
        validation = validate_character(d)
        return self._json(
            {
                "ok": True,
                "created": is_new,
                "character_id": cid,
                "validation": validation,
                "characters": entries,
            }
        )

    def _synth(self, body: dict):
        cid = str(body.get("character_id") or "")
        text = str(body.get("text") or "").strip()
        if not text:
            return self._err("先填要念的台词")
        if len(text) > 200:
            return self._err("单句 ≤200 字;长句请先切分(L1-02)")
        d = CHAR_DIR / cid
        if not d.is_dir():
            return self._err("角色不存在", 404)

        card = read_yaml(d / "voice_card.yaml")
        presets = (read_yaml(d / "presets.yaml") or {}).get("presets") or {}
        key = str(body.get("preset") or "calm")
        preset = presets.get(key) or {}
        rate = float(preset.get("rate") or (card.get("voice") or {}).get("rate_baseline") or 1.0)
        ref = d / "refs" / "calm.wav"

        out = WORK_ROOT / "synth" / (uuid.uuid4().hex + ".wav")
        try:
            meta = tts_adapter.synthesize(
                text, out, provider=body.get("provider"), rate=rate, ref=ref if ref.is_file() else None
            )
        except Exception as exc:
            return self._err(str(exc), 502)
        return self._json({"ok": True, **meta, "file": out.name, "url": f"/api/synth/audio?f={out.name}"})

    def _delete(self, cid: str):
        d = CHAR_DIR / cid
        if not d.is_dir():
            return self._err("角色不存在", 404)
        card = read_yaml(d / "voice_card.yaml")
        refs = ref_status(d)
        if card.get("status") != "draft":
            return self._err("只能删除 draft 状态的角色;已发布的请改 retired")
        if any(r["present"] for r in refs.values()):
            return self._err("该角色已有参考音频,不允许删除;请改 status=retired")
        for f in sorted(d.rglob("*"), reverse=True):
            f.unlink() if f.is_file() else f.rmdir()
        d.rmdir()
        entries = sync_all()
        return self._json({"ok": True, "characters": entries})

    def _commit(self, body: dict):
        jid = str(body.get("job") or "")
        try:
            idx = int(body.get("index", 0))
        except Exception:
            return self._err("index 非法")
        kind = str(body.get("kind") or "calm")
        cid = str(body.get("character_id") or "").strip()

        if kind not in REF_KINDS:
            return self._err("kind 必须是 calm/intense/whisper")
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,31}", cid):
            return self._err("character_id 必须匹配 ^[a-z][a-z0-9_]{2,31}$")
        with JOB_LOCK:
            job = JOBS.get(jid)
        if not job or job.get("state") != "done":
            return self._err("采集任务未完成")
        cands = job["result"]["candidates"]
        if not (0 <= idx < len(cands)):
            return self._err("候选不存在")
        cand = cands[idx]
        src = WORK_ROOT / jid / cand["file"]
        if not src.is_file():
            return self._err("片段文件已丢失,请重新采集")

        d = CHAR_DIR / cid
        (d / "refs").mkdir(parents=True, exist_ok=True)
        (d / "bench").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, d / "refs" / f"{kind}.wav")

        created = False
        card_path = d / "voice_card.yaml"
        if not card_path.is_file():
            created = True
            tags = [t.strip() for t in str(body.get("tags") or "").split(",") if t.strip()]
            if not tags:
                tags = ["待标注"]
            if len(tags) < 2:
                tags.append("采集")
            card = {
                "character_id": cid,
                "display_name": str(body.get("display_name") or cid),
                "version": "0.1.0",
                "status": "draft",
                "profile": {
                    "gender": str(body.get("gender") or "female"),
                    "age_range": str(body.get("age_range") or "18-30"),
                    "timbre_tags": tags[:6],
                    "archetype": "采集音色",
                },
                "voice": {"rate_baseline": 0.95, "pitch_baseline_st": 0, "breathiness": 0.3},
                "source": {"type": "harvested", "license_ref": f"licenses/{cid}.md"},
                "providers": {
                    "index_tts25": {"ref": "refs/calm.wav", "attn_backend": "sdpa", "out_rate": 22050}
                },
                "fallback_order": ["index_tts25"],
                "notes": f"由采集器从 {job.get('src', '')} 生成。未取得口头/书面授权前不得转 active。",
            }
            write_yaml(card_path, card, header=f"# 由采集器生成于 {date.today().isoformat()}")
            write_yaml(
                d / "presets.yaml",
                {
                    "character_id": cid,
                    "version": "0.1.0",
                    "presets": {
                        "calm": {"rate": 0.95, "emo": {"calm": 0.6, "melancholic": 0.15},
                                 "intensity": 0.3, "pause_after": 0.35, "reverb": "room_small"},
                        "intense": {"rate": 1.05, "emo": {"angry": 0.55, "disgusted": 0.1},
                                    "intensity": 0.8, "pause_after": 0.2, "reverb": "room_small"},
                    },
                },
                header="# 采集后自动生成的预设,请按实际听感调整",
            )

        note = ROOT / "licenses" / f"{cid}.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        block = (
            f"# 采集来源记录 · {kind}\n\n"
            f"- 来源:`{job.get('src', '')}`\n"
            f"- 采集时间:{stamp}\n"
            f"- 片段区间:{cand.get('start')}s – {cand.get('end')}s(时长 {cand.get('duration')}s)\n"
            f"- 人声分离:{'已分离' if cand.get('separated') else '未分离(含 BGM 风险)'}\n"
            f"- 质量评分:{cand.get('score')}/100\n"
            f"- 自动判定:{'通过' if cand.get('ok') else '有告警'}\n\n"
            f"## 授权状态:**未签署**\n\n"
            f"本文件只是来源证据,不是授权。未取得声音权利人书面许可前,\n"
            f"该角色必须保持在 `draft`,不得用于任何发布项目;平台条款亦可能禁止抓取。\n"
        )
        if note.is_file():
            with note.open("a", encoding="utf-8") as f:
                f.write("\n---\n\n" + block)
        else:
            note.write_text(block, encoding="utf-8")

        entries = sync_all()
        validation = validate_character(d)
        return self._json(
            {
                "ok": True,
                "created": created,
                "character_id": cid,
                "validation": validation,
                "characters": entries,
            }
        )


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    port = 8767
    sync_all()
    print(f"voicelib 控制台  →  http://127.0.0.1:{port}")
    print(f"库根目录          →  {ROOT}")
    print("Ctrl+C 停止")
    Server(("127.0.0.1", port), Handler).serve_forever()
