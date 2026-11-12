"""远端声音角色库：角色和音频在数据库事务中保存。"""
import hashlib
import json
import os
import ssl
from pathlib import Path

import pymysql
from fastapi import HTTPException

MAX_AUDIO = 12 * 1024 * 1024


def enabled():
    return any(os.getenv(key) for key in ("CREATOR_VOICE_DB_HOST", "CREATOR_VOICE_DB_USER",
                                           "CREATOR_VOICE_DB_PASSWORD", "CREATOR_VOICE_DB_NAME"))


def connect():
    required = ["CREATOR_VOICE_DB_HOST", "CREATOR_VOICE_DB_USER", "CREATOR_VOICE_DB_PASSWORD", "CREATOR_VOICE_DB_NAME"]
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise HTTPException(503, "声音数据库配置不完整：" + "、".join(missing))
    try:
        ca = os.getenv("CREATOR_VOICE_DB_SSL_CA")
        tls = {"ca": ca, "check_hostname": True, "verify_mode": True} if ca else {"check_hostname": False, "verify_mode": False}
        db = pymysql.connect(host=os.environ[required[0]], user=os.environ[required[1]],
                               password=os.environ[required[2]], database=os.environ[required[3]],
                               port=int(os.getenv("CREATOR_VOICE_DB_PORT", "3306")),
                               charset="utf8mb4", connect_timeout=8, read_timeout=30, write_timeout=30,
                               cursorclass=pymysql.cursors.DictCursor, autocommit=False, ssl=tls)
        if not isinstance(db._sock, ssl.SSLSocket):
            db.close()
            raise HTTPException(503, "声音数据库没有启用 TLS 加密")
        return db
    except (pymysql.MySQLError, ValueError):
        raise HTTPException(503, "声音数据库连接失败，请检查本机连接配置") from None


def parse_manifest(row):
    manifest = json.loads(row["manifest_json"])
    if manifest.get("character_id") != row["character_id"]:
        raise HTTPException(500, "声音角色记录不一致")
    return manifest


def list_roles():
    with connect() as db:
        with db.cursor() as cur:
            cur.execute("SELECT character_id,name,version,selected_candidate,manifest_json FROM voice_character ORDER BY created_at,character_id")
            records = cur.fetchall()
            cur.execute("SELECT character_id,file_name FROM voice_audio WHERE kind=%s ORDER BY file_name", ("sample",))
            samples = cur.fetchall()
    by_role = {}
    for sample in samples:
        by_role.setdefault(sample["character_id"], []).append({"file": sample["file_name"]})
    return [{"id": r["character_id"], "name": r["name"], "version": r["version"],
             "selected": r["selected_candidate"], "clips": parse_manifest(r).get("clips", []),
             "samples": by_role.get(r["character_id"], [])} for r in records]


def get_record(db, role_id, lock=False):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM voice_character WHERE character_id=%s" + (" FOR UPDATE" if lock else ""), (role_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "声音角色不存在")
    return row


def get_audio(db, role_id, name):
    with db.cursor() as cur:
        cur.execute("SELECT content,sha256 FROM voice_audio WHERE character_id=%s AND file_name=%s", (role_id, name))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "音频文件不存在")
    raw = bytes(row["content"])
    if hashlib.sha256(raw).hexdigest() != row["sha256"]:
        raise HTTPException(500, "音频校验失败")
    return raw


def insert_audio(cur, role_id, name, kind, raw):
    if len(raw) > MAX_AUDIO:
        raise ValueError("音频超过 12 MB，请选择较短片段")
    cur.execute("INSERT INTO voice_audio(character_id,file_name,kind,byte_size,sha256,content) VALUES(%s,%s,%s,%s,%s,%s)",
                (role_id, name, kind, len(raw), hashlib.sha256(raw).hexdigest(), raw))


