"""MiMo 音色复刻；缓存成功返回的段落，完整校验后才发布合并文件。"""
import base64
from contextlib import ExitStack
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.error
import urllib.request
import wave

import numpy as np

MODEL = os.environ.get("CREATOR_MIMO_VOICECLONE_MODEL", "mimo-v2.5-tts-voiceclone")
ENDPOINT = "https://api.xiaomimimo.com/v1/chat/completions"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def request_audio(voice, text, style, key):
    messages = [{"role": "user", "content": style}] if style else []
    messages.append({"role": "assistant", "content": text})
    payload = {"model": MODEL, "messages": messages, "stream": False, "audio": {"format": "wav", "voice": voice}}
    req = urllib.request.Request(ENDPOINT, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", "api-key": key})
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=120) as resp:
            raw = resp.read(8 * 1024 * 1024 + 1)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"MiMo HTTP {exc.code}。请检查凭据、模型权限或限流，未自动重试") from None
    except (OSError, TimeoutError):
        raise RuntimeError("MiMo 连接失败或超时，计费情况请查看供应商记录，未自动重试") from None
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("MiMo 响应过大")
    return base64.b64decode(json.loads(raw)["choices"][0]["message"]["audio"]["data"], validate=True)


def read_pcm(raw):
    with wave.open(io.BytesIO(raw)) as wav:
        hz = wav.getframerate()
        if hz < 22050 or wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise ValueError("MiMo 输出格式不符合要求，需要至少 22050 Hz 的单声道 PCM16 WAV")
        data = wav.readframes(wav.getnframes())
        if len(data) != wav.getnframes() * 2:
            raise ValueError("WAV 数据不完整")
    signal = np.frombuffer(data, dtype="<i2")
    hop = hz // 100
    frames = signal[:len(signal) // hop * hop].astype(np.float32).reshape(-1, hop)
    voiced = np.flatnonzero(np.mean(frames ** 2, axis=1) > 100 ** 2)
    if not len(voiced):
        raise ValueError("MiMo 返回空音频或静音")
    # 只裁掉首尾过长的留白，保留语句内部自然停顿。
    start = max(0, (int(voiced[0]) - 12) * hop)
    end = min(len(signal), (int(voiced[-1]) + 1 + 20) * hop)
    return hz, signal[start:end].tobytes()


def render(reference, text, style, output, role):
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    if not paragraphs or any(sum(not c.isspace() for c in p) > 40 for p in paragraphs):
        raise ValueError("每个合成块需 1–40 个非空白字符；长稿请在自然停顿处用空行分段")
    if output.suffix.lower() != ".wav" or output.exists():
        raise ValueError("请选择尚不存在的 .wav 输出文件")
    key = os.environ.get("MIMO_API_KEY")
    if not key:
        raise ValueError("请为当前进程配置 MIMO_API_KEY")
    digest = hashlib.sha256(reference).hexdigest()
    voice = "data:audio/wav;base64," + base64.b64encode(reference).decode("ascii")
    cache = role / "takes"
    cache.mkdir(exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as staging:
        assembled = Path(staging) / "output.wav"
        with ExitStack() as stack:
            rate = None
            for i, paragraph in enumerate(paragraphs, 1):
                params = json.dumps([ENDPOINT, MODEL, digest, style, paragraph]).encode()
                path = cache / (hashlib.sha256(params).hexdigest() + ".wav")
                cached = path.is_file()
                print(f"段落 {i}/{len(paragraphs)} | {'读取本地结果' if cached else '请求 MiMo'}", flush=True)
                if cached:
                    raw = path.read_bytes()
                else:
                    raw = request_audio(voice, paragraph, style, key)
                hz, pcm = read_pcm(raw)
                if rate is None:
                    dest = stack.enter_context(wave.open(str(assembled), "wb"))
                    dest.setnchannels(1)
                    dest.setsampwidth(2)
                    rate = hz
                    dest.setframerate(rate)
                elif hz != rate:
                    raise ValueError("段落采样率不一致")
                if not cached:
                    with tempfile.NamedTemporaryFile(dir=cache, delete=False) as part:
                        part.write(raw)
                    Path(part.name).replace(path)
                if i > 1:
                    dest.writeframesraw(b"\0\0" * round(rate * 0.35))
                dest.writeframesraw(pcm)
        if output.exists():
            raise ValueError("输出文件已被其他任务创建，请更换文件名")
        assembled.rename(output)
    with wave.open(str(output), "rb") as wav:
        print(f"{output} | {wav.getnframes() / wav.getframerate():.2f} 秒 | {wav.getframerate()} Hz")
