"""合成适配器:把「角色 + 预设 + 台词」变成一段 wav

支持两种协议:
  - openai_speech: POST {base}/audio/speech(任意 OpenAI 兼容端点)
  - fish_tts     : POST https://api.fish.audio/v1/tts(零样本克隆)

设计约束(对应 SPEC):
  L3-07 密钥/端点只从环境变量读,绝不落盘
  L1-03 数字必须在送合成前转汉字
  L3-02 库内 rate(>1 更快)在这里翻译成供应商语义
"""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
import wave
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "_shared" / "tts_api.yaml"

_DIGIT = str.maketrans("0123456789", "零一二三四五六七八九")


def normalize_zh(text: str) -> str:
    """预归一化:数字逐位转汉字(替代 pynini,Windows 上唯一可行方案)"""
    return re.sub(r"\d", lambda m: m.group().translate(_DIGIT), text)


def load_config() -> dict:
    if not CONFIG.is_file():
        return {"providers": {}, "default_provider": None}
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}


def provider_status() -> list[dict]:
    """返回每个供应商是否可用(只看环境变量是否就位,不发请求)"""
    cfg = load_config()
    out = []
    for name, p in (cfg.get("providers") or {}).items():
        key_env = p.get("api_key_env", "")
        base_ok = True
        if p.get("base_url_env"):
            base_ok = bool(os.environ.get(p["base_url_env"]))
        item = {
            "name": name,
            "display": p.get("display", name),
            "protocol": p.get("protocol"),
            "supports_clone": bool(p.get("supports_clone")),
            "key_env": key_env,
            "ready": bool(os.environ.get(key_env)) and base_ok,
            "missing": []
            if (os.environ.get(key_env) and base_ok)
            else ([key_env] if not os.environ.get(key_env) else [p.get("base_url_env")]),
        }
        out.append(item)
    return out


def _http_json(url: str, payload: dict, headers: dict, timeout: int = 120) -> tuple[int, bytes, str]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), r.headers.get("content-type", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("content-type", "") if e.headers else ""
    except Exception as e:  # 网络/DNS/超时
        return 0, str(e).encode("utf-8"), ""


def _save_audio(body: bytes, out: Path, ctype: str) -> None:
    """接口可能直接回 wav,也可能回 JSON 里带 base64"""
    if ctype.startswith("application/json") or body[:1] == b"{":
        data = json.loads(body.decode("utf-8"))
        for k in ("audio", "data", "audio_base64", "audioContent"):
            v = data.get(k)
            if isinstance(v, str):
                body = base64.b64decode(v)
                break
        else:
            raise RuntimeError("接口返回 JSON 但没有音频字段:" + ", ".join(list(data)[:5]))
    out.write_bytes(body)


def _openai_speech(p: dict, text: str, out: Path, ref: Path | None, speed: float) -> dict:
    base = os.environ.get(p["base_url_env"], "").rstrip("/")
    key = os.environ.get(p["api_key_env"], "")
    url = base + p.get("path", "/audio/speech")
    payload = {
        "model": p.get("model", "gpt-4o-mini-tts"),
        "voice": p.get("voice", "alloy"),
        "input": text,
        "response_format": p.get("response_format", "wav"),
        "speed": round(speed, 3),
    }
    code, body, ctype = _http_json(url, payload, {"Authorization": f"Bearer {key}"})
    if code != 200:
        raise RuntimeError(f"HTTP {code}: {body[:200].decode('utf-8', 'replace')}")
    _save_audio(body, out, ctype)
    return {"provider": "openai_compat", "voice": payload["voice"], "speed": payload["speed"]}


def _fish(p: dict, text: str, out: Path, ref: Path | None, speed: float) -> dict:
    base = p.get("base_url", "https://api.fish.audio").rstrip("/")
    key = os.environ.get(p["api_key_env"], "")
    payload: dict = {
        "text": text,
        "format": p.get("format", "wav"),
        "normalize": True,
        "latency": "normal",
    }
    ref_id = os.environ.get(p.get("reference_id_env", ""), "")
    if ref_id:
        payload["reference_id"] = ref_id
    elif ref and p.get("use_local_ref", True):
        payload["references"] = [{"audio": base64.b64encode(ref.read_bytes()).decode(), "text": ""}]
    else:
        raise RuntimeError("Fish 需要 FISH_REFERENCE_ID,或角色有 refs/calm.wav")

    code, body, ctype = _http_json(
        base + "/v1/tts", payload, {"Authorization": f"Bearer {key}", "model": "s1"}, timeout=180
    )
    if code != 200:
        raise RuntimeError(f"HTTP {code}: {body[:200].decode('utf-8', 'replace')}")
    _save_audio(body, out, ctype)
    return {"provider": "fish", "ref": ref_id or "inline-reference"}


def probe_wav(path: Path) -> dict:
    try:
        with wave.open(str(path), "rb") as w:
            return {
                "duration": round(w.getnframes() / w.getframerate(), 2),
                "sample_rate": w.getframerate(),
                "channels": w.getnchannels(),
            }
    except Exception:
        return {"duration": None, "sample_rate": None, "channels": None}


def synthesize(
    text: str,
    out: Path,
    provider: str | None = None,
    rate: float = 1.0,
    ref: Path | None = None,
) -> dict:
    cfg = load_config()
    providers = cfg.get("providers") or {}
    name = provider or cfg.get("default_provider")
    if name not in providers:
        raise RuntimeError(f"未知供应商:{name},可选 {list(providers)}")
    p = providers[name]

    key_env = p.get("api_key_env", "")
    if not os.environ.get(key_env):
        raise RuntimeError(f"缺少环境变量 {key_env}。设置后重开终端再启动服务")

    norm = normalize_zh(text)
    out.parent.mkdir(parents=True, exist_ok=True)

    if p.get("protocol") == "openai_speech":
        meta = _openai_speech(p, norm, out, ref, rate)
    elif p.get("protocol") == "fish_tts":
        meta = _fish(p, norm, out, ref, rate)
    else:
        raise RuntimeError(f"未实现的协议:{p.get('protocol')}")

    if not out.is_file() or out.stat().st_size < 512:
        raise RuntimeError("接口返回的音频为空")
    info = probe_wav(out)
    return {"ok": True, "provider": name, "text": norm, "bytes": out.stat().st_size, **meta, **info}
