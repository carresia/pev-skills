# 数据类型选择（MySQL / PostgreSQL）

总原则：**最小够用的类型 + 显式约束**。类型即文档，类型即第一层校验。

---

## 字符串

| 场景 | MySQL | PostgreSQL | 备注 |
|------|-------|-----------|------|
| 定长代码 | `CHAR(2)` | `char(2)` | 国家码、币种码 |
| 变长短文本 | `VARCHAR(n)` | `text`（或 `varchar(n)`） | PG 中两者性能相同，社区惯用 `text` + `CHECK (length(...))` |
| 长文本 | `TEXT` | `text` | 文章、描述 |

**MySQL 字符集：永远 `utf8mb4`。** `utf8` 是 3 字节阉割版（utf8mb3），存 emoji/生僻字直接报错。8.0 默认 collation 用 `utf8mb4_0900_ai_ci`。

```sql
-- MySQL 建表显式声明，不依赖实例默认值
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
```

VARCHAR 长度按业务含义定，不无脑 255：email → `VARCHAR(254)`（RFC 5321 上限）、E.164 手机号 → `VARCHAR(16)`、URL → `VARCHAR(2048)`。

## 数值

| 宽度 | MySQL | PostgreSQL | 用途 |
|------|-------|-----------|------|
| 1 字节 | `TINYINT` | 无（用 `smallint`） | 状态码 |
| 2 字节 | `SMALLINT` | `smallint` | 小计数 |
| 4 字节 | `INT` | `integer` | 一般计数 |
| 8 字节 | `BIGINT` | `bigint` | ID、大计数 |
| 精确小数 | `DECIMAL(p,s)` | `numeric(p,s)` | 金额、费率 |
| 浮点 | `FLOAT`/`DOUBLE` | `real`/`double precision` | 仅科学计算、坐标 |

注意：
- **PG 没有 TINYINT，也没有 UNSIGNED。**
- MySQL 的 `UNSIGNED` 慎用（跨库移植差、JDBC/ORM 边界坑多）；需要更大范围直接升 `BIGINT`。
- ID 列直接用 `BIGINT`。`INT` 21 亿上限在活跃系统里会被耗尽，事后改 PK 类型是重大手术。

## 金额

绝不用 FLOAT/DOUBLE（二进制浮点无法精确表示 0.1）。两种正解：

```sql
-- 方案 A：DECIMAL + 独立币种列（通用记账推荐）
amount   DECIMAL(19,4) NOT NULL,          -- 4 位小数容纳分摊、汇率中间值
currency CHAR(3)       NOT NULL,          -- ISO 4217：'CNY' / 'USD'

-- 方案 B：最小货币单位整数（避免一切小数运算）
amount_cents BIGINT NOT NULL,             -- 以「分」计价
```

多币种系统金额列必须配 currency 列——只存数字的金额是不完整的值。

## 日期时间

| 需求 | MySQL | PostgreSQL |
|------|-------|-----------|
| 事件时刻（推荐默认） | `DATETIME(6)`，应用层统一写 UTC | `timestamptz` |
| 仅日期 | `DATE` | `date` |
| 仅时间 | `TIME` | `time` |

- **MySQL `TIMESTAMP` 有 2038 问题**（上限 2038-01-19），且随会话时区隐式转换。远期时间（合同到期、证件有效期）必须用 `DATETIME`。
- **PG 默认选 `timestamptz`**：内部统一存 UTC 时刻，按会话时区渲染；裸 `timestamp` 容易被隐式时区坑。
- 审计列的两方言写法：

```sql
-- MySQL：数据库层自动维护
created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
           ON UPDATE CURRENT_TIMESTAMP(6),

-- PostgreSQL：没有 ON UPDATE 语法，updated_at 由 BEFORE UPDATE 触发器或应用层维护
created_at timestamptz NOT NULL DEFAULT now(),
updated_at timestamptz NOT NULL DEFAULT now(),
```

## 布尔

```sql
is_active boolean    NOT NULL DEFAULT true   -- PostgreSQL
is_active TINYINT(1) NOT NULL DEFAULT 1      -- MySQL 惯例
```

## Enum / 状态 / 类型列 —— 三方案权衡

**没有全场景铁律。按下表选，并在 DDL 注释里记录选择依据：**

| 方案 | 完整性 | 可读性 | 加值成本 | 适用 |
|------|--------|--------|----------|------|
| ① 字符串 + CHECK | DB 层强制 | 高，数据自解释 | 改 CHECK（PG 短锁；MySQL 见下方版本警告） | 值少且稳定 —— **默认推荐** |
| ② Lookup 表 + FK | 最强（外键） | 高，可带元数据 | INSERT 一行，零 DDL | 值需运营配置、带附加属性（展示名、排序） |
| ③ 整数码 + CHECK | 需手写 CHECK | 低，需查映射 | 改 CHECK | 极端写入密集、跨异构库同步、存储敏感 |

```sql
-- ① 字符串 + CHECK（PostgreSQL / MySQL 8.0.16+）
status VARCHAR(20) NOT NULL DEFAULT 'draft'
  CHECK (status IN ('draft', 'pending', 'published')),

-- ② Lookup 表 + FK
CREATE TABLE order_statuses (
  code       VARCHAR(20) PRIMARY KEY,
  label      VARCHAR(50) NOT NULL,     -- 展示名
  sort_order SMALLINT    NOT NULL
);
-- orders.status REFERENCES order_statuses(code)

-- ③ 整数码：必须同时有 CHECK（防脏值）和映射注释（防失忆）
status TINYINT NOT NULL DEFAULT 0 COMMENT '0=draft 1=pending 2=published'
  CHECK (status IN (0, 1, 2)),
```

**版本警告：MySQL 的 CHECK 约束 8.0.16 起才真正执行，之前版本解析后静默忽略。** 目标版本 <8.0.16 时，方案①③的 DB 层防线不存在，改用方案②或触发器。

**原生 ENUM 类型的真实情况**（纠正流传的错误说法）：

- MySQL `ENUM`：在**末尾追加**值是 metadata-only（INPLACE，不重写表）；插入中间或删除值才重建表。真正的缺点是：值域藏在列定义里、跨库移植差、部分 ORM 映射别扭——可用，但不作首选。
- PG `CREATE TYPE ... AS ENUM`：`ALTER TYPE ... ADD VALUE` 代价极低；缺点是**不能删值、难以重排**。值域长期稳定时是干净的选择。

## JSON 列

| 用 | 不用 |
|----|------|
| 稀疏/异构属性（商品自定义规格） | 需要 FK/CHECK 约束的核心字段 |
| 第三方 payload 原样归档 | 高频 WHERE / JOIN / ORDER BY 的字段 |
| 真 schema-less 且整体读回 | 需要跨行聚合统计的字段 |

```sql
-- PostgreSQL：jsonb + GIN 索引（支持 @> 包含查询）
attrs jsonb NOT NULL DEFAULT '{}';
CREATE INDEX idx_products_attrs ON products USING GIN (attrs);

-- MySQL：JSON + 生成列抽关键字段建索引
attrs JSON,
brand VARCHAR(50) GENERATED ALWAYS AS (attrs->>'$.brand') STORED,
KEY idx_products_brand (brand)
```

**红线：核心业务字段一旦进 JSON，约束、索引、统计全部降级。先建列，JSON 只兜底。**

## 生成列（Generated Columns）

派生值想建索引或强制一致时使用（两方言均支持 8.0 / PG 12+）：

```sql
total_cents BIGINT GENERATED ALWAYS AS (quantity * unit_price_cents) STORED
```
