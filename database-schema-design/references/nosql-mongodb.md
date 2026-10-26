# NoSQL 文档建模（MongoDB）

范式转换：关系库先建规范模型再适配查询；**MongoDB 从查询出发设计文档——「一起读的数据放一起存」。** 列不出主要 access patterns 就还没到建模的时候。

---

## Embed vs Reference（核心决策）

| 因素 | Embed | Reference |
|------|-------|-----------|
| 访问 | 总是随父读 | 独立访问/独立更新 |
| 基数 | 1:few（有界，≤几百） | 1:many / 无界 |
| 增长 | 子项数量有上限 | 子项无限增长（评论、日志） |
| 更新频率 | 低频 | 高频且独立 |

```javascript
// Embed：订单行项随订单读写，天然内嵌；快照价格是时点事实
{
  _id: ObjectId(),
  user_id: ObjectId(),                       // reference：用户被多处引用且独立更新
  status: "pending",
  items: [                                    // embed：1:few、随单读、下单后不变
    { product_id: ObjectId(), name_snapshot: "Keyboard", qty: 2, price_cents: 29900 }
  ],
  total_cents: 59800,
  created_at: ISODate()
}
```

**三条铁律：**
1. **文档硬上限 16MB**，无界数组必炸——评论、事件流、粉丝列表永远 reference；
2. 内嵌数组元素需要独立分页/排序/权限时，说明它是独立实体 → reference；
3. 被多个父引用的数据（用户资料）内嵌即冗余，更新要多处同步 → reference，或只内嵌稳定快照字段（见下）。

## Extended Reference（受控冗余）

Reference 但高频列表页需要对方 1~2 个字段 → 内嵌**稳定子集**，省 `$lookup`：

```javascript
{ _id: ..., user: { _id: ObjectId("..."), name: "Jane" },   // 只嵌 id+name，不嵌整个 user
  total_cents: 59800 }
```

只嵌少变字段；源变更时的同步机制（应用层双写 / Change Stream 触发）必须在设计文档里写明。

## 常用模式速查

| 模式 | 问题 | 做法 |
|------|------|------|
| Subset | 文档大但列表页只用头部字段 | 热字段留主文档，长尾拆 detail 集合 |
| Bucket | 时序/事件高频小文档 | 按时间窗聚桶：一文档存一小时的点位数组 |
| Computed | 高频聚合读 | 写时维护 `stats.total`，免实时聚合 |
| Schema Versioning | 文档结构演进 | 文档带 `schema_version` 字段，读时兼容、写时升级、后台批量迁移 |

Schema Versioning 是关系库 migration 的替代物——Mongo 没有 ALTER TABLE，结构演进必须在应用层显式管理，新集合从 v1 就带版本字段。

## 索引：ESR 规则

复合索引列序 = **Equality → Sort → Range**：

```javascript
// 查询：find({ user_id: X, status: "pending", created_at: { $gt: d } }).sort({ created_at: -1 })
db.orders.createIndex({ user_id: 1, status: 1, created_at: -1 })
//                       Equality──┴─────────┘   Sort+Range──┘
```

```javascript
db.users.createIndex({ email: 1 }, { unique: true })
db.orders.createIndex({ "items.product_id": 1 })                      // multikey（数组字段）
db.messages.createIndex({ expires_at: 1 }, { expireAfterSeconds: 0 }) // TTL 自动清理
db.orders.createIndex({ user_id: 1 }, { partialFilterExpression: { status: "pending" } })
```

验证：`explain("executionStats")` 看 `IXSCAN`（好）vs `COLLSCAN`（坏），`totalDocsExamined` 应接近 `nReturned`。

## Schema 校验（Mongo 也要约束）

「schema-less」指灵活，不是放任。生产集合一律加 JSON Schema 校验：

```javascript
db.createCollection("orders", {
  validator: { $jsonSchema: {
    required: ["user_id", "status", "total_cents", "created_at"],
    properties: {
      status: { enum: ["pending", "paid", "shipped", "cancelled"] },
      total_cents: { bsonType: "long", minimum: 0 }
    }
  }},
  validationLevel: "moderate"     // 老文档宽限，新写入强制
})
```

## 事务与不变量

Mongo 4.0+ 有多文档事务，但**性能显著劣于单文档原子写——依赖多文档事务维持核心不变量，通常说明文档边界切错了**。把需要原子变更的数据装进同一文档（单文档写天然原子）。跨文档强一致不变量密集的领域（记账、库存扣减）本就是关系库的主场，回看 [normalization-and-modeling.md](normalization-and-modeling.md) 的选型表。

## Mongo 反模式

| 反模式 | 后果 | 纠正 |
|--------|------|------|
| 无界数组 | 逼近 16MB、重写放大 | Reference / Bucket |
| 把 Mongo 当关系库（处处 $lookup） | 慢且丢关系库的约束红利 | 重切文档边界，或换 PG |
| 集合数爆炸（per-tenant collection） | 索引与内存开销失控 | 共享集合 + tenant_id 字段 |
| 无 schema 校验 | 脏文档静默入库 | $jsonSchema validator |
| 大海捞针不建索引 | COLLSCAN 拖垮集群 | ESR 建索引 + explain 验证 |
