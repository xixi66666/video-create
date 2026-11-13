"""配音 CLI：本地采集、选择参考样本、调用 MiMo 试音或分段朗诵。"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import wave


def directory(role_id):
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,31}", role_id) or role_id in {
        "con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))
    }:
        raise ValueError("角色 ID 使用 3–32 位小写英文、数字或下划线，以字母开头，避开系统保留名")
    default = Path(__file__).resolve().parents[1] / ".voice-data"
    return Path(os.environ.get("VOICELIB_HOME") or default).expanduser().resolve() / role_id


def reference(role, number):
    manifest = json.loads((role / "manifest.json").read_text(encoding="utf-8"))
    if manifest["character_id"] != role.name or not 1 <= number <= len(manifest["clips"]):
        raise ValueError("角色或候选编号无效，请检查 manifest.json")
    clip = manifest["clips"][number - 1]
    filename = f"{number:02}-vocals.wav"
    if clip["vocals"] != filename:
        raise ValueError("候选文件名与编号不符")
    data = (role / filename).read_bytes()
    if hashlib.sha1(data).hexdigest() != clip["sha1"]:
        raise ValueError("参考 WAV 指纹已改变，请重新采集")
    return clip, data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    steps = parser.add_subparsers(dest="command", required=True)
    steps.add_parser("doctor", help="检查解释器、软件和凭据配置")
    extract = steps.add_parser("extract", help="从链接或本地音视频提取候选")
    extract.add_argument("role")
    extract.add_argument("source")
    extract.add_argument("--start", type=float, default=0, help="处理范围的起始秒数")
    extract.add_argument("--seconds", type=float, help="最多处理多少秒，默认到音轨结尾")
    extract.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    extract.add_argument("--clean", action="store_true", help="素材已经是干声，跳过 Demucs")
    choose = steps.add_parser("select", help="选定候选，在角色目录登记版本")
    choose.add_argument("role")
    choose.add_argument("number", type=int)
    choose.add_argument("--name", required=True)
    speak = steps.add_parser("speak", help="将选定样本和台词发给 MiMo 生成 WAV")
    speak.add_argument("role")
    source = speak.add_mutually_exclusive_group(required=True)
    source.add_argument("--text")
    source.add_argument("--text-file", type=Path)
    speak.add_argument("--style", default="", help="可选的语气或读音指令")
    speak.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command in ("doctor", "speak"):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent-runtime"))
        from app.local_voice_config import load
        load(include_database=False)
    if args.command == "doctor":
        import importlib.metadata as metadata
        import shutil
        missing = False
        print(f"Python {sys.version.split()[0]} | {sys.executable}")
        for name in ("numpy", "yt-dlp", "torch", "demucs"):
            try:
                print(f"{name}: {metadata.version(name)}")
            except metadata.PackageNotFoundError:
                missing = True
                print(f"{name}: 缺失")
        for name in ("ffmpeg", "ffprobe"):
            path = shutil.which(name)
            print(f"{name}: {path or '缺失'}")
            missing |= path is None
        if not missing:
            import torch
            import demucs.separate
            print(f"CUDA 可用：{torch.cuda.is_available()}")
        print("MiMo 凭据：" + ("已配置" if os.getenv("MIMO_API_KEY") else "未配置（仅 speak 使用）"))
        return int(missing)
    role = directory(args.role)
    if args.command == "extract":
        if not math.isfinite(args.start) or args.start < 0:
            raise ValueError("起点必须为非负有限秒数")
        if args.seconds is not None and (not math.isfinite(args.seconds) or args.seconds < 10):
            raise ValueError("处理范围至少 10 秒")
        from extraction import prepare
        prepare(args, role)
    elif args.command == "select":
        clip, _ = reference(role, args.number)
        name = args.name.strip()
        if not name:
            raise ValueError("角色名不能为空")
        card = {"character_id": role.name, "version": "1.0.0", "name": name,
                "candidate": args.number, "reference": clip["vocals"], "sha1": clip["sha1"]}
        # 一个角色版本对应同一份参考音频。重复选择同一个样本可安全重跑。
        target = role / "character.json"
        if target.exists():
            if json.loads(target.read_text(encoding="utf-8")) != card:
                raise ValueError("此角色已定档，换参考时请使用新的采集目录，已有样本仍可复现")
        else:
            with target.open("x", encoding="utf-8") as f:
                json.dump(card, f, ensure_ascii=False, indent=2)
        print(f"选定 {clip['start']}–{clip['end']} 秒：{target}")
    else:
        from synthesis import render
        card = json.loads((role / "character.json").read_text(encoding="utf-8"))
        clip, data = reference(role, card["candidate"])
        if (card["character_id"], card["reference"], card["sha1"]) != (role.name, clip["vocals"], clip["sha1"]):
            raise ValueError("角色与样本记录不一致")
        text = args.text if args.text is not None else args.text_file.read_text(encoding="utf-8-sig")
        render(data, text, args.style, args.out, role)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError, ImportError, RuntimeError,
            wave.Error, EOFError, subprocess.SubprocessError) as exc:
        sys.exit(f"失败：{exc}")
