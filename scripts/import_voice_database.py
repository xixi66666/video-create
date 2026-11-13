"""初始化声音库表并把已定档的本地角色迁入共享数据库。凭据只从进程环境读取。"""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent-runtime"))
from app import voice_database
from app.local_voice_config import load


def initialize():
    schema = (ROOT / "docs" / "sql" / "003_voice_library.sql").read_text(encoding="utf-8")
    with voice_database.connect() as db:
        with db.cursor() as cur:
            cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN (%s,%s)",
                        ("voice_character", "voice_audio"))
            existing = [r["table_name"] for r in cur.fetchall()]
            if existing:
                raise RuntimeError("数据库已有声音表，请先核对结构，不自动覆盖：" + ", ".join(existing))
            for statement in schema.split(";"):
                if statement.strip():
                    cur.execute(statement)
        db.commit()
    print("声音库表已创建")


def main():
    load(include_mimo=False)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--init", action="store_true", help="仅在声音表都不存在时创建")
    parser.add_argument("--role", type=Path, help="本地角色目录")
    args = parser.parse_args()
    if not args.init and not args.role:
        parser.error("请指定 --init 或 --role")
    if args.init:
        initialize()
    if args.role:
        role = args.role.expanduser().resolve(strict=True)
        if not role.is_dir():
            raise ValueError("角色路径必须为目录")
        voice_database.import_role(role)
        print("角色已迁入共享数据库：" + role.name)


if __name__ == "__main__":
    main()
