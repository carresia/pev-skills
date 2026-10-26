# 拆解流程指南

> 本文件是知识库,按需读取。**SKILL.md 是工作流,这里是需要想清楚时才翻的地方。**
> 上游输入统一称 `spec_source`(工程 Spec 优先,已批准 PRD 亦可)。文中凡说"需求""PRD",
> 都读作 `spec_source`。缺口(上游缺失或自相矛盾的产品行为)不是硬停,浮出后交给用户
> 三选一;它在三个位置落盘,对应三个阶段:EXECUTING 发现时记入 artifact 的
> `unresolved`;用户选"回上游/上游补充"时转记入 state 的 `spec_gaps`(仅
> WAITING_FOR_SPEC 期间非空);用户拍板时记为 Evidence Ledger 的 DECISION 条目。

## PEV 在这个 skill 里是什么

PEV 是本 skill 采用的**执行架构**,不是 skill 本身。Planner、Executor、Verifier 是同一
skill 下的三种执行机制,共享一个结构化 state;对应现实中的协作过程——**开发团队拿着已冻结的
Spec 开拆解会**:主持人先定策略与批次,逐 Epic 建树,独立评审打回,拆不动的地方浮出给用户定夺。

三者互锁的边界(任何时候不得违反):

| 角色 | 不许做什么 |
|---|---|
| Planner | 不产出行为目录,只产出拆解规划(策略 + 批次) |
| Executor | 不发明产品行为;不做技术选型;不拆代码任务 |
| Verifier | 不直接修改结果,只输出 verdict + scores + required_changes |

**角色的实现方式可以降级,依据落盘这一条不能降级。** 有子代理能力时 spawn 只读子代理;
无子代理时同会话切角色、只从文件重新推导。两种方式下 Verifier 的判断依据都只有文件——
EXECUTING 阶段的推理不在文件里,就当作不存在。

## 运行目录与产物

`.pev/` 是 PEV 家族三个 skill(product-manager、requirement-clarify、本 skill)
共享的根目录,按需求目标分轮次目录 `prd-<今日日期>/`,同日新开多个轮次时目录名加
`-2`、`-3` 后缀(其余命名与创建规则见 product-manager)。本 skill 的工作目录是轮次
目录下的 `decompose/`;轮次跟随上游:上游在 `.pev/` 某轮内→同轮,外部路径→新开轮次:

```text
.pev/<轮次>/
├── pm/                           # product-manager 的产物,合法溯源源
├── rc/                           # requirement-clarify 的产物(Evidence Ledger、澄清记录),合法溯源源
└── decompose/                    # 本 skill 的工作目录
    ├── state.json                # 共享状态(schemas/state.schema.json),含 spec_source
    ├── iterations/
    │   ├── 01-plan.json          # 每轮产物按 schema 校验
    │   ├── 01-artifact.json
    │   └── 01-verification.json
    └── output/                   # PASS 后按 templates/ 渲染的最终交付物
```

上游**引用不复制**:`state.spec_source` 只记录路径(优先 `.pev/<轮次>/rc/output/spec.md`,
用户直接给的 PRD 亦可)。同轮 `rc/` 下的中间产物(Evidence Ledger、澄清记录)是合法溯源源,
按需读取,不拷入 `decompose/`。

文件名中的 `<N>` 是迭代号。REVISE 轮复用原 Plan,因此只有 `<N>-artifact.json` /
`<N>-verification.json` 而没有 `<N>-plan.json`——**这是正常的,不是缺文件**。

用户明确要求重开时:把该轮 `decompose/` 归档为 `decompose.bak-<日期>/`(不动同轮的
`pm/`、`rc/`),再在本轮次内重建——这是唯一允许覆盖已有产物的入口。

## 拆解算法

### 1. 输入处理:归一化

- 按句边界切分(`.` `!` `?` `\n`)
- 去掉填充语("我们需要""我想要""请")
- 标出关键名词(实体、系统、功能)与动词(动作、能力)
- 提取**产品级**约束:合规、隐私、权限、时限

技术栈、框架选型一类不是本 skill 的输入,不进这一步——那是 `architecture-design` 的事。

### 2. 范围判定

```text
单一功能(< 5 个 story)     → 单 Epic → Feature → Story(仅一个 Epic)
多功能(5-20 个 story)       → Epic → Feature → Story
大型计划(20+ 个 story)      → Epic → Feature → Story;超出部分记入 stop_conditions
```

### 3. 隐式需求:只作线索,不作依据

