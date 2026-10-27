# 实施前现状取证

基线通过后、每批任务首次执行前,Planner 从 task_registry 的声明文件、依赖和验收标准提取必须核实的代码事实。已有同轮取证先核对任务与代码是否仍对应;过期的证据重查。小改动只查必要范围,不扩大为全仓扫描。

有只读子代理时分派探索角色;没有时 Planner 按同一契约只读调查。调用输入严格限四项:`sourceRoot`(目标仓库)、`scope`(相关路径与任务 ID)、`questions`(每项稳定 Q-ID 和具体待核事实)、`stopCondition`(有证据、发现冲突或确认无法定位即停止;最多两轮有界搜索)。不附带写入或额外任务。代理只读、不继续委派;先用文件搜索定位,再按行读取,同一路径+行范围+问题不重复读。函数签名、参数顺序、字段、数值边界和验收合同逐字记录。

返回结果必须有四段,每个 Q-ID 都出现,没有内容填 `none`:

```text
Coverage:
- Q1: answered | conflict | unresolved
Evidence:
- Q1: <事实> | Source: <相对路径>#<行号>
Conflicts:
- Q1: <冲突两侧事实及各自来源,或 none>
Unresolved gaps:
- Q1: <无法核实的事实及已查范围,或 none>
```

Planner 将结果保存到 `.pev/<轮次>/impl/explore/<批次或任务 ID>.md`,并把有来源的 FACT、未解决的 UNKNOWN/冲突同步到本轮 Evidence Ledger。探索代理不写报告,由 Planner 保存。冲突两侧并列,不得折中成猜测。Executor 开工前读对应报告,只在需要时按行抽查;不得重复全量搜索。

任一 Q-ID 为 `conflict` 或 `unresolved` 且影响任务实现或验收时,该任务不得执行红灯测试或改代码。把任务 ID、缺口、已查位置及下一步写入 `unresolved`,artifact 置 `status="blocked"` 并走既有三选一;其他不依赖该缺口的任务可按原批次继续。验收以来源、签名保真、冲突双侧和缺口阻塞为准,不声称省时。
