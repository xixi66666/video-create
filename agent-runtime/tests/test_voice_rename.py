import json

import pytest
from fastapi import HTTPException

from app import voice_console


def test_rename_preserves_reference_and_role_version(tmp_path, monkeypatch):
    monkeypatch.setattr(voice_console, "LIBRARY", tmp_path)
    role = tmp_path / "narrator_one"
    role.mkdir()
    manifest = {"character_id": "narrator_one", "clips": [{"vocals": "01-vocals.wav", "sha1": "fingerprint"}]}
    card = {"character_id": "narrator_one", "name": "旧名称", "version": "1.0.0", "candidate": 1,
            "reference": "01-vocals.wav", "sha1": "fingerprint"}
    (role / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (role / "character.json").write_text(json.dumps(card), encoding="utf-8")
    result = voice_console.action({"action": "rename", "role": "narrator_one", "name": " 新名称 "})
    assert result["name"] == "新名称"
    updated = json.loads((role / "character.json").read_text(encoding="utf-8"))
    assert updated == {**card, "name": "新名称"}
    assert json.loads((role / "manifest.json").read_text(encoding="utf-8")) == manifest
    assert voice_console.action({"action": "list"})["roles"][0]["name"] == "新名称"
    with pytest.raises(HTTPException):
        voice_console.action({"action": "rename", "role": "narrator_one", "name": "  "})
    assert json.loads((role / "character.json").read_text(encoding="utf-8")) == updated


def test_rename_draft_before_selection(tmp_path, monkeypatch):
    monkeypatch.setattr(voice_console, "LIBRARY", tmp_path)
    role = tmp_path / "draft_one"
    role.mkdir()
    (role / "manifest.json").write_text(json.dumps({"character_id": "draft_one", "clips": []}), encoding="utf-8")
    voice_console.action({"action": "rename", "role": "draft_one", "name": "待选声音"})
    item = voice_console.action({"action": "list"})["roles"][0]
    assert item["name"] == "待选声音"
    assert item["selected"] is None