看到"认证"你会想到用户管理、会话、访问控制——但这些**不能自动推导为行为**。
隐式需求的唯一用途是**提示你去 `spec_source` 里找锚点**:

- 找得到 → 按 FACT 产出,`trace` 指向该处
- 找不到 → 进 `unresolved`,artifact 置 `status="blocked"`,走三选一

**不替用户承担产品风险,不"采用合理默认值"。** "默认现代技术栈就是邮箱密码 + Google SSO"
这类推断在别处也许成立,在这里是越界:认证方式是产品行为,只有 Spec 或用户决定能定它。

### 4. 决策门

遇到歧义时先问一句:**这个歧义会改变范围、用户可见行为、安全、合规或数据完整性吗?**

- 会 → 不能自行决定。进 `unresolved` → `status="blocked"` → 三选一(见 SKILL.md Input Gate)
- 不会,且属非产品性技术假设 → 可以采用,但必须在 `assumptions` 里标注

### 5. 溯源锚点

不再分配 `REQ-{n}` 之类的自造 ID——**溯源锚点就是上游自己的位置**:

- FACT 锚点:`spec_source §3.1` 形式的章节位置,或同轮 `.pev/<轮次>/rc/` 产物里的条目
- DECISION 锚点:用户决定落盘的位置,如 `01-artifact decisions#d2`

每个 story / scenario 的 `trace` 填其一,并同步进 Evidence Ledger。校验脚本强制
`type=FACT|DECISION` 的条目必须有非空 `evidence`。

### 拆解策略

#### 自顶向下(默认)

```text
需求
  └── Epic(业务能力)
        └── Feature(功能域)
              └── Story(用户价值)  ← 本 skill 的最低层
```

- 每层 3-7 项(认知组块上限)
- Epic 之下最多再嵌 3 层
- 叶子节点必须可估(Story ≤8 故事点)

#### 自底向上(适合已高度条目化的上游)

```text
需求
  └── 先识别具体行为点
        └── 聚合成 Story
              └── 聚合成 Feature
                    └── 聚合成 Epic
```

上游给的是细粒度行为清单而非高层目标时用这个。

### ID 生成

```text
EPIC-{n}            → 顶层 Epic
FEATURE-{e}.{n}     → Epic e 下的 Feature
STORY-{e}.{f}.{n}   → Epic e 的 Feature f 下的 Story
```

**没有 TECH 层**——实现任务不属于本 skill。

```text
EPIC-1: 用户认证
  FEATURE-1.1: 邮箱登录
    STORY-1.1.1: 用户可用邮箱注册
    STORY-1.1.2: 用户可用邮箱登录
```

### 精修提示模板

```text
用户提出以下精修要求:
{refinement_request}

当前目录:
{current_decomposition}

应用该改动并给出更新后的目录。保持所有 ID、父子关系、依赖一致。
```

每条精修指令 = 一次 DECISION,锚点形如 `02-artifact decisions#d3`,同步进 Evidence Ledger。

---

## 场景覆盖算法

### 第一步:两级表态建立适用集

适用性大部分由**项目域**决定(有没有资金流、是否纯内部工具),小部分是 story 特有的。
因此表态分两级,**不要逐 story 重复全局事实**。类别共 **11 个**:前 5 个是行为类
(场景长什么样),后 6 个是风险类(场景防住了什么):

| 行为类 | 含义 |
|---|---|
| `normal` | 典型成功路径 |
| `exception` | 非法输入、失败、超时、冲突、拒绝 |
| `boundary` | 空 / 上限 / 下限 / 边界外一点 / 并发边缘 |
| `permission_state` | 谁能做、在什么状态下能做、什么被禁止 |
| `dependency` | 上游产品依赖不可用时的行为 |

| 风险类 | 含义 |
|---|---|
| `security` | 注入、越权、凭据泄露等安全风险 |
| `authorization` | 授权与所有权边界 |
| `funds` | 资金、计价、退款 |
| `privacy` | 个人信息、留存、导出 |
| `irreversible` | 不可撤销动作(删除、发送、扣款) |
| `data_integrity` | 数据冲突、顺序、精度、时区、兼容 |

**全局层**写进 artifact 根的 `category_defaults`(第一个 artifact 定一次,迭代间不变;
变更须记 DECISION):

```json
"category_defaults": {
  "applicable": ["normal", "exception"],
  "inapplicable": [{"what": "funds", "reason": "本项目无任何资金流"}]
}
```

**story 层**只写偏离(可选,无偏离则整个省略):

```json
"coverage_assessment": {
  "applicable_add": ["boundary", "security"],
  "inapplicable_add": [{"what": "privacy", "reason": "仅改展示名,不触达个人信息"}]
}
```

