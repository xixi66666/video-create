-- 声音角色库独立表；只创建不存在的表，不修改其他项目的数据。
CREATE TABLE IF NOT EXISTS voice_character (
    character_id VARCHAR(32) NOT NULL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    version VARCHAR(32) NULL,
    selected_candidate INT NULL,
    manifest_json LONGTEXT NOT NULL,
    revision BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS voice_audio (
    character_id VARCHAR(32) NOT NULL,
    file_name VARCHAR(191) NOT NULL,
    kind VARCHAR(20) NOT NULL,
    byte_size BIGINT NOT NULL,
    sha256 CHAR(64) NOT NULL,
    content LONGBLOB NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (character_id, file_name),
    CONSTRAINT fk_voice_audio_character FOREIGN KEY (character_id)
        REFERENCES voice_character(character_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
