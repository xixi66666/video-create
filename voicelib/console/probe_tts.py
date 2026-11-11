"""探测一个 TTS 端点是否可用(注册后先跑这个,别急着配)

用法:
    python probe_tts.py --base https://api.xxx.com/v1 --key sk-xxx
    python probe_tts.py --base https://api.xxx.com/v1 --key sk-xxx --voice my_voice --model my_model
    python probe_tts.py --base https://api.xxx.com/v1 --key sk-xxx --path /audio/speech

判定:
    200 + audio/*   → 可用,直接把 --base 填进 TTS_BASE_URL
    404             → 该站没有语音接口(只做 chat),换一家
    401/403         → key 不对或没额度
    400             → 通了但参数不对,多半是 model / voice 名
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="如 https://api.siliconflow.cn/v1")
    ap.add_argument("--key", required=True)
    ap.add_argument("--path", default="/audio/speech")
    ap.add_argument("--model", default="gpt-4o-mini-tts")
    ap.add_argument("--voice", default="alloy")
    ap.add_argument("--text", default="这是一次接口连通性测试。")
    ap.add_argument("--format", default="wav")
    args = ap.parse_args()

    url = args.base.rstrip("/") + args.path
    payload = {
        "model": args.model,
        "voice": args.voice,
        "input": args.text,
        "response_format": args.format,
    }
    print(f"POST {url}")
    print(f"     model={args.model}  voice={args.voice}  format={args.format}")

    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {args.key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read()
            ctype = r.headers.get("content-type", "")
            code = r.status
    except urllib.error.HTTPError as e:
        body = e.read()
        ctype = (e.headers.get("content-type", "") if e.headers else "") or ""
        code = e.code
    except Exception as e:
        print(f"\n[X] 连不上:{e}")
        print("    检查:base 是否带 /v1、是否要代理、域名是否可达")
        return 2

    print(f"\nHTTP {code}  content-type={ctype}  {len(body)} bytes")

    if code == 200 and (ctype.startswith("audio/") or body[:4] in (b"RIFF", b"OggS", b"ID3\x03")):
        print("[OK] 可用。把下面这行填进环境变量:")
        print(f'     $env:TTS_BASE_URL = "{args.base}"')
        if len(body) > 1024:
            with open("probe_output.bin", "wb") as f:
                f.write(body)
            print(f"     (已保存样本到 probe_output.bin,{len(body)} bytes)")
        return 0

    if code == 200:
        print("[?] 返回 200 但不是音频,可能是 JSON。前 300 字节:")
        print("    " + body[:300].decode("utf-8", "replace"))
        print("    → 这家的字段名不同,需要改 console/synth.py 的 _save_audio()")
        return 1

    hint = {
        404: "该站没有语音接口(或路径不对)。很多聚合站只做 chat —— 换一家",
        401: "key 无效",
        403: "key 无权访问该模型,或额度用尽",
        400: "接口存在但参数不对:多半是 model / voice 名不对,换一个再试",
        429: "限流,等一会儿再试",
    }.get(code, "")
    print(f"[X] {hint}")
    print("    返回体前 300 字节:")
    print("    " + body[:300].decode("utf-8", "replace"))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
