# 主键与索引策略（MySQL / PostgreSQL）

---

## 主键选型

| 方案 | 存储 | 优点 | 缺点 | 适用 |
|------|------|------|------|------|
| 自增整数 | `BIGINT` | 最快、最省、时间有序 | 单点发号；ID 可枚举暴露业务量 | 单库单写入点 —— **默认** |
| UUIDv7 | `BINARY(16)` / PG `uuid` | 时间有序 + 分布式无协调发号 | 比 BIGINT 略大 | 分布式写入、需要合库、ID 先于落库生成 |
| ULID | 同上 | 同 UUIDv7，字符序即时间序 | 生态非标准 | 同上（团队已有惯例时） |
| Snowflake | `BIGINT` | 时间有序 + 分布式 + 仍是 8 字节 | 需发号服务/机器位分配 | 大规模分布式（有基建时） |
| 自然键 | 视情况 | 无冗余列 | 业务变更即灾难（邮箱换绑、身份证升位） | 仅静态标准码表（国家码、币种） |

**核心机制：InnoDB 表按 PK 聚簇存储。** 随机 PK（UUIDv4）使插入均匀砸向整棵 B+ 树 → 页分裂、buffer pool 污染；且**每个二级索引叶子都携带 PK 值**，PK 用 CHAR(36) 会让全部二级索引膨胀 4.5 倍（36 vs 8 字节）。PG 堆表无聚簇问题，但随机 UUID 同样使 B-tree 索引写放大、WAL 变大。**结论：需要 UUID 时用时间有序的 v7，绝不用 CHAR(36) 存。**

```sql
-- MySQL
id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY   -- 默认
id BINARY(16) PRIMARY KEY                                 -- UUIDv7，应用层生成

-- PostgreSQL
id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY        -- 默认（IDENTITY 优于 serial：serial 是伪类型，权限与依赖管理粗糙）
id uuid PRIMARY KEY                                       -- UUIDv7，应用层生成；PG 18+ 可 DEFAULT uuidv7()
```

对外暴露的资源标识与内部 PK 可以分离：内部 `BIGINT` 自增 + 对外 `public_id`（UUID/NanoID，UNIQUE 索引），同时拿到性能与不可枚举性。

## 什么列该建索引

| 建 | 原因 |
|----|------|
| FK 列 | JOIN、级联删除。**MySQL 建 FK 时自动建索引，PG 不会——PG 必须手动建** |
| 高频 WHERE 等值/范围列 | 避免全表扫描 |
| ORDER BY / GROUP BY 列 | 避免 filesort / 临时表 |
| UNIQUE 业务键 | 唯一性本身靠索引实现 |

**每个索引必须能指出它服务的具体查询。** 指不出来 = 删掉。写入时每个索引都要维护，over-indexing 是慢写入的头号原因。

## 复合索引：列序规则

```
等值条件列在前 → 排序列其次 → 范围条件列最后
```

```sql
-- 查询：WHERE tenant_id = ? AND status = ? AND created_at > ? ORDER BY created_at
CREATE INDEX idx_orders_tenant_status_created
  ON orders (tenant_id, status, created_at);
-- 等值(tenant_id, status)在前，范围+排序(created_at)在最后
```

**最左前缀原则**：`(a, b, c)` 可服务 `a`、`a,b`、`a,b,c` 的查询，**不能**服务只有 `b` 或 `c` 的查询。范围条件之后的列无法再用于索引定位——这是「范围列放最后」的原因。

已有 `(a, b)` 时再建 `(a)` 是冗余；反之 `(a)` 升级为 `(a, b)` 后应删旧索引。

## Covering Index

查询所需列全部在索引中 → 免回表（MySQL `Extra: Using index`；PG Index Only Scan）：

```sql
-- 查询：SELECT status, total FROM orders WHERE user_id = ?
CREATE INDEX idx_orders_user_covering ON orders (user_id, status, total);        -- MySQL：全列进 key
CREATE INDEX idx_orders_user_covering ON orders (user_id) INCLUDE (status, total); -- PG 11+：INCLUDE 列不参与排序，索引更浅
```

高频窄查询的第一优化手段。这也是「SELECT * 是反模式」的技术原因——列清单不确定就永远无法 covering。

## 索引类型速查

| 类型 | MySQL | PostgreSQL | 用途 |
|------|-------|-----------|------|
| B-tree | 默认 | 默认 | 等值、范围、排序（99% 场景） |
| Hash | MEMORY 引擎 | `USING hash` | 纯等值（B-tree 通常够用） |
| 全文 | `FULLTEXT` | GIN + `tsvector` | 文本检索（重需求上 ES/Meilisearch） |
| GIN | 无 | `USING GIN` | jsonb、数组、全文 |
| Partial | 无（可用生成列模拟） | `WHERE` 子句 | 只索引热子集，见下 |
| 函数/表达式 | 8.0.13+ `((expr))` | `(lower(email))` | 表达式查询 |

**Partial index 是 PG 的独门利器**——大表里只有小子集被高频查询时，索引体积和写放大都数量级下降：

```sql
-- 千万行订单，只有 1% 是 pending，且只有 pending 被轮询
CREATE INDEX idx_orders_pending ON orders (created_at) WHERE status = 'pending';

-- 软删除表的「活行」唯一约束（deleted_at IS NULL 的行内 email 唯一）
CREATE UNIQUE INDEX uniq_users_email_active ON users (email) WHERE deleted_at IS NULL;
```

## 验证：EXPLAIN 读法

```sql
EXPLAIN SELECT ... ;                    -- MySQL / PG 通用入口
EXPLAIN (ANALYZE, BUFFERS) SELECT ...;  -- PG 实际执行并给出真实行数与 IO
```

| 信号 | MySQL | PostgreSQL | 含义 |
|------|-------|-----------|------|
| 坏 | `type: ALL` | `Seq Scan`（于大表） | 全表扫描 |
| 好 | `type: ref/range` | `Index Scan` | 走索引 |
| 更好 | `Extra: Using index` | `Index Only Scan` | covering，免回表 |
| 坏 | `Extra: Using filesort` | 外部 `Sort` 节点 | 排序未被索引消化 |

**交付索引设计时，对最关键的 1~2 条查询附 EXPLAIN 预期。** 设计阶段无法运行时，注明「上线后以 EXPLAIN (ANALYZE) 验证」。

## 索引反模式

| 反模式 | 后果 | 纠正 |
|--------|------|------|
| 每列一个单列索引 | 优化器多数只用一个；写入全拖慢 | 按查询建复合索引 |
| 索引低选择性列（如 gender） | 扫描量几乎不减 | 放进复合索引后列，或 partial index |
| WHERE 里对列套函数 | `WHERE DATE(created_at) = ?` 索引失效 | 改范围：`created_at >= ? AND created_at < ?`，或表达式索引 |
| 隐式类型转换 | 字符串列用数字比较，索引失效 | 参数类型与列一致 |
| 前缀通配 LIKE | `LIKE '%foo'` 无法走 B-tree | 全文索引 / PG `pg_trgm` |
