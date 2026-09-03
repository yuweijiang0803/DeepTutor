"""Authoritative DDL for the subject-pack tables.

Single source of truth for the four global ``dt_subject*`` tables.  The sync
migration (``deeptutor/services/sync/migrate.py``) appends this to its server
schema and the subject-pack MySQL store executes it idempotently on first
connect, so the two code paths can never drift.

Conventions (mirroring the ``dt_mastery_*`` block of ``migrate.py``):

* Global pre-set content — no ``user_id`` column; every learner references the
  same tree.
* Stable semantic ids, reused directly as the mastery engine's
  ``LearningModule.id`` / ``KnowledgePoint.id``:
  ``math-rjb-7a`` → ``math-rjb-7a-u1`` → ``math-rjb-7a-u1-k2``.
* Epoch ``DOUBLE`` timestamps, utf8mb4, idempotent ``CREATE TABLE IF NOT
  EXISTS`` (safe to re-run through the ``;``-splitting executor).
"""

SUBJECT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS dt_subject (
  id          VARCHAR(64)  NOT NULL PRIMARY KEY,
  name        VARCHAR(255) NOT NULL,             -- 学科名，如「初中数学」
  stage       VARCHAR(32)  NOT NULL DEFAULT '',  -- 学段：junior / senior …
  grade       VARCHAR(64)  NOT NULL DEFAULT '',  -- 册：七年级上册
  textbook    VARCHAR(64)  NOT NULL DEFAULT '',  -- 对齐教材：人教版
  status      VARCHAR(16)  NOT NULL DEFAULT 'active',
  created_at  DOUBLE       NOT NULL,
  updated_at  DOUBLE       NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS dt_subject_module (
  id             VARCHAR(64)  NOT NULL PRIMARY KEY,
  subject_id     VARCHAR(64)  NOT NULL,
  name           VARCHAR(255) NOT NULL,          -- 章名：第一章 有理数
  order_no       INT          NOT NULL DEFAULT 0,
  pass_threshold FLOAT        NOT NULL DEFAULT 0.7,
  created_at     DOUBLE       NOT NULL,
  updated_at     DOUBLE       NOT NULL,
  KEY idx_subject_module (subject_id, order_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS dt_subject_kp (
  id                VARCHAR(64)   NOT NULL PRIMARY KEY,
  module_id         VARCHAR(64)   NOT NULL,
  name              VARCHAR(255)  NOT NULL,       -- 知识点名：绝对值
  kp_type           VARCHAR(16)   NOT NULL DEFAULT 'procedure',  -- memory/procedure/concept/design
  order_no          INT           NOT NULL DEFAULT 0,
  -- OpenMAIC 课件引用：该知识点的讲解课件 stage（本体在 OpenMAIC 侧，DeepTutor 只存引用）
  openmaic_stage_id VARCHAR(64)   NOT NULL DEFAULT '',
  openmaic_url      VARCHAR(512)  NOT NULL DEFAULT '',
  created_at        DOUBLE        NOT NULL,
  updated_at        DOUBLE        NOT NULL,
  KEY idx_subject_kp (module_id, order_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS dt_subject_question (
  id           VARCHAR(64)  NOT NULL PRIMARY KEY,
  kp_id        VARCHAR(64)  NOT NULL,
  question     MEDIUMTEXT   NOT NULL,             -- 支持 LaTeX
  q_type       VARCHAR(16)  NOT NULL DEFAULT 'choice',  -- choice / fill_in_blank / written
  options_json MEDIUMTEXT,
  answer       MEDIUMTEXT   NOT NULL,
  explanation  MEDIUMTEXT,
  difficulty   VARCHAR(16)  NOT NULL DEFAULT 'medium',  -- easy / medium / hard
  created_by   VARCHAR(64)  NOT NULL DEFAULT 'system',
  created_at   DOUBLE       NOT NULL,
  updated_at   DOUBLE       NOT NULL,
  KEY idx_subject_question (kp_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

__all__ = ["SUBJECT_SCHEMA_SQL"]
