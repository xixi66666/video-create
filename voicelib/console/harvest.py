"""采集流水线:链接/文件 → 纯人声候选 → 角色参考音频

阶段:
  1. 下载(yt-dlp)或读取本地文件
  2. 抽音轨(ffmpeg)→ 44.1kHz 单声道 WAV
  3. 人声分离(demucs,可选;缺失则跳过并标记)
  4. 能量 VAD 切段 → 每段挑最佳 12 秒窗口
  5. 打分 + 写出候选片段

设计原则:
  - 每个阶段都可以失败,失败要给出人话原因,不要静默跳过
  - 「疑似单人」是启发式,不是说话人分离模型;UI 必须如实标注
"""

from __future__ import annotations

import glob
import json
import re
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np

SR_TARGET = 44100
FRAME_MS = 20


# ────────────────────────── 依赖探测 ──────────────────────────
def ffmpeg_path() -> str | None:
    p = shutil.which("ffmpeg")
    if p:
        return p
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def deps() -> dict:
    out = {"ffmpeg": ffmpeg_path(), "yt_dlp": None, "demucs": None, "torch": None}
    try:
        import yt_dlp  # noqa: F401

        out["yt_dlp"] = getattr(yt_dlp.version, "__version__", "ok")
    except Exception:
        pass
    try:
        import torch

        out["torch"] = torch.__version__
        out["cuda"] = bool(torch.cuda.is_available())
    except Exception:
        pass
    try:
        import demucs  # noqa: F401

        out["demucs"] = getattr(demucs, "__version__", "ok")
    except Exception:
        pass
    return out


# ────────────────────────── 执行工具 ──────────────────────────
def run(cmd: list[str], log, cwd: Path | None = None, timeout: int = 1800, env: dict | None = None) -> int:
    log("$ " + " ".join(str(c) for c in cmd[:6]) + (" …" if len(cmd) > 6 else ""))
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )
    except FileNotFoundError:
        log(f"✗ 找不到可执行文件:{cmd[0]}")
        return 127
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            line = line.strip()
            if line:
                log(line[:300])
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        log("✗ 超时,已终止")
        return 124


# ────────────────────────── 阶段 1:获取媒体 ──────────────────────────
def is_url(s: str) -> bool:
    return bool(re.match(r"^https?://", s.strip(), re.I))


def fetch_media(src: str, work: Path, log, cookies: str = "") -> Path:
    src = src.strip().strip('"')
    if not is_url(src):
        p = Path(src)
        if not p.is_file():
            raise RuntimeError(f"本地文件不存在:{src}")
        log(f"使用本地文件:{p.name}")
        dst = work / ("src" + p.suffix)
        shutil.copyfile(p, dst)
        return dst

    if not deps()["yt_dlp"]:
        raise RuntimeError("缺少 yt-dlp,无法下载。安装:pip install -U yt-dlp")

    cmd = [
        "yt-dlp",
        "-f",
        "bestaudio/best",
        "--no-playlist",
        "--no-warnings",
        "--newline",
        "-o",
        str(work / "src.%(ext)s"),
    ]
    if cookies:
        cmd += ["--cookies", cookies]
    cmd.append(src)

    code = run(cmd, log)
    hits = sorted(glob.glob(str(work / "src.*")))
    hits = [h for h in hits if not h.endswith(".part")]
    if code != 0 or not hits:
        raise RuntimeError(
            "下载失败。常见原因:需要登录(抖音/小红书请提供 cookies.txt)、地区限制、或链接不是视频页"
        )
    return Path(hits[0])


# ────────────────────────── 阶段 2:抽音轨 ──────────────────────────
def extract_audio(media: Path, out: Path, log) -> Path:
    ff = ffmpeg_path()
    if not ff:
        raise RuntimeError("缺少 ffmpeg")
    code = run(
        [ff, "-y", "-i", str(media), "-vn", "-ac", "1", "-ar", str(SR_TARGET), "-c:a", "pcm_s16le", str(out)],
        log,
    )
    if code != 0 or not out.is_file() or out.stat().st_size < 1024:
        raise RuntimeError("抽取音轨失败:文件里可能没有音频流")
    return out