有效适用集 = 全局 applicable ∪ applicable_add − inapplicable_add,由校验脚本合并计算。

规则:

- **全局 applicable 宜小而稳**:通常至少 normal/exception;声明即要求每个 story 都有证据
  (行为类=场景 class,风险类=covers)。全局 `inapplicable` 是最大的分母操纵面
  (一次豁免 = 所有 story 免检),必须有项目级理由。
- **story 偏离是常态不是负担**:有额外适用面就加 `applicable_add`,声明须配套场景证据;
  特有豁免才写 `inapplicable_add`,理由必须具体到本 story("不适用"这类空话不算)。
- **沉默 = 豁免**:未决类别(全局两边都没写、story 也没写)视为本 story 不适用,无需任何
  声明——这是省掉逐 story 全量表态的关键,代价是该处机械不可见,由 Verifier 逐 Story 扫。
- 校验脚本 R5 查两级结构合法性(无重复/交集/同侧冗余、豁免有非空理由),
  R6 从合并后的有效适用集算分母,R7 查全局表态跨迭代一致性(变更须有 DECISION 背书)。
- **这就是分母。** 覆盖率不靠人估,由脚本算出。

### 第二步:选取场景

用风险代表,不做组合爆炸:

- **等价类**:每个实质不同的合法/非法类取一个代表
- **边界值**:确切边界 + 两侧最近值
- **状态迁移**:每条允许的迁移,以及每条有后果的禁止迁移
- **判定表**:仅当规则相互影响时才做组合
- **成对组合**:参数多且相互独立、穷举不现实时用
- **故障注入**:每条有后果的外部依赖失败策略各一

一个场景可以同时覆盖多个类别,只要它的 Given/When/Then 把每个结果都写明了。
**场景覆盖了某个风险类,必须在该场景的 `covers` 里声明**,否则该风险类算未覆盖:

```json
{"class": "exception", "given": "...", "when": "...", "then": "...", "covers": ["security"]}
```

### 第三步:计算与门禁

两个百分比由 `scripts/validate.py` 从 artifact 直接算出并打印,**不由 Verifier 填报**:

```text
scenario_category_pct = 已覆盖的行为类数 / 适用的行为类数 × 100
critical_risk_pct     = 已覆盖的风险类数 / 适用的风险类数 × 100   (仅 P0/P1 story)
```

其中"已覆盖"= story 里有场景的 `class` 等于该行为类,或场景的 `covers` 包含该风险类。
分母为 0 记 100(无适用即无缺口)。

门禁:

- 总门禁:场景类别覆盖 **≥ 90%**
- 关键门禁:P0/P1 story 的适用风险类必须 **100%**

**Verifier 的职责不是算这个数,而是质疑两级声明与沉默豁免**(判据见
rubrics/decomposition-review.md 维度 6):分母是唯一能被操纵的地方,所以要盯分母。
脚本另打印逐 story 适用未覆盖清单(已声明适用但无场景证据的类别,非门禁)——
单轮评审逐 story 扫有漏检风险,机械检出不依赖评审注意力,由 Verifier 逐条处置:
补场景进 required_changes,或接受残留写进 warnings。

**这个指标衡量的是"计划中的行为风险覆盖",任何时候不得当作代码覆盖率呈现。**

---

## 依赖图算法

只记**产品级依赖**——哪个行为必须先存在。技术/构建依赖不属于本目录。

### 直接依赖

从上游的显式关系里读:

```text
"先做认证,再做 SSO"
  → FEATURE-1.2 blocked-by FEATURE-1.1(显式顺序)

"SSO 复用登录会话模型"
  → STORY-1.2.1 blocked-by STORY-1.1.2(产品级前置,不是构建依赖)
```

### 解析顺序

```text
第一批:无依赖项(可立即开始)
第二批:依赖项全部落在第一批的
第三批:依赖项全部落在前两批的
...重复直到全部归位
```

检测到环 → **标出并拆/重挂,不硬排顺序**。

---

## 拆解边界情况处理

### 超大需求(潜在条目 > 20)

**分块 + 排序**:

1. 请用户指出最高优先区域
2. 只对 top 3 epic 做细拆
3. 其余列为占位项并给粗略规模
4. 余下部分建一个"第二批"分组承接,并记入 `stop_conditions`

### 模糊需求

先查 `spec_source`,再查同轮 `.pev/<轮次>/rc/` 中间产物与 `product-context.md`(仅非产品性上下文)。
**追踪不到不要猜**——进 `unresolved`,走三选一:

