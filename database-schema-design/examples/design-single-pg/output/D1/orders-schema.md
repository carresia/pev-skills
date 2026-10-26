# 数据库 Schema:订单主库(D1)

> 上游:module/output/M1/module-detail.md(module_design) · 迭代 1 · Verdict PASS
>
> 门禁:目标库齐 true · 实体守恒 true · 落点齐 true · 自查处置 true · 数据流一致 true

本 schema 止于结构与约束。写持久层代码 → incremental-implementation + test-driven-development;拆任务 → planning-and-task-breakdown。

## 库定位(承接上游)

- 存储类型:postgresql
- 承接实体(⊆ 上游声明):orders 订单、order_items 订单明细

### 环境与规模假设

- 方言与版本:PostgreSQL 16
- 规模:日增 50 万,峰值读写 10:1
- 保留期:订单保留 3 年,超期归档

### 承接的上游声明交互

| 上游交互 | 本模块角色 | schema 承接方式 | 溯源 |
| --- | --- | --- | --- |
| I1 用户下单 | 接收方 | D1-I2 唯一索引(order_no)承接幂等去重 | FACT arch 交互 I1 |

## Access Patterns(索引与 denorm 的依据)

| id | 读写模式 | 频率 | 查询形状 |
| --- | --- | --- | --- |
| D1-A1 | 按买家查订单列表 | 高频 | WHERE buyer_id=? ORDER BY created_at DESC |
| D1-A2 | 按订单号点查 | 高频 | WHERE order_no=? |
| D1-A3 | 按订单查明细 | 中频 | WHERE order_id=? |

## 表

| 表 | 目的 | 承接实体 | 主键策略 |
| --- | --- | --- | --- |
| D1-T1 orders | 订单主表 | orders 订单 | BIGINT 自增 |
| D1-T2 order_items | 订单明细行 | order_items 订单明细 | BIGINT 自增 |

### D1-T1 orders

- 目的:订单主表
- 列:id BIGINT PK; order_no VARCHAR(32) UNIQUE NOT NULL; buyer_id BIGINT NOT NULL; amount DECIMAL(12,2) NOT NULL; status SMALLINT NOT NULL; created_at timestamptz NOT NULL
- 主键:BIGINT 自增(单库写入,无分片计划)
- 约束:UNIQUE(order_no); CHECK status IN (0,1,2); 关键列 NOT NULL
- WHY:order_no 生成列承载业务语义,PK 不暴露

### D1-T2 order_items

- 目的:订单明细行
- 列:id BIGINT PK; order_id BIGINT NOT NULL; sku VARCHAR(64) NOT NULL; qty INT NOT NULL; price DECIMAL(12,2) NOT NULL
- 主键:BIGINT 自增
- 约束:FK order_id→orders(id) ON DELETE CASCADE; qty NOT NULL

## 索引依据

| 索引 | 表 | 定义 | 服务 access pattern | WHY |
| --- | --- | --- | --- | --- |
| D1-I1 | D1-T1 | INDEX (buyer_id, created_at DESC) | D1-A1 | 买家维度列表排序 |
| D1-I2 | D1-T1 | UNIQUE INDEX (order_no) | D1-A2 | 订单号点查 + 幂等去重 |
| D1-I3 | D1-T2 | INDEX (order_id) | D1-A3 | FK 列手动建索引 |

## 演进与迁移策略

- 策略:expand-contract + Flyway 版本化
- 兼容规则:删列/改类型/改约束视为破坏性变更,先双写一个版本周期;UP/DOWN 成对;大表变更评估锁级别
- 大表计划:订单 3 年归档到 orders_archive;千万行后按 created_at RANGE 分区

## 关键取舍

| 决策 | 选择 | 理由 | 代价 | 替代方案 |
| --- | --- | --- | --- | --- |
| 主键自增 vs UUIDv7 | BIGINT 自增 | 单库写入,时间有序避免页分裂 | 跨库合并需映射表,且暴露业务量 | UUIDv7 BINARY(16) |

## 给下游 Skills 的交付物

- incremental-implementation:orders/order_items 的 DDL 与约束清单
- test-driven-development:order_no 唯一约束与 status CHECK 约束的用例
- planning-and-task-breakdown:按表拆迁移任务
- documentation-and-adrs:主键选型 ADR
