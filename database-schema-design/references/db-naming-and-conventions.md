# 命名规范与设计硬规则(数据库 schema 设计)

默认规范,源自 cospowers 的《MySQL 开发规范》(规则 ID 保留可溯源)与数据库设计
模板的命名规范表。**项目已有库/表命名风格优先遵循**(勘察 survey_codebase 结论);
仅新库、新表、新索引在项目无既有风格时按本规范执行。规则 ID 前缀 `MYSQL-` 的条目
适用于 MySQL;非 MySQL 库遵循通用条目(命名、见名知意、索引依据),方言差异以
对应 references 为准。

## 命名规范

| 对象 | 规范 | 示例 |
|---|---|---|
| 库 | `项目_环境`,小写下划线 | `myapp_prod` |
| 表 | `模块_业务含义`(或项目既有风格),小写下划线、字母开头、**单数形式**、见名知意、一般 ≤3 个英文单词,禁保留字 | `order_order_item` / `user_account` |
| 字段 | 业务含义,小写下划线、见名知意,禁保留字 | `buyer_id`、`order_no` |
| 主键约束 | `pk_表名` | `pk_orders` |
| 外键约束 | `fk_源表_目标表` | `fk_order_user` |
| 普通索引 | `idx_字段1_字段2`(MYSQL-IDX-02 [强制]) | `idx_buyer_id_created_at` |
| 唯一索引 | `uniq_字段1_字段2`(MYSQL-IDX-02 [强制]) | `uniq_order_no` |

**见名知意(MYSQL-TBL-04 [建议])**:`a1`、`tbl1`、`data2` 这类无意义命名禁止;
缩写只用在团队公认处(buyer_id 可以,byid 不行)。**MYSQL-TBL-03 [强制]**:库名、
表名、字段名只用英文字母、数字、下划线,全部小写,字母开头,禁连字符(-)与保留
关键字(`order`、`group` 等)。

## 设计硬规则(建表时逐条对照)

| 规则 ID | 等级 | 内容 |
|---|---|---|
| MYSQL-TBL-01 | 强制 | InnoDB 引擎;字符集 utf8mb4(规范原文写 utf8,以其 DDL 示例与本 skill 红线为准取 utf8mb4——utf8 是 3 字节阉割版) |
| MYSQL-TBL-02 | 强制 | 所有表有自增主键 `id`,禁止联合主键;联合唯一改用自增主键 + 联合唯一索引(分布式 ID 场景见 keys-and-indexes.md,选型记 DECISION) |
| MYSQL-TBL-05 | 建议 | 单表数据量控制在 500 万以内;超限走分区/分表/归档(partitioning-and-scale.md) |
| MYSQL-TBL-06 | 建议 | 不在数据库存文件等大二进制,防随机 IO 与体积失控 |
| MYSQL-FLD-01 | 强制 | 避免 TEXT/BLOB 大字段(内存临时表不支持,不能默认值、难排序建索引);大文本评估独立存储 |
| MYSQL-FLD-02 | 建议 | 避免 NULL:能 NOT NULL 就 NOT NULL,给默认值(数字 0/空串) |
| MYSQL-FLD-03 | 建议 | varchar 按业务实际定长,不过度预留(VARCHAR(255) 无脑用是反模式) |
| MYSQL-FLD-04 | 强制 | 小数用 DECIMAL,禁 FLOAT/DOUBLE(金额见 data-types.md) |
| MYSQL-IDX-03 | 建议 | 仅在需要时建索引;单表索引总数 ≤5,单字段索引 ≤3,无冗余重复索引 |
| MYSQL-IDX-04 | 建议 | 低基数列(状态/类型/性别)不建独立索引;频繁更新列不建索引 |
| MYSQL-IDX-08 | 强制 | 复合索引最左前缀匹配;范围查询字段放最后(列序细则见 keys-and-indexes.md) |
| MYSQL-BAN-01 | 强制 | 禁止存储过程——计算上移服务层 |
| MYSQL-BAN-02 | 强制 | 禁止视图 |
| MYSQL-BAN-03 | 强制 | 禁止触发器 |
| MYSQL-BAN-04 | 强制 | 禁止 Event 事件调度器 |

禁止项的共同理念:数据库只擅长存储与索引,CPU 计算上移服务层,高并发下这些
特性会拖死数据库且无法横向扩容。

## 范围说明

《MySQL 开发规范》的 **SQL 编写** 与 **ORM 使用** 两节(MYSQL-SQL-01~08、
MYSQL-ORM-01~07)约束的是实现期代码,归 incremental-implementation /
code-review 阶段,不在 schema 设计产物中强制;但 schema 设计不得逼实现违反它们
(如索引设计让高频查询只能全模糊 LIKE、约束设计迫使事务里做 IO)。
