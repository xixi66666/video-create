"""受控素材目录的只读工具；默认关闭，媒体探测使用受限的本机 FFmpeg。"""
import hashlib
import io
import json
import math
import os
import re
import shutil
import stat
import struct
import subprocess
import threading
import wave
import zlib
from pathlib import Path

from langchain_core.tools import tool

MAX_BYTES = 64 * 1024 * 1024
MAX_PROCESS_OUTPUT = 2 * 1024 * 1024
PROCESS_TIMEOUT_SECONDS = 30
MAX_AUDIO_SECONDS = 120


def _run_media_program(executable, args, data):
    """只将已验证的文件内容送入 stdin，禁止子进程通过协议读取路径或网络。"""
    configured = os.getenv("CREATOR_FFMPEG_PATH" if executable == "ffmpeg" else "CREATOR_FFPROBE_PATH")
    local_name = executable + (".exe" if os.name == "nt" else "")
    local_binary = Path(__file__).resolve().parents[1] / "data" / "media-tools" / local_name
    path = shutil.which(configured or (str(local_binary) if local_binary.is_file() else executable))
    if not path:
        raise ValueError(f"未安装 {executable}，请配置受信任的 FFmpeg 工具")
    try:
        process = subprocess.Popen(
            [path, *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), shell=False)
    except OSError:
        raise ValueError(f"无法启动 {executable}") from None
    output = {"stdout": bytearray(), "stderr": bytearray()}
    exceeded = threading.Event()

    def read_pipe(stream, name):
        try:
            while True:
                chunk = stream.read(16384)
                if not chunk:
                    break
                if len(output[name]) + len(chunk) > MAX_PROCESS_OUTPUT:
                    exceeded.set()
                    process.kill()
                    break
                output[name].extend(chunk)
        except (OSError, ValueError):
            pass

    def write_input():
        try:
            process.stdin.write(data)
        except (OSError, ValueError):
            pass
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass

    threads = [threading.Thread(target=read_pipe, args=(process.stdout, "stdout"), daemon=True),
               threading.Thread(target=read_pipe, args=(process.stderr, "stderr"), daemon=True),
               threading.Thread(target=write_input, daemon=True)]
    for thread in threads:
        thread.start()
    try:
        process.wait(timeout=PROCESS_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        raise ValueError("媒体探测超时；未完成分析") from None
    finally:
        for thread in threads:
            thread.join(timeout=2)
    if exceeded.is_set():
        raise ValueError("媒体探测输出超过限制")
    if process.returncode:
        raise ValueError("媒体格式无法探测或解码；未完成分析")
    return bytes(output["stdout"]), bytes(output["stderr"])


def _probe(data):
    raw, _ = _run_media_program("ffprobe", ["-v", "error", "-protocol_whitelist", "pipe",
        "-show_entries", "format=format_name,duration,size,bit_rate:stream=index,codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,duration,sample_rate,channels,channel_layout,bit_rate",
        "-of", "json", "pipe:0"], data)
    try:
        result = json.loads(raw)
        if not isinstance(result, dict) or not isinstance(result.get("streams", []), list):
            raise ValueError
        return result
    except (ValueError, UnicodeError):
        raise ValueError("媒体探测结果无效") from None


def _loudness(data):
    _, raw = _run_media_program("ffmpeg", ["-hide_banner", "-nostats", "-v", "info",
        "-protocol_whitelist", "pipe", "-i", "pipe:0", "-t", str(MAX_AUDIO_SECONDS),
        "-map", "0:a:0", "-vn", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
        "-f", "null", "-"], data)
    text = raw.decode("utf-8", "replace")
    matches = re.findall(r"\{[^{}]*\}", text, re.DOTALL)
    try:
        obj = json.loads(matches[-1])
        values = {"integratedLufs": float(obj["input_i"]), "truePeakDbtp": float(obj["input_tp"]),
                  "loudnessRangeLu": float(obj["input_lra"])}
        if not all(math.isfinite(v) for v in values.values()):
            raise ValueError
    except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise ValueError("响度测量无有效结果，可能是静音、无音轨或格式不支持") from None
    return {**values, "method": "FFmpeg loudnorm / EBU R128", "maxAnalyzedSeconds": MAX_AUDIO_SECONDS,
            "note": "最多分析前 120 秒的第一条音轨；不代表已试听或通过音质验收。"}


def _windows_final_path(fd):
    """获取已打开句柄的目标路径，避免检查路径后再打开的竞态。"""
    import ctypes
    import msvcrt
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_path = kernel32.GetFinalPathNameByHandleW
    get_path.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    get_path.restype = wintypes.DWORD
    handle = msvcrt.get_osfhandle(fd)
    size = get_path(handle, None, 0, 0)
    if not size or size > 32768:
        raise ValueError("无法验证素材文件句柄")
    buf = ctypes.create_unicode_buffer(size + 1)
    if not get_path(handle, buf, len(buf), 0):
        raise ValueError("无法验证素材文件句柄")
    value = buf.value
    if value.startswith("\\\\?\\UNC\\"):
        return "\\\\" + value[8:]
    return value[4:] if value.startswith("\\\\?\\") else value


def _read_local(root, name):
    # 仅支持平铺文件，禁止绝对路径、相对组件、ADS 和 Windows 设备名。
    if (not isinstance(name, str) or not name or len(name) > 240 or name in {".", ".."}
            or any(c in name for c in "/\\:\x00") or name.rstrip(". ") != name):
        raise ValueError("素材名称无效")
    stem = name.split(".", 1)[0].upper()
    if stem in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        raise ValueError("素材名称无效")
    try:
        root = Path(root)
        root_stat = root.stat(follow_symlinks=False)
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if (not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode)
                or getattr(root_stat, "st_file_attributes", 0) & reparse):
            raise ValueError("素材目录不可用")
        canonical_root = root.resolve(strict=True)
        if os.path.normcase(str(canonical_root)) != os.path.normcase(os.path.abspath(root)):
            raise ValueError("素材目录路径不得包含链接或重解析点")
        # Windows 无 O_NOFOLLOW，检查目录项和已打开句柄的目标路径。
        entry_stat = (canonical_root / name).stat(follow_symlinks=False)
        if not stat.S_ISREG(entry_stat.st_mode) or getattr(entry_stat, "st_file_attributes", 0) & reparse:
            raise ValueError("不允许链接或重解析点")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(canonical_root / name, flags)
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > MAX_BYTES:
                raise ValueError("素材不是普通文件或超过大小限制")
            if os.name == "nt":
                final = Path(_windows_final_path(fd))
                if os.path.normcase(str(final)) != os.path.normcase(str(canonical_root / name)):
                    raise ValueError("素材文件目标不在指定位置")
            elif Path("/proc/self/fd").exists():
                actual = Path(os.readlink(f"/proc/self/fd/{fd}"))
                if actual != canonical_root / name:
                    raise ValueError("素材文件目标不在指定位置")
            with os.fdopen(fd, "rb", closefd=False) as f:
                data = f.read(MAX_BYTES + 1)
            after = os.fstat(fd)
            if len(data) > MAX_BYTES:
                raise ValueError("素材超过大小限制")
            # 检测读取期间发生的常见文件变化，不能防止有权限者刻意伪造时间戳。
            if (st.st_size, st.st_mtime_ns, st.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns) or len(data) != after.st_size:
                raise ValueError("读取期间素材发生变化，请重试")
            return data
        finally:
            os.close(fd)
    except ValueError:
        raise
    except (OSError, RuntimeError):
        # 不回传系统路径、环境变量或底层异常。
        raise ValueError("素材不可读取或目录不可用") from None


