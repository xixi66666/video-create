"""Colab IndexTTS-2.5 客户端:一次命令完成「提交 → 等 → 拿 wav」

原理:往你 fork 的 index-tts-in-colab 仓库开一个 issue(表单格式),
GitHub Actions 自动拉起免费 Colab T4 跑 IndexTTS,完成后在 issue 里回 Release 链接,
本脚本轮询、下载、落盘。

用法:
    $env:GH_TOKEN = "ghp_xxx"            # 需要 repo 权限(public fork 用 public_repo 也行)
    python colab_tts.py --repo 你的用户名/index-tts-in-colab `
        --text "第一句\n第二句" --emotion 悲傷 --weight 0.85 --model 2.5 --out out.wav

    # 只看会提交什么,不真的发:
    python colab_tts.py --repo ... --text "测试" --dry-run

字段名对应 .github/ISSUE_TEMPLATE/synthesize.yml,改模板要同步改这里。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.github.com"

# 情绪选项必须与模板里的 options 逐字一致(parser 用子串匹配中文名)
EMOTIONS = {
    "自然": "自然 (neutral)",
    "高興": "高興 (happy)",
    "憤怒": "憤怒 (angry)",
    "悲傷": "悲傷 (sad)",
    "低落": "低落 (melancholic)",
    "驚訝": "驚訝 (surprised)",
}
MODEL_25 = "2.5（較快，但中文偏大陸腔）"
MODEL_20 = "2.0（貼近參考音檔原始腔調，推薦）"

# 与 parse_issue.py 的限额保持一致
MAX_LINES = 200
MAX_TOTAL_CHARS = 6000
MAX_LINE_CHARS = 200


def build_body(text: str, emotion: str, weight: float, model: str) -> str:
    """拼出 GitHub issue 表单渲染后的正文格式(### 标签 + 空行 + 值)"""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ValueError("文本为空")
    if len(lines) > MAX_LINES:
        raise ValueError(f"行数超限:{len(lines)} > {MAX_LINES}")
    bad = [ln for ln in lines if len(ln) > MAX_LINE_CHARS]
    if bad:
        raise ValueError(f"单行超过 {MAX_LINE_CHARS} 字:{bad[0][:30]}…")
    total = sum(len(ln) for ln in lines)
    if total > MAX_TOTAL_CHARS:
        raise ValueError(f"总字数超限:{total} > {MAX_TOTAL_CHARS}")
    if any(ln.startswith("###") for ln in lines):
        raise ValueError("文本里不能有以 ### 开头的行(会被当成表单字段)")

    emo_label = EMOTIONS.get(emotion) or next((v for v in EMOTIONS.values() if emotion in v), None)
    if not emo_label:
        raise ValueError(f"未知情绪:{emotion},可选 {list(EMOTIONS)}")
    model_label = MODEL_25 if str(model).startswith("2.5") else MODEL_20

    return "\n\n".join(
        [
            "### 要朗讀的文字",
            "\n".join(lines),
            "### 情緒",
            emo_label,
            "### 情緒強度 (0.1 - 1.0)",
            f"{float(weight):.2f}",
            "### 模型版本",
            model_label,
        ]
    ) + "\n"


def parse_sections(body: str) -> dict:
    """与 parse_issue.py 同款切分,用于自检"""
    out = {}
    parts = re.split(r"^### (.+)$", body, flags=re.MULTILINE)
    for i in range(1, len(parts), 2):
        out[parts[i].strip()] = parts[i + 1].strip() if i + 1 < len(parts) else ""
    return out


def _req(method: str, path: str, token: str, payload: dict | None = None) -> tuple[int, dict | bytes]:
    url = path if path.startswith("http") else API + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "voicelib-colab-tts",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            ctype = r.headers.get("content-type", "")
            return r.status, (json.loads(raw) if "json" in ctype else raw)
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:300]


def create_issue(repo: str, title: str, body: str, token: str) -> int:
    code, data = _req(
        "POST",
        f"/repos/{repo}/issues",
        token,
        {"title": title, "body": body, "labels": ["synthesize"]},
    )
    if code not in (200, 201):
        raise RuntimeError(f"建 issue 失败 HTTP {code}: {data}")
    return int(data["number"])  # type: ignore[index]


