import hashlib
import json
import os
import struct
import sys
import wave
import zlib
import pytest
from app import local_media_tools as local


def lookup(root):
    return {t.name: t for t in local.make_local_media_tools(root, enabled=True)}


def test_disabled_and_hash_real_file(tmp_path):
    assert local.make_local_media_tools(tmp_path) == []
    assert local.make_local_media_tools(None, enabled=True) == []
    (tmp_path / "素材.txt").write_bytes(b"abc")
    result = lookup(tmp_path)["local_sha256"].invoke({"filename": "素材.txt"})
    assert result["sha256"] == hashlib.sha256(b"abc").hexdigest()
    assert result["bytes"] == 3


def test_wav_and_png_real_headers(tmp_path):
    with wave.open(str(tmp_path / "tone.wav"), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(b"\x00\x00" * 800)
    header = b"IHDR" + struct.pack(">IIBBBBB", 16, 9, 8, 2, 0, 0, 0)
    (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + header + struct.pack(">I", zlib.crc32(header)))
    inspect = lookup(tmp_path)["inspect_local_media"]
    audio = inspect.invoke({"filename": "tone.wav"})
    assert (audio["sampleRateHz"], audio["channels"], audio["durationSeconds"]) == (8000, 1, .1)
    assert "未验证" in audio["note"]
    image = inspect.invoke({"filename": "image.png"})
    assert (image["width"], image["height"]) == (16, 9)
    (tmp_path / "bad.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 30)
    with pytest.raises(ValueError, match="PNG 头无效"):
        inspect.invoke({"filename": "bad.png"})


def test_paths_symlinks_limits_and_redacted_errors(tmp_path, monkeypatch):
    sha = lookup(tmp_path)["local_sha256"]
    for name in ("../secret", "a/b", "C:\\secret", "x:stream", "NUL.txt", "x.", ""):
        with pytest.raises(ValueError):
            sha.invoke({"filename": name})
    secret = tmp_path.parent / (tmp_path.name + "-secret.txt")
    secret.write_bytes(b"private")
    try:
        (tmp_path / "link").symlink_to(secret)
    except OSError:
        pass
    else:
        with pytest.raises(ValueError):
            sha.invoke({"filename": "link"})
    monkeypatch.setattr(local, "MAX_BYTES", 2)
    (tmp_path / "large").write_bytes(b"abc")
    with pytest.raises(ValueError, match="大小"):
        sha.invoke({"filename": "large"})
    with pytest.raises(ValueError) as e:
        sha.invoke({"filename": "missing"})
    assert str(tmp_path) not in str(e.value)


def test_detect_change_during_read(tmp_path, monkeypatch):
    path = tmp_path / "a"
    path.write_bytes(b"abc")
    old_fstat = local.os.fstat
    calls = 0
    def changing(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            path.write_bytes(b"changed")
        return old_fstat(fd)
    monkeypatch.setattr(local.os, "fstat", changing)
    with pytest.raises(ValueError, match="发生变化"):
        lookup(tmp_path)["local_sha256"].invoke({"filename": "a"})


def test_growth_cannot_exceed_read_limit(tmp_path, monkeypatch):
    path = tmp_path / "a"
    path.write_bytes(b"a")
    old_fstat = local.os.fstat
    calls = 0
    def growing(fd):
        nonlocal calls
        calls += 1
        result = old_fstat(fd)
        if calls == 1:
            path.write_bytes(b"longer")
        return result
    monkeypatch.setattr(local, "MAX_BYTES", 2)
    monkeypatch.setattr(local.os, "fstat", growing)
    with pytest.raises(ValueError, match="大小"):
        lookup(tmp_path)["local_sha256"].invoke({"filename": "a"})


def test_hardlink_is_rejected(tmp_path):
    original = tmp_path.parent / (tmp_path.name + "-original")
    original.write_bytes(b"private")
    try:
        os.link(original, tmp_path / "linked")
    except OSError:
        pytest.skip("硬链接不可用")
    with pytest.raises(ValueError):
        lookup(tmp_path)["local_sha256"].invoke({"filename": "linked"})


def test_windows_handle_target_is_checked(tmp_path, monkeypatch):
    if os.name != "nt":
        pytest.skip("Windows handle test")
    (tmp_path / "a").write_bytes(b"abc")
    monkeypatch.setattr(local, "_windows_final_path", lambda fd: str(tmp_path.parent / "outside"))
    with pytest.raises(ValueError, match="指定位置"):
        lookup(tmp_path)["local_sha256"].invoke({"filename": "a"})


def test_ffprobe_metadata_and_loudness_use_only_pipe(tmp_path, monkeypatch):
    (tmp_path / "clip.mp4").write_bytes(b"virtual media bytes")
    seen = []
    def fake_program(name, args, data):
        seen.append((name, args, data))
        assert args[args.index("-protocol_whitelist") + 1] == "pipe"
        assert "pipe:0" in args
        assert data == b"virtual media bytes"
        if name == "ffprobe":
            return json.dumps({"format": {"duration": "12.5", "bit_rate": "900000"},
                               "streams": [{"codec_type": "video", "width": 1920, "height": 1080,
                                            "avg_frame_rate": "30/1"}, {"codec_type": "audio"}]}).encode(), b""
        return b"", b'log\n{"input_i":"-18.2","input_tp":"-1.3","input_lra":"4.0"}\n'
    monkeypatch.setattr(local, "_run_media_program", fake_program)
    result = lookup(tmp_path)["inspect_local_media"].invoke({"filename": "clip.mp4", "include_loudness": True})
    assert result["probe"]["streams"][0]["width"] == 1920
    assert result["probe"]["streams"][0]["avg_frame_rate"] == "30/1"
    assert result["loudness"]["integratedLufs"] == -18.2
    assert result["loudness"]["truePeakDbtp"] == -1.3
    assert result["loudness"]["maxAnalyzedSeconds"] == 120
    assert [item[0] for item in seen] == ["ffprobe", "ffmpeg"]
    assert seen[1][1][seen[1][1].index("-t") + 1] == "120"


def test_unknown_media_requires_probe_and_invalid_loudness_is_not_a_number(tmp_path, monkeypatch):
    (tmp_path / "clip.webp").write_bytes(b"not a real webp")
    monkeypatch.setattr(local, "_run_media_program", lambda *args: (_ for _ in ()).throw(ValueError("未安装 ffprobe")))
    with pytest.raises(ValueError, match="未安装"):
        lookup(tmp_path)["inspect_local_media"].invoke({"filename": "clip.webp"})
    monkeypatch.setattr(local, "_run_media_program", lambda *args: (b"", b'{"input_i":"-inf","input_tp":"-inf","input_lra":"0"}'))
    with pytest.raises(ValueError, match="无有效结果"):
        local._loudness(b"silent audio")


def test_media_subprocess_output_and_time_are_bounded(monkeypatch):
    monkeypatch.setattr(local.shutil, "which", lambda _: sys.executable)
    monkeypatch.setattr(local, "MAX_PROCESS_OUTPUT", 1000)
    with pytest.raises(ValueError, match="输出超过限制"):
        local._run_media_program("ffprobe", ["-c", "import sys;sys.stdout.write('x'*100000)"], b"")
    monkeypatch.setattr(local, "PROCESS_TIMEOUT_SECONDS", .3)
    with pytest.raises(ValueError, match="超时"):
        local._run_media_program("ffprobe", ["-c", "import time;time.sleep(5)"], b"")


def test_real_ffmpeg_formats_and_audio_signal(tmp_path):
    """安装 FFmpeg 时生成无版权的测试媒体，验证真实元数据与响度链路。"""
    import math
    import shutil
    import subprocess
    local_dir = local.Path(local.__file__).resolve().parents[1] / "data" / "media-tools"
    suffix = ".exe" if os.name == "nt" else ""
    ffmpeg = os.getenv("CREATOR_FFMPEG_PATH") or (str(local_dir / ("ffmpeg" + suffix)) if (local_dir / ("ffmpeg" + suffix)).is_file() else "ffmpeg")
    ffprobe = os.getenv("CREATOR_FFPROBE_PATH") or (str(local_dir / ("ffprobe" + suffix)) if (local_dir / ("ffprobe" + suffix)).is_file() else "ffprobe")
    if not shutil.which(ffmpeg) or not shutil.which(ffprobe):
        pytest.skip("FFmpeg / ffprobe 不可用")
    with wave.open(str(tmp_path / "tone.wav"), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(48000)
        out.writeframes(b"".join(struct.pack("<h", round(10000 * math.sin(2 * math.pi * 1000 * i / 48000))) for i in range(48000)))
    media = tmp_path / "clip.mp4"
    subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=160x90:r=25:d=1",
                    "-i", str(tmp_path / "tone.wav"), "-c:v", "mpeg4", "-c:a", "aac", "-movflags", "+faststart",
                    "-y", str(media)], check=True, capture_output=True, timeout=30)
    tool = lookup(tmp_path)["inspect_local_media"]
    result = tool.invoke({"filename": media.name, "include_loudness": True})
    streams = result["probe"]["streams"]
    video = next(s for s in streams if s["codec_type"] == "video")
    assert (video["width"], video["height"], video["avg_frame_rate"]) == (160, 90, "25/1")
    assert any(s["codec_type"] == "audio" for s in streams)
    assert -40 < result["loudness"]["integratedLufs"] < 0
    assert -30 < result["loudness"]["truePeakDbtp"] < 0
    webm = tmp_path / "clip.webm"
    subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=160x90:r=25:d=1",
                    "-i", str(tmp_path / "tone.wav"), "-c:v", "libvpx", "-c:a", "libopus",
                    "-y", str(webm)], check=True, capture_output=True, timeout=30)
    webm_result = tool.invoke({"filename": webm.name})
    assert any(s["codec_type"] == "video" and s["width"] == 160 for s in webm_result["probe"]["streams"])
    for extension in ("jpg", "webp"):
        image = tmp_path / ("sample." + extension)
        subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=160x90",
                        "-frames:v", "1", "-y", str(image)], check=True, capture_output=True, timeout=30)
        img = tool.invoke({"filename": image.name})
        stream = next(s for s in img["probe"]["streams"] if s["codec_type"] == "video")
        assert (stream["width"], stream["height"]) == (160, 90)
