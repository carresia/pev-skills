-- Migration: YYYYMMDDHHMMSS_descriptive_name.sql
-- Description: [这次变更做什么、为什么]
-- Dialect/Version: [MySQL 8.0.x / PostgreSQL 16 —— 锁行为因版本而异]
-- Author: [姓名]
-- Date: YYYY-MM-DD

-- ============================================================================
-- 锁影响评估（执行前必填，见 references/migrations.md）
-- ============================================================================
-- 操作类型:       [ADD COLUMN / ADD INDEX / ADD FK / 改类型 / ...]
-- 预期算法:       [MySQL: INSTANT/INPLACE/COPY | PG: 是否重写表]
-- 表当前行数:     [X 行]
-- 预估耗时:       [staging 生产级数据量实测值]
-- 是否需维护窗口: [Yes/No；No 则说明零停机依据]

-- ============================================================================
-- UP
-- ============================================================================

-- PG: DDL 可整体包事务（CREATE INDEX CONCURRENTLY 除外，须裸跑且设 lock_timeout）
-- MySQL: DDL 隐式提交，无法与 DML 同事务回滚——每条 DDL 独立可重入
BEGIN;

-- 示例：建表
CREATE TABLE IF NOT EXISTS table_name (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,  -- MySQL: BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY
  name       VARCHAR(100) NOT NULL,
  status     VARCHAR(20)  NOT NULL DEFAULT 'draft'
             CHECK (status IN ('draft', 'active')),            -- MySQL <8.0.16 CHECK 不执行，改 lookup 表
  created_at timestamptz  NOT NULL DEFAULT now(),              -- MySQL: DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
  updated_at timestamptz  NOT NULL DEFAULT now()               -- MySQL 加 ON UPDATE CURRENT_TIMESTAMP(6)；PG 用触发器/应用层维护
);  -- MySQL 表尾: ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci

-- 示例：加索引
-- PG 生产环境（事务外执行）: CREATE INDEX CONCURRENTLY idx_table_name_name ON table_name (name);
CREATE INDEX idx_table_name_name ON table_name (name);
-- MySQL: ALTER TABLE table_name ADD INDEX idx_table_name_name (name), ALGORITHM=INPLACE, LOCK=NONE;

-- 示例：加 FK（PG 大表两步法免长锁）
-- ALTER TABLE table_name ADD CONSTRAINT fk_table_ref
--   FOREIGN KEY (ref_id) REFERENCES other_table(id) ON DELETE RESTRICT NOT VALID;
-- ALTER TABLE table_name VALIDATE CONSTRAINT fk_table_ref;
-- 别忘了 FK 列索引（PG 不自动建）:
-- CREATE INDEX idx_table_name_ref_id ON table_name (ref_id);

COMMIT;

-- 数据回填放独立的 data migration 文件，分批提交（见 references/migrations.md）

-- ============================================================================
-- DOWN
-- ============================================================================

-- BEGIN;
-- DROP INDEX IF EXISTS idx_table_name_name;        -- MySQL: ALTER TABLE table_name DROP INDEX idx_table_name_name;
-- DROP TABLE IF EXISTS table_name;
-- COMMIT;
-- ⚠ 含 DROP COLUMN/TABLE 的 DOWN 只恢复结构不恢复数据——在此标注数据恢复途径（备份/归档表）

-- ============================================================================
-- 验证
-- ============================================================================
-- 结构:   \d table_name (PG) / SHOW CREATE TABLE table_name (MySQL)
-- 索引:   PG: SELECT indexname FROM pg_indexes WHERE tablename='table_name';
--         MySQL: SHOW INDEX FROM table_name;
-- PG 专项: CONCURRENTLY 失败会遗留 INVALID 索引:
--         SELECT relname FROM pg_class c JOIN pg_index i ON c.oid=i.indexrelid WHERE NOT i.indisvalid;
