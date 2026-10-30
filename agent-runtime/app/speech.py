import base64
import binascii
import io
import json
import os
import urllib.error
import urllib.request
import wave

from fastapi import HTTPException

ENDPOINT = 'https://api.xiaomimimo.com/v1/chat/completions'
VOICES = {'苏打', '冰糖', '茉莉', '白桦'}
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


def synthesize(text: str, voice: str) -> dict:
    if os.getenv('CREATOR_ENABLE_MIMO_TTS', '').lower() != 'true':
        raise HTTPException(409, 'MiMo TTS 未启用')
    key = os.getenv('MIMO_API_KEY', '')
    if not key:
        raise HTTPException(503, 'MiMo TTS 凭据未配置')
    if not text.strip() or len(text) > 1000 or voice not in VOICES:
        raise HTTPException(400, '文本不能为空或超过 1000 字，音色必须为支持的预设')
    payload = {'model': 'mimo-v2.5-tts', 'messages': [{'role': 'assistant', 'content': text}],
               'audio': {'format': 'wav', 'voice': voice}, 'stream': False}
    request = urllib.request.Request(ENDPOINT, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                                     headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key}, method='POST')
    try:
        # 禁止自动重试，也不跟随可能泄露认证头的重定向。
        opener = urllib.request.build_opener(_NoRedirect())
        with opener.open(request, timeout=80) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise HTTPException(502, 'MiMo 响应过大，未保存音频')
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise HTTPException(502, 'MiMo 认证失败或账户无权限') from None
        if exc.code == 429:
            raise HTTPException(429, 'MiMo 请求受限，请稍后手动重试') from None
        raise HTTPException(502, 'MiMo 请求失败，请检查供应商状态；未自动重试') from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise HTTPException(504, 'MiMo 请求超时或网络中断，供应商处理状态未知；未自动重试') from None
    try:
        audio = json.loads(raw)['choices'][0]['message']['audio']['data']
        if not isinstance(audio, str):
            raise ValueError()
        decoded = base64.b64decode(audio, validate=True)
        with wave.open(io.BytesIO(decoded), 'rb') as f:
            if f.getnframes() == 0 or f.getnchannels() not in (1, 2):
                raise ValueError()
    except (ValueError, TypeError, KeyError, IndexError, json.JSONDecodeError, binascii.Error, wave.Error, EOFError):
        raise HTTPException(502, 'MiMo 返回的音频无效；未自动重试') from None
    return {'audioBase64': audio, 'format': 'wav', 'model': 'mimo-v2.5-tts'}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None