def import_role(role):
    """只添加不存在的角色，所有文件在一笔事务中提交。"""
    role = Path(role)
    manifest = json.loads((role / "manifest.json").read_text(encoding="utf-8"))
    role_id = role.name
    if manifest.get("character_id") != role_id:
        raise ValueError("角色目录和清单不一致")
    card_path = role / "character.json"
    card = json.loads(card_path.read_text(encoding="utf-8")) if card_path.exists() else None
    if card and card.get("character_id") != role_id:
        raise ValueError("角色卡与目录不一致")
    files = []
    for number, clip in enumerate(manifest.get("clips", []), 1):
        for kind in ("original", "vocals"):
            filename = f"{number:02}-{kind}.wav"
            if clip.get(kind) != filename:
                raise ValueError("候选文件记录无效")
            raw = (role / filename).read_bytes()
            if kind == "vocals" and hashlib.sha1(raw).hexdigest() != clip.get("sha1"):
                raise ValueError("参考音频指纹不一致")
            files.append((filename, kind, raw))
    if card:
        index = card.get("candidate")
        if not isinstance(index, int) or not 1 <= index <= len(manifest["clips"]):
            raise ValueError("已选候选无效")
        selected = manifest["clips"][index - 1]
        if card.get("reference") != selected["vocals"] or card.get("sha1") != selected["sha1"]:
            raise ValueError("角色卡与参考样本不一致")
    samples = role / "samples"
    if samples.is_dir():
        for file in sorted(samples.glob("*.wav")):
            if file.is_file() and file.resolve().parent == samples.resolve() and len(file.name) <= 191:
                files.append((file.name, "sample", file.read_bytes()))
    name = card.get("name", role_id) if card else manifest.get("name", role_id)
    with connect() as db:
        try:
            with db.cursor() as cur:
                cur.execute("INSERT INTO voice_character(character_id,name,version,selected_candidate,manifest_json) VALUES(%s,%s,%s,%s,%s)",
                            (role_id, name, card.get("version") if card else None,
                             card.get("candidate") if card else None, json.dumps(manifest, ensure_ascii=False)))
                for file_name, kind, raw in files:
                    insert_audio(cur, role_id, file_name, kind, raw)
            db.commit()
        except pymysql.err.IntegrityError:
            db.rollback()
            raise HTTPException(409, "角色 ID 已存在，未覆盖远端角色") from None
        except Exception:
            db.rollback()
            raise


def rename(role_id, name):
    with connect() as db:
        try:
            row = get_record(db, role_id, lock=True)
            with db.cursor() as cur:
                cur.execute("UPDATE voice_character SET name=%s,revision=revision+1 WHERE character_id=%s", (name, role_id))
            db.commit()
        except Exception:
            db.rollback()
            raise
    return {"id": role_id, "name": name}


def select(role_id, number, name):
    with connect() as db:
        try:
            row = get_record(db, role_id, lock=True)
            manifest = parse_manifest(row)
            clips = manifest.get("clips", [])
            if not 1 <= number <= len(clips):
                raise HTTPException(400, "候选编号无效")
            clip = clips[number - 1]
            if row["selected_candidate"] is not None:
                if row["selected_candidate"] == number and row["name"] == name:
                    return
                raise HTTPException(409, "角色已定档")
            raw = get_audio(db, role_id, f"{number:02}-vocals.wav")
            if hashlib.sha1(raw).hexdigest() != clip.get("sha1"):
                raise HTTPException(409, "参考音频指纹不一致")
            with db.cursor() as cur:
                cur.execute("UPDATE voice_character SET name=%s,version=%s,selected_candidate=%s,revision=revision+1 WHERE character_id=%s",
                            (name, "1.0.0", number, role_id))
            db.commit()
        except Exception:
            db.rollback()
            raise


def materialize(role_id, library):
    """下载角色必要文件到独立临时工作区，供原有合成引擎使用。"""
    with connect() as db:
        row = get_record(db, role_id)
        manifest = parse_manifest(row)
        number = row["selected_candidate"]
        if not number:
            raise HTTPException(400, "请先选择参考音频")
        clip = manifest["clips"][number - 1]
        if clip.get("vocals") != f"{number:02}-vocals.wav":
            raise HTTPException(409, "参考音频文件名不匹配")
        raw = get_audio(db, role_id, f"{number:02}-vocals.wav")
    if hashlib.sha1(raw).hexdigest() != clip["sha1"]:
        raise HTTPException(409, "参考音频指纹不一致")
    role = Path(library) / role_id
    role.mkdir()
    (role / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    card = {"character_id": role_id, "name": row["name"], "version": row["version"],
            "candidate": number, "reference": clip["vocals"], "sha1": clip["sha1"]}
    (role / "character.json").write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
    (role / clip["vocals"]).write_bytes(raw)
    (role / "samples").mkdir()
    return role


def save_sample(role_id, filename, raw):
    with connect() as db:
        try:
            get_record(db, role_id, lock=True)
            with db.cursor() as cur:
                insert_audio(cur, role_id, filename, "sample", raw)
            db.commit()
        except Exception:
            db.rollback()
            raise
