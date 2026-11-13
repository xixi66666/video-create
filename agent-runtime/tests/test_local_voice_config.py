import json

import pytest

from app import local_voice_config


@pytest.fixture(autouse=True)
def isolate_config(tmp_path, monkeypatch):
    monkeypatch.setattr(local_voice_config, "CONFIG_PATH", tmp_path / "model.local")
    for name in ("CREATOR_VOICE_DB_HOST", "CREATOR_VOICE_DB_PORT", "CREATOR_VOICE_DB_NAME",
                 "CREATOR_VOICE_DB_USER", "CREATOR_VOICE_DB_PASSWORD", "MIMO_API_KEY",
                 "CREATOR_MIMO_VOICECLONE_MODEL"):
        # load() 会修改进程环境；先登记原值，确保测试结束时清理。
        monkeypatch.setenv(name, "fixture-placeholder")
        monkeypatch.delenv(name)


def write_config():
    local_voice_config.CONFIG_PATH.write_text(json.dumps({"voice": {
        "database": {"host": "db.test", "port": 3306, "name": "voices", "passwordCredential": "db"},
        "mimo": {"model": "test-model", "apiKeyCredential": "mimo"}}}), encoding="utf-8")


def test_load_reads_credential_store_without_writing_secrets(monkeypatch):
    write_config()
    monkeypatch.setattr(local_voice_config, "read_credential", lambda ref: ("secret-" + ref, "db-user"))
    local_voice_config.load()
    import os
    assert os.environ["CREATOR_VOICE_DB_USER"] == "db-user"
    assert os.environ["CREATOR_VOICE_DB_PASSWORD"] == "secret-db"
    assert os.environ["MIMO_API_KEY"] == "secret-mimo"
    assert os.environ["CREATOR_MIMO_VOICECLONE_MODEL"] == "test-model"
    assert "secret-" not in local_voice_config.CONFIG_PATH.read_text(encoding="utf-8")


def test_environment_database_is_not_mixed_with_local_configuration(monkeypatch):
    write_config()
    monkeypatch.setenv("CREATOR_VOICE_DB_HOST", "override.test")
    monkeypatch.setenv("MIMO_API_KEY", "override-key")
    monkeypatch.setattr(local_voice_config, "read_credential", lambda ref: pytest.fail("不应读取凭据"))
    local_voice_config.load()
    import os
    assert os.environ["CREATOR_VOICE_DB_HOST"] == "override.test"
    assert "CREATOR_VOICE_DB_PASSWORD" not in os.environ
    assert os.environ["MIMO_API_KEY"] == "override-key"


def test_invalid_configuration_fails_without_disclosing_values():
    local_voice_config.CONFIG_PATH.write_text('{"voice":', encoding="utf-8")
    with pytest.raises(ValueError, match="model.local"):
        local_voice_config.load()


def test_voice_subprocess_can_load_only_mimo(monkeypatch):
    write_config()
    monkeypatch.setattr(local_voice_config, "read_credential", lambda ref: ("secret-" + ref, "user"))
    local_voice_config.load(include_database=False)
    import os
    assert os.environ["MIMO_API_KEY"] == "secret-mimo"
    assert "CREATOR_VOICE_DB_PASSWORD" not in os.environ
