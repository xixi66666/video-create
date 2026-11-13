"""读取本机声音配置，并从当前 Windows 用户的凭据管理器获取密钥。"""
import ctypes
import json
import os
from pathlib import Path
import threading


CONFIG_PATH = Path(__file__).resolve().parents[2] / "model.local"
_LOAD_LOCK = threading.Lock()


def read_credential(target):
    if os.name != "nt":
        raise ValueError("本机声音配置使用 Windows 凭据管理器，请通过环境变量提供凭据")

    class Credential(ctypes.Structure):
        _fields_ = [("flags", ctypes.c_uint32), ("type", ctypes.c_uint32),
                    ("target_name", ctypes.c_void_p), ("comment", ctypes.c_void_p),
                    ("last_written", ctypes.c_uint64), ("blob_size", ctypes.c_uint32),
                    ("blob", ctypes.c_void_p), ("persist", ctypes.c_uint32),
                    ("attribute_count", ctypes.c_uint32), ("attributes", ctypes.c_void_p),
                    ("target_alias", ctypes.c_void_p), ("user_name", ctypes.c_void_p)]

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi.CredReadW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                 ctypes.POINTER(ctypes.POINTER(Credential))]
    advapi.CredReadW.restype = ctypes.c_int
    advapi.CredFree.argtypes = [ctypes.c_void_p]
    pointer = ctypes.POINTER(Credential)()
    if not advapi.CredReadW(target, 1, 0, ctypes.byref(pointer)):
        raise ValueError("无法读取本机声音配置中的 Windows 凭据，请检查凭据管理器")
    try:
        item = pointer.contents
        if not item.blob or not item.blob_size or item.blob_size % 2:
            raise ValueError("本机声音凭据为空或格式无效")
        secret = ctypes.wstring_at(item.blob, item.blob_size // 2).rstrip("\0")
        username = ctypes.wstring_at(item.user_name) if item.user_name else ""
        return secret, username
    finally:
        advapi.CredFree(pointer)


def load(*, include_database=True, include_mimo=True):
    """显式环境变量优先；没有本地文件时保留原有行为。"""
    with _LOAD_LOCK:
        _load(include_database=include_database, include_mimo=include_mimo)


def _load(*, include_database, include_mimo):
    if not CONFIG_PATH.exists():
        return
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
        voice = config.get("voice", {})
        if not isinstance(voice, dict):
            raise ValueError("voice 必须是对象")
        database = voice.get("database") if include_database else None
        if database is not None:
            if not isinstance(database, dict):
                raise ValueError("voice.database 必须是对象")
            db_keys = ("CREATOR_VOICE_DB_HOST", "CREATOR_VOICE_DB_PORT", "CREATOR_VOICE_DB_NAME",
                       "CREATOR_VOICE_DB_USER", "CREATOR_VOICE_DB_PASSWORD")
            # 一旦显式提供数据库环境变量，整组都由调用者提供，避免混用不同数据库的凭据。
            if not any(os.getenv(k) for k in db_keys):
                host, name, target = (database[k] for k in ("host", "name", "passwordCredential"))
                port = int(database.get("port", 3306))
                if not all(isinstance(v, str) and v.strip() for v in (host, name, target)) or not 1 <= port <= 65535:
                    raise ValueError("数据库配置不完整")
                password, user = read_credential(target)
                if not user or not password:
                    raise ValueError("数据库凭据缺少用户名或密码")
                values = dict(zip(db_keys, (host, str(port), name, user, password)))
                if database.get("sslCa"):
                    values["CREATOR_VOICE_DB_SSL_CA"] = database["sslCa"]
                os.environ.update(values)
        mimo = voice.get("mimo") if include_mimo else None
        if mimo is not None:
            if not isinstance(mimo, dict):
                raise ValueError("voice.mimo 必须是对象")
            model = mimo.get("model", "mimo-v2.5-tts-voiceclone")
            if not isinstance(model, str) or not model.strip():
                raise ValueError("MiMo 模型名称无效")
            if not os.getenv("MIMO_API_KEY"):
                target = mimo.get("apiKeyCredential")
                if not isinstance(target, str) or not target.strip():
                    raise ValueError("MiMo 凭据引用无效")
                key, _ = read_credential(target)
                if not key:
                    raise ValueError("MiMo 凭据为空")
                os.environ["MIMO_API_KEY"] = key
            os.environ.setdefault("CREATOR_MIMO_VOICECLONE_MODEL", model)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise ValueError("本机 model.local 声音配置无效或凭据不可读取，请检查本地配置和 Windows 凭据管理器") from None
