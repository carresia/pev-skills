# 规范化与领域建模

---

## Normal Forms 速查

| 范式 | 规则 | 违例特征 |
|------|------|----------|
| **1NF** | 值原子、无重复组 | `product_ids = '1,2,3'` 逗号串 |
| **2NF** | 1NF + 无部分依赖（针对复合主键） | order_items 里存 customer_name |
| **3NF** | 2NF + 无传递依赖 | customers 里 country 由 postal_code 推得 |

```sql
-- 1NF 违例 → 拆子表
product_ids VARCHAR(255)              -- BAD: '101,102,103'，无法 JOIN/约束/索引
→ CREATE TABLE order_items (order_id ..., product_id ...)

-- 2NF 违例 → 依赖整键的列才留在复合键表里
order_items(order_id, product_id, customer_name)   -- BAD: customer_name 只依赖 order_id
→ customer 信息归 orders/customers 表

-- 3NF 违例 → 传递依赖拆出去
customers(postal_code, country)       -- BAD: country ← postal_code ← id 传递依赖
→ CREATE TABLE postal_codes (code PRIMARY KEY, country)
```

**实务标准：OLTP 做到 3NF 即可。** BCNF/4NF/5NF 留给论文；把精力花在 access pattern 与约束上。

## Denormalization：只按证据做

规则：**先 3NF，出现具体的慢查询证据后，才引入冗余；每处冗余注明服务的查询和同步机制。**

| 场景 | 手段 | 同步机制 |
|------|------|----------|
| 列表页反复 JOIN 取父名 | 子表冗余 `xxx_name` 列 | 应用层双写 / 触发器 |
| 聚合值高频读（订单总额、评论数） | 预计算列 `total_cents`、`comment_count` | 事务内同更 / 异步补偿 |
| 报表/仪表盘 | Materialized View（PG 原生；MySQL 用定时任务落汇总表） | 定时 REFRESH |
| 历史快照（下单时的商品价格） | **这不是 denorm，是业务事实** —— 必须冗余 | 写入时固化，永不回填 |

最后一行最常被误判：`order_items.unit_price` 冗余 `products.price` 不是范式违例——订单价是交易时刻的事实，商品改价不应影响历史订单。**区分「派生值」（可重算，是 denorm）与「时点事实」（不可重算，必须落表）。**

## 常用建模模式

### 软删除（soft delete）

```sql
deleted_at timestamptz   -- NULL = 活行；非 NULL = 删除时刻（比 is_deleted 多携带时间信息）
```

配套义务（缺一即 bug）：
1. 所有业务查询默认带 `WHERE deleted_at IS NULL`（ORM 全局 scope 强制）；
2. 唯一约束改为 partial：PG `CREATE UNIQUE INDEX ... WHERE deleted_at IS NULL`；MySQL 无 partial index，用生成列技巧：

```sql
-- MySQL：deleted_at 为 NULL 时 alive=1，参与唯一键；非 NULL 时 alive=NULL，
-- 而 MySQL UNIQUE 允许多个 NULL → 已删行不占用唯一名额
alive TINYINT GENERATED ALWAYS AS (IF(deleted_at IS NULL, 1, NULL)) VIRTUAL,
UNIQUE KEY uniq_email_alive (email, alive)
```

**什么时候不用软删除**：法务要求物理清除（GDPR）、行数巨大且删除占比高（改归档表）。

### 乐观锁（optimistic locking）

并发改同一行、后写覆盖先写不可接受时（余额、库存、文档协作）：

```sql
version INT NOT NULL DEFAULT 0
-- UPDATE ... SET version = version + 1 WHERE id = ? AND version = ?
-- affected_rows = 0 → 冲突，应用层重试或报错
```

### 审计与历史

| 需求 | 方案 |
|------|------|
| 谁在何时改过（轻量） | `created_by` / `updated_by` + 时间戳列 |
| 完整变更历史 | 独立 `xxx_history` 表，触发器或应用层追加写 |
| 全库级审计 | PG 用 pgaudit / 触发器方案；或 CDC（Debezium）外送 |

### 多租户（multi-tenancy）

| 方案 | 隔离 | 成本 | 适用 |
|------|------|------|------|
| 共享表 + `tenant_id` 列 | 弱（靠查询纪律） | 最低 | 绝大多数 SaaS —— **默认** |
| PG schema-per-tenant | 中 | migration 乘租户数 | 数百租户内、隔离敏感 |
| 库/实例 per tenant | 强 | 最高 | 大客户合规要求 |

共享表方案的纪律：
- `tenant_id` 出现在**每张业务表**且 NOT NULL；
- 复合索引与 UNIQUE 一律以 `tenant_id` 打头（`UNIQUE (tenant_id, slug)`）;
- PG 可加 Row-Level Security 兜底：`CREATE POLICY tenant_isolation ON orders USING (tenant_id = current_setting('app.tenant_id')::bigint)`。

## SQL vs NoSQL 选型

| 信号 | 倾向 |
|------|------|
| 关系多、事务性不变量（转账、扣库存）、ad-hoc 查询 | SQL |
| 聚合为读写单元、schema 异构、水平写扩展是硬需求 | NoSQL（文档） |
| 「关系型数据 + 少量灵活字段」 | **SQL + jsonb 列**，不要为局部灵活性放弃整库约束 |

默认答案是 PostgreSQL：jsonb 覆盖了大部分「想用 Mongo」的动机，而 FK/事务/JOIN 保留完整。选 NoSQL 应当由 access pattern 与扩展需求驱动，而非「灵活」的感觉。文档建模见 [nosql-mongodb.md](nosql-mongodb.md)。
