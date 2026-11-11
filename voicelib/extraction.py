"""准备音轨，按人声活动和人声/伴奏相对能量筛选参考片段。"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
import wave

import numpy as np

RATE = 44100
HOP = RATE // 50  # 每帧 20 毫秒


def fetch(source, work):
    url = urlsplit(source)
    if url.scheme.lower() in {"https", "http"}:
        if not url.hostname or url.username or url.password:
            raise ValueError("请输入不带登录凭据的音视频链接")
        media_id = work / "media-id.txt"
        subprocess.run([sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist",
                        "--no-progress", "--print-to-file", "after_move:%(id)s", str(media_id),
                        "-f", "bestaudio/best", "-o", str(work / "source.%(ext)s"),
                        "--", source], check=True, timeout=900)
        files = [p for p in work.glob("source.*") if p.suffix not in {".part", ".ytdl"}]
        if len(files) != 1:
            raise ValueError("下载未产生唯一的完整媒体文件")
        # 不把跟踪参数、签名或访问凭据写入声卡。
        return files[0], {"url": f"{url.scheme}://{url.hostname}{url.path}",
                          "media_id": media_id.read_text(encoding="utf-8").strip()}
    path = Path(source).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError("素材必须是本地文件或 HTTP(S) 链接")
    return path, {"file": path.name}


def levels(path):
    """分块读取立体声 PCM，保留帧级能量，避免整部视频常驻内存。"""
    blocks = []
    with wave.open(str(path), "rb") as reader:
        if reader.getsampwidth() != 2 or reader.getframerate() != RATE:
            raise ValueError(f"需要 44.1 kHz PCM16 WAV：{path.name}")
        channels = reader.getnchannels()
        while data := reader.readframes(HOP * 1000):
            mono = np.frombuffer(data, dtype="<i2").reshape(-1, channels).mean(axis=1, dtype=np.float32)
            frames = mono[:len(mono) // HOP * HOP].reshape(-1, HOP) / 32768
            blocks.append(10 * np.log10(np.mean(frames ** 2, axis=1) + 1e-12))
    return np.concatenate(blocks) if blocks else np.empty(0)


def windows(voice, music):
    count = len(voice) if music is None else min(len(voice), len(music))
    width = min(600, count)
    if width < 500:
        raise ValueError("音频不足 10 秒，换较长素材或扩大处理范围")
    ranked = []
    for i in range(0, count - width + 1, 5):
        v = voice[i:i + width]
        active = v > -42
        fraction = active.mean()
        if fraction < 0.55:
            continue
        edges = np.r_[v[:5], v[-5:]]
        score = 3 * (fraction + (edges < -46).mean())
        if music is not None:
            relative = np.median((v - music[i:i + width])[active])
            score += np.clip(relative, -18, 18) / 9
        ranked.append((float(score), i))
    chosen = []
    for _, i in sorted(ranked, key=lambda item: -item[0]):
        if all(abs(i - prev) >= width for prev in chosen):
            chosen.append(i)
            if len(chosen) == 3:
                break
    if not chosen:
        raise ValueError("未找到足够连续的人声，可换时间段或换素材")
    return [(i / 50, width / 50) for i in chosen]


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", *map(str, args)],
                   check=True, timeout=1800)


def prepare(args, role):
    if not shutil.which("ffmpeg"):
        raise ValueError("找不到 ffmpeg，请安装并加入 PATH 后重新打开终端")
    role.parent.mkdir(parents=True, exist_ok=True)
    if role.exists():
        raise ValueError(f"角色目录已存在：{role}，请使用新的角色 ID")
    with tempfile.TemporaryDirectory(dir=role.parent) as staging:
        work = Path(staging)
        result = work / "result"
        result.mkdir()
        media, source = fetch(args.source, work)
        mix = work / "mix.wav"
        limit = ["-t", args.seconds] if args.seconds is not None else []
        ffmpeg("-ss", args.start, "-i", media, *limit, "-map", "0:a:0", "-vn", "-ac", 2,
               "-ar", RATE, "-c:a", "pcm_s16le", mix)
        vocal, music = mix, None
        if not args.clean:
            env = dict(os.environ)
            env.setdefault("OMP_NUM_THREADS", "4")
            env.setdefault("MKL_NUM_THREADS", "4")
            subprocess.run([sys.executable, "-m", "demucs", "--two-stems=vocals", "-n", "htdemucs",
                            "-d", args.device, "-o", str(work / "stems"), str(mix)],
                           env=env, check=True, timeout=7200)
            vocal = work / "stems" / "htdemucs" / "mix" / "vocals.wav"
            music = levels(vocal.with_name("no_vocals.wav"))
        clips = []
        for n, (start, seconds) in enumerate(windows(levels(vocal), music), 1):
            clip = {"start": round(args.start + start, 2), "end": round(args.start + start + seconds, 2)}
            for label, track in (("original", mix), ("vocals", vocal)):
                name = f"{n:02}-{label}.wav"
                ffmpeg("-ss", start, "-i", track, "-t", seconds, "-ac", 1, "-ar", RATE,
                       "-c:a", "pcm_s16le", result / name)
                with wave.open(str(result / name), "rb") as wav:
                    if wav.getnframes() != round(seconds * RATE):
                        raise ValueError("导出的候选时长与原片时间不一致")
                clip[label] = name
            clip["sha1"] = hashlib.sha1((result / clip["vocals"]).read_bytes()).hexdigest()
            clips.append(clip)
        report = {"character_id": role.name, "source": source, "separator": None if args.clean else "htdemucs",
                  "clips": clips}
        (result / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        result.rename(role)
        print(f"已保存 {len(clips)} 组试听对照：{role}")