```text
⚠️ 缺口:上游未定义「认证方式」
   卡住:STORY-1.1.1 / STORY-1.1.2
   推荐答案:邮箱密码 + Google SSO(仅供参考,不是默认值)
   请选:① 回上游重新提 ② 上游补充 ③ 你直接拍板(记为 DECISION)
```

### 重复检测

评审时按以下线索找重复:

- 归一化标题匹配(忽略大小写、去停用词)
- 验收标准重叠 > 80%
- 依赖模式相同

检出后**先 merge 再进预览**,不把两个同类项一起交上去:

```text
⚠️ 疑似重复:
  STORY-1.1.1: "用户可用邮箱注册"
  STORY-1.2.1: "用户邮箱注册"
  建议:合并进 STORY-1.1.1,验收标准合并
```

### 跨切关注点

横跨多个 Feature 的**产品**关注点:

1. 在依赖映射阶段识别
2. 影响 3+ Feature → **提升为独立 Epic**(报 Planner,走 REPLAN)
3. 记录时挂到受影响 story 的 `trace` 上做交叉引用

产品向的例子:账号注销与数据删除、未成年人保护、通知偏好、多语言下的称谓与日期格式。
**不是技术向的例子**:可观测性、缓存、CDN、数据库索引——那些是 `architecture-design` 的输入。

### 孤儿检测

拆完后校验:

- 每个非 Epic 项都有父
- 每个 Epic 至少一个 Feature
- 每个 Feature 至少一个 Story
- 依赖声明无悬空引用

---

## 依赖类型(仅 2 类)

| 类型 | 含义 | 例 |
|---|---|---|
| `blocked-by` | 必须先存在,否则该行为无法交付 | FEATURE-1.2 blocked-by FEATURE-1.1 |
| `related-to` | 相关但不阻塞 | STORY-1.1.1 related-to STORY-2.1.1 |

**`depends-on` 归入 `blocked-by`。** "行为依赖另一行为存在"在产品行为目录里就是阻塞关系——
B 依赖 A,就说明 B 不能先于 A 交付。"硬阻塞 vs 软依赖"是排期粒度,属于下游
`planning-and-task-breakdown`。

**`duplicates` 不是依赖类型**,由 Executor 的 `merge` 指令处理;**`parent-of` 就是层级本身**。

---

## 层级定义

Story 是最低层——实现任务属于 `planning-and-task-breakdown`。

| 层级 | 范围 | 粒度 | 读者 | 验收标准 |
|---|---|---|---|---|
| **Epic** | 业务计划 | 周到月 | 干系人 | 业务结果 |
| **Feature** | 功能能力 | 天到周 | 产品/开发 | 功能完整性 |
| **Story** | 用户价值增量 | 小时到天 | 开发/测试 | 用户验收 |

---

## 拆分技法

Feature 或 Story 感觉太大时用:

| 技法 | 何时用 | 例 |
|---|---|---|
| 按流程步骤 | 线性过程 | "结算" → "加购" + "付款" + "确认订单" |
| 按角色 | 多类用户 | "看板" → "管理看板" + "用户看板" |
| 按数据类型 | 多种输入 | "导入" → "导入 CSV" + "导入 Excel" |
| 按操作 | CRUD | "管理用户" → "新建" + "编辑" + "删除" |
| 正常路径优先 | 降风险 | 先做基本流程;异常/边界行为只有在**独立用户价值**时才单独成 story |

最后一条对应本 skill 的场景分类:先有 normal 路径的 story;exception / boundary 行为
只在承载独立用户价值时才拆成单独 story,否则作为同一 story 的场景。

---

## Evidence Ledger 规则

`state.evidence` 中每条 claim 必须标注类型:

```json
{"claim": "STORY-1.1.1 邮箱注册对应 Spec §3.1 注册流程", "type": "FACT", "evidence": "Spec §3.1", "confidence": "high"}
{"claim": "STORY-1.2.1 由用户 split 指令拆出", "type": "DECISION", "evidence": "02-artifact decisions#d3", "confidence": "high"}
```

- `FACT`(证据 = `spec_source` §x / `.pev/<轮次>/rc/` 产物)与 `DECISION`(证据 = 决定锚点)
  **都必须有非空 `evidence`**(校验脚本 R1 强制);没有证据的结论只能标
  `INFERENCE` / `HYPOTHESIS` / `UNKNOWN`。
- Verifier 以 Ledger 为准自动检查:条目无来源 → 不允许留在目录里,记入 `evidence_gaps`。