# ────────────────────────── 阶段 3:人声分离 ──────────────────────────
def separate_vocals(wav: Path, work: Path, log) -> Path | None:
    d = deps()
    if not d["demucs"]:
        log("⚠ 未安装 demucs,跳过人声分离。带 BGM 的片段克隆效果会明显变差")
        return None

    import os
    import sys as _sys

    env = os.environ.copy()
    # demucs 4.1 从 HuggingFace 拉权重;直连在国内基本不通,默认走镜像
    env.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    device = "cuda" if d.get("cuda") else "cpu"
    log(f"人声分离中(设备 {device};首次运行需下载约 80MB 权重)…")
    code = run(
        [
            _sys.executable,
            "-m",
            "demucs",
            "--two-stems=vocals",
            "-n",
            "htdemucs",
            "-d",
            device,
            "-o",
            str(work / "stems"),
            str(wav),
        ],
        log,
        env=env,
    )
    hits = glob.glob(str(work / "stems" / "*" / "*" / "vocals.wav"))
    if code != 0 or not hits:
        log("⚠ 分离失败,回退到原始混音")
        return None
    return Path(sorted(hits, key=lambda p: -Path(p).stat().st_size)[0])


# ────────────────────────── 阶段 4:VAD 与切段 ──────────────────────────
def load_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        ch = w.getnchannels()
        sw = w.getsampwidth()
        raw = w.readframes(n)
    if sw != 2:
        raise RuntimeError(f"只支持 16-bit PCM,实际 {sw * 8} bit")
    sig = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if ch > 1:
        sig = sig.reshape(-1, ch).mean(axis=1)
    return sig, sr


def frame_rms(sig: np.ndarray, sr: int) -> np.ndarray:
    hop = int(sr * FRAME_MS / 1000)
    if hop < 1:
        return np.array([0.0])
    usable = len(sig) // hop * hop
    if usable == 0:
        return np.array([0.0])
    frames = sig[:usable].reshape(-1, hop)
    return np.sqrt((frames ** 2).mean(axis=1) + 1e-12)


def vad_segments(sig: np.ndarray, sr: int, strict: bool = True) -> list[tuple[float, float]]:
    rms = frame_rms(sig, sr)
    if not len(rms):
        return []
    floor = float(np.percentile(rms, 10))
    loud = float(np.percentile(rms, 90))
    if strict:
        thr = max(floor * 2.2, loud * 0.10, 0.0035)
    else:
        # 宽松模式:分离后音量常被压得很低,按相对阈值找
        thr = max(floor * 1.5, loud * 0.05, 0.0006)
    mask = rms > thr

    # 合并短空隙 / 去掉短促噪声
    min_speech = 0.30
    min_gap = 0.40
    hop_s = FRAME_MS / 1000.0
    segs: list[list[float]] = []
    start = None
    for i, on in enumerate(mask):
        t = i * hop_s
        if on and start is None:
            start = t
        elif not on and start is not None:
            segs.append([start, t])
            start = None
    if start is not None:
        segs.append([start, len(mask) * hop_s])

    merged: list[list[float]] = []
    for s, e in segs:
        if merged and s - merged[-1][1] < min_gap:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    return [(s, e) for s, e in merged if e - s >= min_speech]


def best_window(sig: np.ndarray, sr: int, start: float, end: float, target: float = 12.0) -> tuple[float, float]:
    dur = end - start
    if dur <= target:
        return start, end
    hop = int(sr * 0.25)
    seg = sig[int(start * sr) : int(end * sr)]
    win = int(target * sr)
    if len(seg) <= win:
        return start, end
    energy = np.convolve(seg ** 2, np.ones(win, dtype=np.float32), mode="valid")
    pos = int(np.argmax(energy[::hop]) * hop)
    pos = min(pos, len(seg) - win)
    return start + pos / sr, start + (pos + win) / sr


