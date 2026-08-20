-- DeepTutor ↔ XiaoZhi 共享库：DeepTutor 会话存储 4 张表
-- 在阿里云 RDS 的 mixly 库中手动执行（或任何管理工具中）
-- 可重复执行（IF NOT EXISTS），幂等安全。
-- 时间字段为 epoch DOUBLE，与 DeepTutor SQLite 的 REAL 保持一致。

CREATE TABLE IF NOT EXISTS dt_sessions (
    id                   VARCHAR(64)  NOT NULL,
    user_id              VARCHAR(64)  NOT NULL,
    title                VARCHAR(255) NOT NULL DEFAULT 'New conversation',
    created_at           DOUBLE       NOT NULL,
    updated_at           DOUBLE       NOT NULL,
    compressed_summary   MEDIUMTEXT,
    summary_up_to_msg_id BIGINT       NOT NULL DEFAULT 0,
    preferences_json     MEDIUMTEXT   NOT NULL,
    PRIMARY KEY (id),
    KEY idx_dt_sessions_user (user_id, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS dt_messages (
    id                 BIGINT       NOT NULL AUTO_INCREMENT,
    session_id         VARCHAR(64)  NOT NULL,
    user_id            VARCHAR(64)  NOT NULL,
    role               VARCHAR(16)  NOT NULL,
    content            MEDIUMTEXT   NOT NULL,
    capability         VARCHAR(32)  NOT NULL DEFAULT '',
    events_json        MEDIUMTEXT,
    attachments_json   MEDIUMTEXT,
    metadata_json      MEDIUMTEXT,
    created_at         DOUBLE       NOT NULL,
    parent_message_id  BIGINT       NULL,
    PRIMARY KEY (id),
    KEY idx_dt_messages_session (session_id, created_at, id),
    KEY idx_dt_messages_user (user_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS dt_turns (
    id          VARCHAR(64) NOT NULL,
    session_id  VARCHAR(64) NOT NULL,
    user_id     VARCHAR(64) NOT NULL,
    capability  VARCHAR(32) NOT NULL DEFAULT '',
    status      VARCHAR(16) NOT NULL DEFAULT 'running',
    error       TEXT,
    created_at  DOUBLE      NOT NULL,
    updated_at  DOUBLE      NOT NULL,
    finished_at DOUBLE      NULL,
    PRIMARY KEY (id),
    KEY idx_dt_turns_session (session_id, updated_at),
    KEY idx_dt_turns_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS dt_turn_events (
    id            BIGINT      NOT NULL AUTO_INCREMENT,
    turn_id       VARCHAR(64) NOT NULL,
    seq           INT         NOT NULL,
    type          VARCHAR(32) NOT NULL,
    source        VARCHAR(64) NOT NULL DEFAULT '',
    stage         VARCHAR(32) NOT NULL DEFAULT '',
    content       MEDIUMTEXT,
    metadata_json TEXT        NOT NULL,
    timestamp     DOUBLE      NOT NULL,
    created_at    DOUBLE      NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_dt_turn_events (turn_id, seq)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
