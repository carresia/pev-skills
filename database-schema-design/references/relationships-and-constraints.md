# 关系建模与约束（MySQL / PostgreSQL）

原则：**完整性规则能进数据库就进数据库。** 应用层校验挡不住并发写入、脚本直连、第二个服务接入。

---

## Foreign Keys 与 ON DELETE 策略

```sql
CONSTRAINT fk_orders_user FOREIGN KEY (user_id) REFERENCES users(id)
  ON DELETE RESTRICT ON UPDATE CASCADE
```

| 策略 | 语义 | 典型场景 |
|------|------|----------|
| `RESTRICT` / `NO ACTION` | 有子行时禁删父行 | **默认选它** —— 误删保护 |
| `CASCADE` | 删父连删子 | 纯从属数据（order → order_items） |
| `SET NULL` | 删父置子 FK 为 NULL（列须 nullable） | 可选归属（文章的作者离职置空） |

**每个 FK 必须显式写 ON DELETE，禁止依赖默认值** ——评审时把「未声明 ON DELETE」视为缺陷。CASCADE 慎用于「大扇出」关系：删一个租户级联抹掉百万行是事故不是功能，宁可 RESTRICT + 应用层编排删除。

FK 索引：MySQL 自动创建；**PG 不会，必须手动为 FK 列建索引**（否则父表删改会全表扫子表）。

## 一对多

```sql
CREATE TABLE orders (
  id      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT
);
CREATE INDEX idx_orders_user_id ON orders (user_id);  -- PG 必须
```

## 多对多（junction table）

```sql
CREATE TABLE enrollments (
  student_id  BIGINT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  course_id   BIGINT NOT NULL REFERENCES courses(id)  ON DELETE CASCADE,
  enrolled_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (student_id, course_id)
);
CREATE INDEX idx_enrollments_course ON enrollments (course_id);
-- PK (student_id, course_id) 已覆盖 student→courses 方向；
-- 反方向 course→students 需要这条独立索引
```

关系本身携带属性（成绩、状态）时，junction table 自然升级为实体表，可换独立代理 PK + 复合 UNIQUE。

## 自引用（树/层级）

```sql
CREATE TABLE categories (
  id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name      VARCHAR(100) NOT NULL,
  parent_id BIGINT REFERENCES categories(id) ON DELETE RESTRICT  -- NULL = 根
);
```

整树查询：两方言都支持 `WITH RECURSIVE`（MySQL 8.0+ / PG）。层级深且读密集时考虑物化路径列（`path VARCHAR` 存 `/1/4/9/`）或 PG `ltree` 扩展。

## Polymorphic（多态关联）

| 方案 | 完整性 | 扩展性 | 选择 |
|------|--------|--------|------|
| ① 互斥 FK 列 + CHECK | 全 DB 层强制 | 加类型要加列 | 类型 ≤3 且稳定 —— **默认** |
| ② type + id 两列 | **无 FK，DB 层零保障** | 加类型零改动 | 类型开放集合；接受孤儿风险并注明 |
| ③ 每类型一张关联表 | 全强制 | 加类型加表 | 各类型还有专属字段时 |

```sql
-- ① 互斥 FK + CHECK（恰有一个非空）
CREATE TABLE comments (
  id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  body     TEXT NOT NULL,
  post_id  BIGINT REFERENCES posts(id)  ON DELETE CASCADE,
  photo_id BIGINT REFERENCES photos(id) ON DELETE CASCADE,
  CHECK (num_nonnulls(post_id, photo_id) = 1)          -- PG
  -- MySQL: CHECK ((post_id IS NOT NULL) + (photo_id IS NOT NULL) = 1)
);
```

选②时必须在 DDL 注释声明：「本关系无 FK 保护，孤儿清理由 <哪个机制> 负责」。

## Lookup 表（受控值域）

枚举值需要运营配置、携带元数据（展示名、排序、是否启用）时，用 lookup 表替代 CHECK/enum（三方案完整对比见 [data-types.md](data-types.md)）：

```sql
CREATE TABLE order_statuses (
  code       VARCHAR(20) PRIMARY KEY,      -- 'draft' / 'pending' / 'published'
  label      VARCHAR(50) NOT NULL,
  sort_order SMALLINT    NOT NULL,
  is_active  boolean     NOT NULL DEFAULT true
);

ALTER TABLE orders ADD CONSTRAINT fk_orders_status
  FOREIGN KEY (status) REFERENCES order_statuses(code) ON DELETE RESTRICT;
```

加新值 = INSERT 一行，零 DDL、零发版。

## CHECK / UNIQUE / NOT NULL

```sql
price_cents  BIGINT NOT NULL CHECK (price_cents >= 0),
discount_pct SMALLINT NOT NULL DEFAULT 0 CHECK (discount_pct BETWEEN 0 AND 100),
started_at   timestamptz NOT NULL,
ended_at     timestamptz,
CHECK (ended_at IS NULL OR ended_at > started_at),   -- 跨列不变量

email CITEXT UNIQUE NOT NULL,        -- PG：citext 扩展做大小写不敏感唯一
-- MySQL：utf8mb4_0900_ai_ci collation 本身大小写不敏感

UNIQUE (tenant_id, slug)             -- 复合业务键：租户内唯一
```

- **MySQL CHECK 约束 8.0.16 起才执行**，之前版本静默忽略——目标版本更低时改用触发器或 lookup 表。
- NOT NULL 是最廉价的约束：设计时对每列先问「NULL 在业务上代表什么」，答不出来就 NOT NULL。
- **MySQL 的 UNIQUE 索引允许多个 NULL；PG 15+ 可用 `UNIQUE NULLS NOT DISTINCT` 收紧。** 依赖「NULL 也唯一」语义时必须显式处理。

## PG 独有的高级约束

```sql
-- EXCLUDE：区间不重叠（预订、排班系统的杀手锏；MySQL 无等价物，只能应用层加锁）
CREATE EXTENSION btree_gist;
CREATE TABLE bookings (
  room_id BIGINT NOT NULL,
  during  tstzrange NOT NULL,
  EXCLUDE USING gist (room_id WITH =, during WITH &&)
);

-- DEFERRABLE：约束延迟到 COMMIT 检查（行序交换、循环 FK 场景）
UNIQUE (position) DEFERRABLE INITIALLY IMMEDIATE
```
