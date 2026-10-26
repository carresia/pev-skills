# Schema 设计校验清单（唯一真源）

用途：交付前自查 / 评审已有 schema。评审时输出按 **Critical（数据损坏或事故风险）/ Warning（性能或演进隐患）/ Suggestion（改进项）** 分级。

---

## 前置（出 DDL 之前）

- [ ] 主要 access patterns 已列出（最高频 3~5 个读写）
- [ ] 规模量级已估（行数、增长率、读写比）
- [ ] 目标方言 + 版本已确认（MySQL/PG/Mongo；版本影响可用特性）
- [ ] SQL vs NoSQL 选型有依据（非「感觉灵活」）
- [ ] 未澄清项已写入「假设声明」

## 主键与标识

- [ ] 每表有 PK；ID 列用 BIGINT（不用 INT）
- [ ] 分布式/需预生成 ID：UUIDv7/ULID 存 BINARY(16)/uuid —— **禁止随机 UUIDv4 做聚簇 PK、禁止 CHAR(36) 存 UUID**
- [ ] 未用业务含义字段（email/编码）做 PK
- [ ] 对外暴露 ID 若需防枚举：public_id 与内部 PK 分离

## 数据类型

- [ ] 金额：DECIMAL 或整数最小货币单位；多币种配 currency 列；**无 FLOAT**
- [ ] 时间：MySQL 用 DATETIME（防 2038）/ PG 用 timestamptz；统一 UTC
- [ ] MySQL 字符集 utf8mb4（**禁 utf8**）
- [ ] VARCHAR 长度有业务依据
- [ ] enum/状态列：三方案（CHECK / lookup 表 / 整数码+CHECK）择一并记录依据；MySQL <8.0.16 不依赖 CHECK
- [ ] JSON 列仅装非核心的灵活属性；需约束/索引/聚合的字段是真实列

## 约束

- [ ] 所有关系有 FK；每个 FK 显式声明 ON DELETE（默认 RESTRICT；CASCADE 仅纯从属数据）
- [ ] 业务必填列 NOT NULL；每个 nullable 列答得出「NULL 代表什么」
- [ ] 业务唯一键有 UNIQUE（多租户下以 tenant_id 打头）
- [ ] 值域/跨列不变量有 CHECK（price >= 0；ended_at > started_at）
- [ ] 每表有 created_at / updated_at（PG 的 updated_at 有维护机制）

## 索引

- [ ] 每个 FK 列有索引（**PG 不自动建，逐个核对**）
- [ ] 每个二级索引能指出服务的具体查询；指不出的删除
- [ ] 复合索引列序：等值 → 排序 → 范围；无被前缀覆盖的冗余索引
- [ ] 热点子集查询用 partial index（PG）/ 生成列（MySQL）
- [ ] 软删除表的唯一约束限定于活行（partial unique / alive 生成列）
- [ ] 关键查询附 EXPLAIN 预期或标注「上线后验证」

## 建模

- [ ] OLTP 达到 3NF；每处 denorm 注明服务查询与同步机制
- [ ] 时点事实（下单价格、快照）已落表——不误判为范式违例
- [ ] 并发更新敏感表有乐观锁 version 或明确的锁策略
- [ ] 软删除表：全局查询 scope + 唯一约束处理齐备；或明确不用软删除的理由
- [ ] 多租户：tenant_id 在每张业务表且 NOT NULL，索引/UNIQUE 以其打头

## Migration（改已有表时）

- [ ] UP + DOWN 成对；不可逆步骤显式标注「DOWN 不恢复数据」
- [ ] 向后兼容：改名/改类型走 expand-contract 多步，不直接 RENAME
- [ ] 锁影响已评估：PG 加索引用 CONCURRENTLY、加约束用 NOT VALID 两步法；MySQL 声明 ALGORITHM/LOCK 期望
- [ ] 大表回填分批提交，不单条 UPDATE 全表
- [ ] 在 staging 以生产级数据量演练过；标注预估耗时

## 规模（预计 >千万行的表）

- [ ] 增长率与 1 年后量级已标注
- [ ] 时间衰减数据有归档策略与保留窗口
- [ ] >5000 万行：分区键已设计（分区键进 PK/UNIQUE 的代价已确认；MySQL 分区表无 FK 已确认）
- [ ] 深分页用 keyset，不用大 OFFSET

## 安全

- [ ] 密码仅存强哈希（bcrypt/argon2）；PII 标记并有加密/脱敏方案
- [ ] 应用账号最小权限；读写分离账号
- [ ] 全部参数化查询（评审时抽查拼接 SQL）

## MongoDB（适用时）

- [ ] 建模从 access patterns 出发；embed/reference 决策有依据
- [ ] 无无界数组；被多父引用的数据不整体内嵌
- [ ] Extended reference 只嵌稳定字段且写明同步机制
- [ ] 集合有 $jsonSchema validator；文档带 schema_version
- [ ] 索引符合 ESR；关键查询 explain 验证 IXSCAN
- [ ] 核心不变量不依赖多文档事务（依赖则重切文档边界或改 SQL）