def make_local_media_tools(root=None, enabled=False):
    """显式启用并配置专用素材目录才注册工具；目录需由管理员管理。"""
    if not enabled or not root:
        return []

    @tool
    def local_sha256(filename: str) -> dict:
        """计算受控素材目录中单个普通文件的 SHA-256；filename 只能是文件名，不支持路径。"""
        data = _read_local(root, filename)
        return {"filename": filename, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "method": "SHA-256"}

    @tool
    def inspect_local_media(filename: str, include_loudness: bool = False) -> dict:
        """探测受控目录中的媒体元数据；可选测前 120 秒首音轨的响度和真峰值。"
        "文件名不含路径。仅元数据和信号测量，不代表试听、视觉识别或内容验收。"""
        data = _read_local(root, filename)
        sha256 = hashlib.sha256(data).hexdigest()
        result = {"filename": filename, "sha256": sha256}
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            if (len(data) < 33 or data[8:12] != b"\x00\x00\x00\r" or data[12:16] != b"IHDR"
                    or zlib.crc32(data[12:29]) != int.from_bytes(data[29:33], "big")):
                raise ValueError("PNG 头无效")
            width, height, depth, color = struct.unpack(">IIBB", data[16:26])
            if width == 0 or height == 0:
                raise ValueError("PNG 尺寸无效")
            result.update(format="PNG", width=width, height=height, bitDepth=depth, colorType=color,
                          note="解析 PNG 头，未验证完整文件或图像内容。")
        elif data[:4] == b"RIFF" and data[8:12] == b"WAVE":
            try:
                with wave.open(io.BytesIO(data), "rb") as f:
                    channels, sample_rate, sample_width, frames = f.getnchannels(), f.getframerate(), f.getsampwidth(), f.getnframes()
                    if sample_rate <= 0:
                        raise ValueError("WAV 采样率无效")
                    result.update(format="WAV", channels=channels, sampleRateHz=sample_rate,
                                  sampleWidthBytes=sample_width, frames=frames, durationSeconds=frames / sample_rate,
                                  note="读取 WAV 头；未验证整段音频或音质。")
            except (wave.Error, EOFError, OSError):
                raise ValueError("WAV 头无效或格式不支持") from None
        try:
            result["probe"] = _probe(data)
            result["probeMethod"] = "ffprobe"
            result["note"] = "已探测容器与流元数据；未验证全部内容，不代表视觉、试听或质量验收。"
        except ValueError as exc:
            if "format" not in result:
                raise
            result["probeUnavailable"] = str(exc)
        if include_loudness:
            result["loudness"] = _loudness(data)
        return result

    return [local_sha256, inspect_local_media]
