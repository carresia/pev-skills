# 分区、归档与规模化

触发条件：单表 >5000 万行或 >50GB，或有明确的时间衰减访问模式（新数据热、老数据冷）。**未到量级不要预支复杂度——但 >千万行的表要在设计期想清楚将来的分区键。**

---

## 先穷尽便宜手段

上分区/分片之前，按序检查：

1. 索引与查询优化（EXPLAIN 驱动，见 [keys-and-indexes.md](keys-and-indexes.md)）
2. Covering index 消回表
3. 读写分离（read replica 分走报表/搜索流量）
4. 缓存层（Redis）挡热点读
5. 归档：冷数据移出主表（见下）——**多数「大表问题」其实是归档缺位**

## 表分区（Partitioning）

单库内把大表按键拆成多个物理段；查询带分区键时只扫相关分区（partition pruning）。

| 类型 | 切法 | 典型场景 |
|------|------|----------|
| RANGE | 按值区间（时间最常见） | 订单按月、日志按天 |
| LIST | 按离散值 | 按 region / 业务线 |
| HASH | 按哈希均摊 | 无自然区间、只求打散 |

```sql
-- PostgreSQL：声明式分区（10+）
CREATE TABLE orders (
  id         BIGINT GENERATED ALWAYS AS IDENTITY,
  user_id    BIGINT NOT NULL,
  created_at timestamptz NOT NULL,
  PRIMARY KEY (id, created_at)          -- 分区键必须包含在 PK/UNIQUE 中
) PARTITION BY RANGE (created_at);

CREATE TABLE orders_2026_07 PARTITION OF orders
  FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');
-- 生产：用 pg_partman 自动滚动创建未来分区，防「无分区可插」事故

-- MySQL：原生分区
CREATE TABLE orders ( ... PRIMARY KEY (id, created_at) )
PARTITION BY RANGE COLUMNS (created_at) (
  PARTITION p2026_07 VALUES LESS THAN ('2026-08-01'),
  PARTITION p_max    VALUES LESS THAN (MAXVALUE)   -- 兜底防插入报错
);
```

**硬性代价（评审时逐条核对）：**
- 分区键必须包含于 PK 和所有 UNIQUE 约束 → 「全局唯一 email」这类约束在分区表上无法原生表达；
- 查询不带分区键 = 扫全部分区，可能比不分区更慢；
- MySQL 分区表**不支持外键**（两个方向都不行）；PG 的分区表 FK 支持也有版本门槛（12+ 才能被引用）。

**判断准则：绝大多数查询天然携带分区键（如时间范围）才分区，否则收益为负。**

## 归档（多数场景的正解）

```sql
-- 热表只留活跃窗口，冷数据搬归档表/归档库
INSERT INTO orders_archive SELECT * FROM orders WHERE created_at < '2025-01-01';
DELETE FROM orders WHERE created_at < '2025-01-01';   -- 分批删，见 migrations.md 回填规范
```

时间分区表的归档是降维打击：`ALTER TABLE ... DETACH PARTITION`（PG）/ `DROP PARTITION`（MySQL）秒级完成，免海量 DELETE。**这是「按时间分区」最实在的收益——不是查询加速，是数据生命周期管理。**

## 分区 vs 分片 vs 读扩展

| 手段 | 解决 | 不解决 | 引入成本 |
|------|------|--------|----------|
| Partitioning | 单表管理性、pruning、快速归档 | 单机容量/写吞吐上限 | 低（库内特性） |
| Read replica | 读吞吐 | 写吞吐；复制延迟致读旧 | 中 |
| Sharding | 写吞吐、容量水平扩展 | —— | **极高**：跨分片 JOIN/事务/再平衡全没了 |

Sharding 是最后手段。到那一步：分片键选写入均匀且查询自带的（常用 tenant_id / user_id），并优先评估现成方案（Vitess、Citus、云厂商分布式版）而非自研路由层。

## 大表设计期检查

- [ ] 增长率估算过（行/天），标注 1 年后量级
- [ ] 有时间衰减访问模式的表：定了归档策略与保留窗口
- [ ] 预计 >5000 万行：分区键已设计（即使暂不启用）
- [ ] 计数/聚合读走预计算，不实时 `COUNT(*)` 大表
- [ ] 分页用 keyset（`WHERE id > ? LIMIT n`），不用深 OFFSET