def wait_for_release(repo: str, issue: int, token: str, timeout: int, interval: int) -> str:
    """轮询 issue 评论,等出现 release 链接;返回 tag 或 asset URL"""
    deadline = time.time() + timeout
    last_note = 0
    while time.time() < deadline:
        code, data = _req("GET", f"/repos/{repo}/issues/{issue}/comments", token)
        if code == 200 and isinstance(data, list):
            for c in data:
                body = c.get("body") or ""
                m = re.search(r"/releases/tag/([^\s\)\]]+)", body)
                if m:
                    return m.group(1)
                m2 = re.search(r"/releases/download/([^\s\)\]]+)", body)
                if m2:
                    return "asset:" + m2.group(1)
        if time.time() - last_note > 120:
            print("   …仍在跑(Colab 首次要下 6GB 模型,15 分钟属正常)", flush=True)
            last_note = time.time()
        time.sleep(interval)
    raise TimeoutError(f"等待超时({timeout}s)。去 {repo}/issues/{issue} 看进度")


def download_release_asset(repo: str, tag: str, token: str, out: Path) -> Path:
    code, rel = _req("GET", f"/repos/{repo}/releases/tags/{tag}", token)
    if code != 200:
        raise RuntimeError(f"取 release 失败 HTTP {code}: {rel}")
    assets = [a for a in rel.get("assets", []) if str(a.get("name", "")).lower().endswith(".wav")]
    if not assets:
        raise RuntimeError("该 release 里没有 wav")
    a = assets[0]
    out.parent.mkdir(parents=True, exist_ok=True)
    # 私有仓库需要带 token;用 curl 更省事,但这里统一走 urllib
    req = urllib.request.Request(
        a["url"],
        headers={"Authorization": f"Bearer {token}", "Accept": "application/octet-stream"},
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        out.write_bytes(r.read())
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="如 yourname/index-tts-in-colab")
    ap.add_argument("--text", required=True, help="多行用 \\n 分隔;每行=一段")
    ap.add_argument("--emotion", default="自然")
    ap.add_argument("--weight", type=float, default=0.85)
    ap.add_argument("--model", default="2.5", choices=["2.0", "2.5"])
    ap.add_argument("--out", default="colab_tts.wav")
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--interval", type=int, default=30)
    ap.add_argument("--dry-run", action="store_true", help="只打印 issue 正文")
    args = ap.parse_args()

    text = args.text.replace("\\n", "\n")
    body = build_body(text, args.emotion, args.weight, args.model)

    if args.dry_run:
        print(body)
        sec = parse_sections(body)
        print("--- 自检:解析回来的字段 ---", file=sys.stderr)
        for k, v in sec.items():
            print(f"  {k} = {v!r}", file=sys.stderr)
        return 0

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    if not token:
        print("[X] 缺 GH_TOKEN。生成:GitHub → Settings → Developer settings → "
              "Personal access tokens → 勾 repository 读写", file=sys.stderr)
        return 2

    title = f"[synthesize] voicelib {time.strftime('%m-%d %H:%M')}"
    print(f"提交 issue → {args.repo}")
    issue = create_issue(args.repo, title, body, token)
    print(f"  issue #{issue} 已创建,等待 Colab…")

    try:
        tag = wait_for_release(args.repo, issue, token, args.timeout, args.interval)
    except TimeoutError as e:
        print(f"[X] {e}", file=sys.stderr)
        return 1

    out = Path(args.out)
    if tag.startswith("asset:"):
        url = API + "/repos/" + args.repo + "/releases/assets/" + tag.split("/")[-1]
        print("  下载 asset…")
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}",
                                                   "Accept": "application/octet-stream"})
        with urllib.request.urlopen(req, timeout=300) as r:
            out.write_bytes(r.read())
    else:
        print(f"  下载 release {tag} …")
        download_release_asset(args.repo, tag, token, out)

    size = out.stat().st_size
    print(f"[OK] 已保存 {out}  ({size/1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
