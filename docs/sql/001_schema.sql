-- 帧序 Creator Workbench · MySQL 建表脚本（一次性执行）
-- 用法：mysql -h <host> -u <user> -p < docs/sql/001_schema.sql

CREATE DATABASE IF NOT EXISTS xixi DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE xixi;

-- 帧序 Creator Workbench · 关系化 schema（MySQL 8 / 5.7）
-- 由 spring.sql.init.schema-locations 指定，仅在 mysql profile 下执行。

CREATE TABLE IF NOT EXISTS workspace_meta (
 id VARCHAR(8) NOT NULL,
 lock_version BIGINT NOT NULL DEFAULT 0,
 updated_at VARCHAR(40) NOT NULL,
 PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS project (
 id VARCHAR(64) NOT NULL,
 title VARCHAR(100) NOT NULL,
 brief MEDIUMTEXT NOT NULL,
 template VARCHAR(20) NOT NULL,
 budget DECIMAL(12,2) NOT NULL DEFAULT 0,
 sample TINYINT NOT NULL DEFAULT 0,
 poster VARCHAR(20) NOT NULL DEFAULT 'blue',
 created_at VARCHAR(40) NOT NULL,
 lock_version BIGINT NOT NULL DEFAULT 0,
 PRIMARY KEY (id),
 KEY ix_project_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS project_platform (
 project_id VARCHAR(64) NOT NULL,
 platform VARCHAR(20) NOT NULL,
 position INT NOT NULL DEFAULT 0,
 PRIMARY KEY (project_id, platform),
 CONSTRAINT fk_platform_project FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS node_instance (
 project_id VARCHAR(64) NOT NULL,
 node_id VARCHAR(5) NOT NULL,
 status VARCHAR(24) NOT NULL,
 draft MEDIUMTEXT NOT NULL,
 output MEDIUMTEXT NOT NULL,
 revision INT NOT NULL DEFAULT 0,
 skip_reason VARCHAR(1000) NULL,
 updated_at VARCHAR(40) NULL,
 PRIMARY KEY (project_id, node_id),
 KEY ix_node_status (project_id, status),
 CONSTRAINT fk_node_project FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS node_dependency (
 project_id VARCHAR(64) NOT NULL,
 node_id VARCHAR(5) NOT NULL,
 depends_on VARCHAR(5) NOT NULL,
 dep_revision INT NOT NULL,
 PRIMARY KEY (project_id, node_id, depends_on),
 KEY ix_dep_upstream (project_id, depends_on),
 CONSTRAINT fk_dep_node FOREIGN KEY (project_id, node_id) REFERENCES node_instance(project_id, node_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS approval_decision (
 project_id VARCHAR(64) NOT NULL,
 gate_id VARCHAR(5) NOT NULL,
 fingerprint VARCHAR(200) NOT NULL,
 decision VARCHAR(12) NOT NULL,
 decided_at VARCHAR(40) NOT NULL,
 PRIMARY KEY (project_id, gate_id),
 CONSTRAINT fk_approval_project FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS archived_node (
 project_id VARCHAR(64) NOT NULL,
 node_id VARCHAR(5) NOT NULL,
 payload MEDIUMTEXT NOT NULL,
 PRIMARY KEY (project_id, node_id),
 CONSTRAINT fk_archived_project FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS model_profile (
 id VARCHAR(64) NOT NULL,
 name VARCHAR(80) NOT NULL,
 payload MEDIUMTEXT NOT NULL,
 PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS model_binding (
 scope_type VARCHAR(10) NOT NULL,
 scope_id VARCHAR(64) NOT NULL,
 capability VARCHAR(40) NOT NULL,
 model_id VARCHAR(64) NOT NULL,
 PRIMARY KEY (scope_type, scope_id, capability)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS task (
 id VARCHAR(90) NOT NULL,
 project_id VARCHAR(64) NOT NULL,
 node_id VARCHAR(5) NULL,
 title VARCHAR(100) NOT NULL,
 status VARCHAR(20) NOT NULL,
 detail MEDIUMTEXT NOT NULL,
 created_at VARCHAR(40) NOT NULL,
 deleted_at VARCHAR(40) NULL,
 PRIMARY KEY (id),
 KEY ix_task_project (project_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS asset (
 id VARCHAR(90) NOT NULL,
 name VARCHAR(255) NOT NULL,
 type VARCHAR(120) NOT NULL,
 size BIGINT NOT NULL DEFAULT 0,
 source VARCHAR(120) NOT NULL,
 file_ref VARCHAR(150) NOT NULL,
 project_id VARCHAR(64) NOT NULL DEFAULT '',
 created_at VARCHAR(40) NOT NULL,
 PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS idea (
 id VARCHAR(90) NOT NULL,
 text MEDIUMTEXT NOT NULL,
 created_at VARCHAR(40) NOT NULL,
 PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ledger_entry (
 id VARCHAR(90) NOT NULL,
 label VARCHAR(200) NOT NULL,
 amount DECIMAL(14,2) NOT NULL,
 kind VARCHAR(10) NOT NULL,
 created_at VARCHAR(40) NOT NULL,
 PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS creator_profile (
 id VARCHAR(8) NOT NULL,
 payload MEDIUMTEXT NOT NULL,
 updated_at VARCHAR(40) NOT NULL,
 PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS agent_run (
 id VARCHAR(100) NOT NULL,
 project_id VARCHAR(90) NOT NULL,
 node_id VARCHAR(5) NOT NULL,
 payload LONGTEXT NOT NULL,
 input_fingerprint VARCHAR(64) NOT NULL,
 state VARCHAR(40) NOT NULL,
 created_at VARCHAR(50) NOT NULL,
 deleted_at VARCHAR(50) NULL,
 PRIMARY KEY (id),
 KEY ix_run_state (state, created_at),
 KEY ix_run_project (project_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS media_file (
 id VARCHAR(64) NOT NULL,
 original_name VARCHAR(255) NOT NULL,
 storage_name VARCHAR(80) NOT NULL,
 media_type VARCHAR(120) NOT NULL,
 byte_size BIGINT NOT NULL,
 sha256 VARCHAR(64) NOT NULL,
 created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS workspace_document (
 id VARCHAR(64) NOT NULL,
 payload LONGTEXT NOT NULL,
 revision BIGINT NOT NULL DEFAULT 0,
 updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS comfy_run (
 id VARCHAR(100) NOT NULL PRIMARY KEY,
 project_id VARCHAR(90) NOT NULL,
 node_id VARCHAR(5) NOT NULL,
 template_id VARCHAR(100) NOT NULL,
 prompt_id VARCHAR(36) NOT NULL,
 payload LONGTEXT NOT NULL,
 input_fingerprint VARCHAR(64) NOT NULL,
 state VARCHAR(30) NOT NULL,
 created_at VARCHAR(50) NOT NULL,
 message VARCHAR(1000),
 file_ref VARCHAR(150),
 sha256 VARCHAR(64),
 byte_size BIGINT,
 adopted BOOLEAN NOT NULL DEFAULT FALSE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
