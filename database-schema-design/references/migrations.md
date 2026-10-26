# Schema Migrations：可逆与零停机

原则：**每个 migration 可逆（UP+DOWN 成对）、向后兼容（老代码在新 schema 上能跑）、评估锁影响后才执行。**

模板：[../assets/templates/migration-template.sql](../assets/templates/migration-template.sql)

---

## Expand → Migrate → Contract（核心模式）

一切零停机变更的骨架：**先加不破坏的新结构（expand），双写/回填过渡（migrate），确认无引用后再删旧结构（contract）。** 部署顺序永远是「schema 先行、代码随后、清理殿后」。

### 加列

```sql
-- 1. expand：加 nullable 列（或带 DEFAULT，见下方版本说明）
ALTER TABLE users ADD COLUMN phone VARCHAR(16);
-- 2. 部署写新列的代码
-- 3. migrate：分批回填（见下）
-- 4. contract：确认无 NULL 后收紧
ALTER TABLE users ALTER COLUMN phone SET NOT NULL;         -- PG
ALTER TABLE users MODIFY phone VARCHAR(16) NOT NULL;        -- MySQL
```

版本红利（可简化步骤 1）：
- **MySQL 8.0+**：`ADD COLUMN` 默认 INSTANT（含带 DEFAULT 的），metadata-only；
- **PG 11+**：`ADD COLUMN ... DEFAULT <常量>` 不重写表。
- 更老版本：带 DEFAULT 的加列会重写全表 → 必须走「先 nullable、后回填」。

### 改名列（永远不要直接 RENAME）

直接 RENAME 在部署窗口内必炸（老代码还在读旧名）。五步：

```
1. 加新列 → 2. 代码双写新旧列 + 回填 → 3. 代码改读新列
→ 4. 代码停写旧列 → 5. DROP 旧列
```

每步之间是独立部署，任一步可回滚。改列类型同理（新列 + 双写 + 切读 + 删旧）。

### 删列

先部署「代码不再引用该列」，观察一个发布周期，再 DROP。DOWN migration 里 `ADD COLUMN` 可恢复结构但**恢复不了数据**——删列前先确认备份策略，并在 migration NOTES 里写明「DOWN 不恢复数据」。

## 锁影响评估（执行前必查）

| 操作 | MySQL 8.0 InnoDB | PostgreSQL |
|------|------------------|-----------|
| ADD COLUMN | INSTANT | 快（11+ 常量 DEFAULT） |
| ADD INDEX | INPLACE，容许并发 DML | **裸 CREATE INDEX 锁写** → 必须 `CREATE INDEX CONCURRENTLY` |
| 改列类型 | 常需 COPY（重建表） | 常需全表重写 + 排他锁 |
| ADD FOREIGN KEY | 校验期锁 | 长锁 → `ADD CONSTRAINT ... NOT VALID` 后 `VALIDATE CONSTRAINT`（短锁+并发校验） |
| ADD CHECK / NOT NULL | 快 | 同上可用 NOT VALID 两步法 |

要点：
- **MySQL**：DDL 写明算法期望，`ALTER TABLE ... ALGORITHM=INSTANT/INPLACE, LOCK=NONE`——不满足时直接报错而不是静默锁表。仍需 COPY 的大表变更用 gh-ost / pt-online-schema-change。
- **PG**：`CREATE INDEX CONCURRENTLY` 不能在事务块里跑（migration 工具需标注 `disableTransaction`）；失败会留下 INVALID 索引，需 DROP 后重建。
- **PG 大忌**：长事务 + DDL 排队会把后续所有查询堵成串。执行 DDL 前设 `lock_timeout`（如 `SET lock_timeout = '5s'`），拿不到锁快速失败重试。

## 分批回填（backfill）

**禁止单条 UPDATE 回填大表**——长事务、锁范围、主从延迟三杀。

```sql
-- 主键区间分批，每批独立提交，批间 sleep
UPDATE users SET phone = '' WHERE phone IS NULL AND id BETWEEN 1 AND 10000;
UPDATE users SET phone = '' WHERE phone IS NULL AND id BETWEEN 10001 AND 20000;
-- ...（脚本循环；监控主从延迟动态调批量）
```

Schema migration 与 data migration 分离成两个文件：schema 快而可逆，data 慢而幂等（可中断重跑）。

## Migration 卫生

| 规则 | WHY |
|------|-----|
| UP + DOWN 成对 | 回滚不是可选项 |
| 一个 migration 一个关注点 | 定位与回滚粒度 |
| 幂等写法（`IF NOT EXISTS` / 先查后改） | 重跑不炸 |
| 不可逆操作（DROP COLUMN）显式标注 | DOWN 恢复结构不恢复数据，团队须知情 |
| staging 用生产级数据量演练 | 10 行表上一切 DDL 都是瞬时的，错觉致命 |
| 标注预估耗时 + 是否需要维护窗口 | 运维可规划 |

**MySQL 注意：DDL 隐式提交，无法与 DML 包在同一事务里回滚**（8.0 起支持原子 DDL，单条 DDL 崩溃不半残，但仍不能多语句成组回滚）。PG 的 DDL 完全事务化——除 `CREATE INDEX CONCURRENTLY` 等少数例外，migration 可整体包事务。
