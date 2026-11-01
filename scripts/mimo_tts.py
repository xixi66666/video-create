"""通过 MiMo 官方接口合成 WAV；密钥只从环境变量读取。"""
import argparse
import base64
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request
import wave
from io import BytesIO

API_URL = 'https://api.xiaomimimo.com/v1/chat/completions'
MODEL = 'mimo-v2.5-tts'
VOICES = ('冰糖', '茉莉', '苏打', '白桦', 'Mia', 'Chloe', 'Milo', 'Dean')


def synthesize(text, context, voice, api_key):
    if not text.strip() or len(text) > 5000 or len(context) > 1000 or voice not in VOICES:
        raise ValueError('文本、风格说明或音色不符合要求')
    if not api_key:
        raise ValueError('未设置 MIMO_API_KEY 环境变量')
    messages = ([{'role':'user', 'content':context}] if context else []) + [{'role':'assistant', 'content':text}]
    body = json.dumps({'model':MODEL, 'messages':messages, 'audio':{'format':'wav','voice':voice}}, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(API_URL, data=body, headers={'Authorization':'Bearer '+api_key, 'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            raw = response.read(40 * 1024 * 1024 + 1)
    except urllib.error.HTTPError as exc:
        raise ValueError(f'MiMo 请求失败，HTTP {exc.code}') from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ValueError('MiMo 服务连接失败，请检查网络') from None
    if len(raw) > 40 * 1024 * 1024:
        raise ValueError('MiMo 返回数据过大')
    try:
        encoded = json.loads(raw)['choices'][0]['message']['audio']['data']
        audio = base64.b64decode(encoded, validate=True)
        with wave.open(BytesIO(audio), 'rb') as wav:
            if wav.getnframes() <= 0 or wav.getframerate() <= 0:
                raise ValueError('空音频')
    except (KeyError, IndexError, TypeError, ValueError, wave.Error, EOFError):
        raise ValueError('MiMo 未返回有效 WAV 音频') from None
    return audio


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--text-file', required=True, help='UTF-8 文本文件')
    parser.add_argument('--output', required=True, help='输出 WAV 路径，不覆盖现有文件')
    parser.add_argument('--voice', default='茉莉', choices=VOICES)
    parser.add_argument('--context', default='自然、克制、有情绪层次的中文纪录片旁白')
    args = parser.parse_args()
    try:
        text = Path(args.text_file).read_text(encoding='utf-8')
        output = Path(args.output)
        if output.exists():
            raise ValueError('输出文件已存在，未覆盖')
        audio = synthesize(text, args.context, args.voice, os.getenv('MIMO_API_KEY'))
        with output.open('xb') as target:
            target.write(audio)
        print('音频已生成：', output)
    except (ValueError, OSError) as exc:
        print('生成失败：' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