# ────────────────────────── 阶段 5:打分 ──────────────────────────
def score_clip(sig: np.ndarray, sr: int) -> dict:
    dur = len(sig) / sr
    peak = float(np.max(np.abs(sig))) if len(sig) else 0.0
    peak_db = 20 * np.log10(peak + 1e-9)
    clip_ratio = float((np.abs(sig) > 0.985).mean())
    silence = float((np.abs(sig) < 0.005).mean())
    rms = frame_rms(sig, sr)
    rms_std = float(np.std(rms) / (np.mean(rms) + 1e-9)) if len(rms) else 1.0

    problems, warnings = [], []
    score = 100.0

    if dur < 8:
        problems.append(f"时长 {dur:.1f}s < 8s")
        score -= 60
    elif dur < 10:
        warnings.append(f"时长 {dur:.1f}s 略短(建议 10–14s)")
        score -= 18
    elif dur > 15:
        problems.append(f"时长 {dur:.1f}s > 15s 硬上限")
        score -= 30

    if clip_ratio > 0.002:
        problems.append(f"削波 {clip_ratio*100:.2f}%")
        score -= 35
    if peak_db > -0.5:
        warnings.append(f"峰值 {peak_db:.1f} dBFS 偏高")
        score -= 8
    elif peak_db < -18:
        warnings.append(f"电平过低 {peak_db:.1f} dBFS")
        score -= 12

    if silence > 0.20:
        warnings.append(f"静音占 {silence*100:.0f}%")
        score -= 12
    if rms_std > 1.5:
        warnings.append("音量起伏大,可能有多人交替")
        score -= 10

    return {
        "duration": round(dur, 2),
        "peak_dbfs": round(peak_db, 1),
        "clip_ratio": round(clip_ratio * 100, 2),
        "silence_ratio": round(silence * 100, 1),
        "rms_variation": round(rms_std, 2),
        "score": round(max(score, 0), 1),
        "problems": problems,
        "warnings": warnings,
        "ok": not problems,
    }


def write_wav(path: Path, sig: np.ndarray, sr: int) -> None:
    data = np.clip(sig, -1, 1)
    pcm = (data * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def harvest(src: str, work: Path, log, cookies: str = "", separate: bool = True, max_candidates: int = 8) -> dict:
    work.mkdir(parents=True, exist_ok=True)
    d = deps()
    log(f"依赖:ffmpeg={'有' if d['ffmpeg'] else '无'} yt-dlp={'有' if d['yt_dlp'] else '无'} "
        f"demucs={'有' if d['demucs'] else '无'} cuda={'有' if d.get('cuda') else '无'}")

    log("① 获取媒体…")
    media = fetch_media(src, work, log)

    log("② 抽取音轨…")
    wav = extract_audio(media, work / "full.wav", log)

    log("③ 人声分离…")
    vocals = separate_vocals(wav, work, log) if separate else None
    if vocals is None:
        log("⚠ 使用原始混音作为分析源(可能含 BGM)")
    analysis_src = vocals or wav
    separated = vocals is not None

    log("④ 切分语音段…")
    sig, sr = load_wav(analysis_src)
    peak_db = 20 * np.log10(float(np.max(np.abs(sig))) + 1e-9) if len(sig) else -999
    log(f"   音频 {len(sig)/sr:.1f}s @ {sr}Hz,峰值 {peak_db:.1f} dBFS")
    segs = vad_segments(sig, sr, strict=True)
    if not segs:
        log("   严格阈值下无语音段,改用宽松阈值重试…")
        segs = vad_segments(sig, sr, strict=False)
    log(f"   检出 {len(segs)} 段 ≥0.3s 的语音")
    if not segs:
        if peak_db < -35:
            log(f"   ✗ 人声轨峰值仅 {peak_db:.1f} dBFS —— 可能是分离过度(原片以 BGM 为主),"
                f"或原片几乎没有人声。试试关掉分离、或换一段有人说话的素材")
        else:
            log("   ✗ 未找到连续语音段 —— 可能是喊叫/歌声/音乐,或全程多人抢话")

    log("⑤ 打分筛选…")
    cands = []
    for idx, (s, e) in enumerate(segs):
        s2, e2 = best_window(sig, sr, s, e)
        clip = sig[int(s2 * sr) : int(e2 * sr)]
        if len(clip) < int(3 * sr):
            continue
        info = score_clip(clip, sr)
        if info["duration"] < 8:
            continue
        out = work / f"cand_{idx:02d}.wav"
        write_wav(out, clip, sr)
        info.update(
            {
                "index": len(cands),
                "file": out.name,
                "start": round(s2, 2),
                "end": round(e2, 2),
                "separated": separated,
            }
        )
        cands.append(info)

    cands.sort(key=lambda c: (c["ok"], c["score"]), reverse=True)
    cands = cands[:max_candidates]
    for i, c in enumerate(cands):
        c["index"] = i

    (work / "candidates.json").write_text(json.dumps(cands, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"   完成:{len(cands)} 个候选")
    if not cands:
        log("✗ 没有达标片段。可能原因:整段都是 BGM、说话太短、或需要登录才能拿到原片")
    return {"candidates": cands, "separated": separated, "duration": round(len(sig) / sr, 1)}
