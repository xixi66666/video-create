-- 素材内容与元数据在同一数据库事务提交；现有表不会被覆盖。
CREATE TABLE IF NOT EXISTS creator_media_content (
 file_id VARCHAR(64) NOT NULL PRIMARY KEY,
 content LONGBLOB NOT NULL,
 CONSTRAINT fk_creator_media_file FOREIGN KEY (file_id) REFERENCES media_file(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS creator_dub_run (
 id VARCHAR(32) NOT NULL PRIMARY KEY,
 project_id VARCHAR(90) NOT NULL,
 manifest_json LONGTEXT NOT NULL,
 updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
 INDEX ix_creator_dub_project (project_id, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS creator_dub_audio (
 run_id VARCHAR(32) NOT NULL,
 file_name VARCHAR(20) NOT NULL,
 sha256 CHAR(64) NOT NULL,
 content LONGBLOB NOT NULL,
 PRIMARY KEY (run_id, file_name),
 CONSTRAINT fk_creator_dub_audio_run FOREIGN KEY (run_id) REFERENCES creator_dub_run(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
