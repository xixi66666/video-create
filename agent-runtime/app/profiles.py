import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "profiles"


def skill_path(profile):
    """从快照的 Skill 名称生成路径；保留旧运行的原始名称和内容。"""
    match = re.search(r"(?m)^name: ([a-z0-9]+(?:-[a-z0-9]+)*)\s*$", profile["skill"])
    if not match:
        raise ValueError("Skill 名称不符合 Agent Skills 规范")
    return f"/skills/{match.group(1)}/SKILL.md"


def load_profiles():
    profiles = {}
    for directory in sorted(ROOT.iterdir()):
        if not directory.is_dir():
            continue
        item = json.loads((directory / "profile.json").read_text(encoding="utf-8"))
        item.update(skill=(directory / "SKILL.md").read_text(encoding="utf-8"),
                    knowledge=(directory / "knowledge.md").read_text(encoding="utf-8"),
                    prompt=(directory / "prompt.md").read_text(encoding="utf-8"))
        item["sha256"] = hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
        profiles[item["id"]] = item
    return profiles
