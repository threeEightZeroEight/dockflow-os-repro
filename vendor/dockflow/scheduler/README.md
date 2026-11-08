# DockFlow 调度算法说明

当前只有一种 baseline 物流模型：车辆到站 → 等待依赖 → 就绪 → 获台 → 驶入 → 装卸 → 驶离。IN 卸货完成立即满足下游货物依赖；月台在驶离后才释放。没有叉车、缓冲区容量或月台故障模型。四种基础规则与三种自研策略都在同一套约束下运行。

## 共同约束与时间口径

- 只选择 READY 车辆；IN→IN/FLEX，OUT→OUT/FLEX，同时满足 allowed_dock_ids。
- 装卸非抢占；当前空闲台存在兼容 READY 车时必须作出分配，不能用返回 None 故意让路。
- 所有时间均为仿真分钟。`a=approach_duration`，`e=exit_duration`，`s=service_duration`。
- `W=max(0, now-ready_since)` 是就绪排队时间；BLOCKED 时间不参加 Aging。
- OUT 的真实截止时间是 `departure_deadline`，违约按真实离站时刻判断。
- OUT 的 `dispatch_deadline` 等于真实截止时间。IN 的派生调度截止时间 D：取已到站且尚未离站的下游 OUT 中 `departure_deadline - OUT.service_duration - a - e` 的最小值；无可用下游时为 None。
- D 是 IN 的启发式卸货完成要求，未扣除其他前置车、月台排队的全部影响；不保证准时。未到站车辆不会影响当前排序或预测。
- 引擎按 slot_index、dock_id 逐台落地。FCFS/SPT/EDF/EDF+Aging/DA 逐台选择；JointDA/RH-DA 先规划当前批次，再按同一接口逐台返回。
- 同分稳定落到 ready_since、arrival_time、truck_id（基础规则具体键如下）。同输入、同调用序列的选择确定；墙钟 decision_cost 不参与确定性断言。

## 1. FCFS：先就绪先服务

选择 `(ready_since, arrival_time, truck_id)` 最小者。

例：A 到站早但一直缺货，第 10 分钟才就绪；B 第 5 分钟已就绪。当前选 B。研究公平的排队基线，不考虑服务长度或时限。

## 2. SPT：短作业优先

选择 `(service_duration, ready_since, truck_id)` 最小者。

例：A 卸货 10 分钟，B 卸货 2 分钟，优先 B。倾向减少平均等待；持续短任务到达时，长任务可能久等，不保证有依赖、多月台场景下全局最优。

## 3. EDF：调度截止时间优先

选择 `(D_or_infinity, ready_since, truck_id)` 最小者。

例：A 的 D=40，B 的 D=25，优先 B。IN 通过已到站下游的派生 D 继承紧迫性。没有时限的任务排在有时限任务之后；不按照松弛时间或最短服务重新定义 EDF。

## 4. EDF+Aging：双层时限与等待保护

阈值 `aging_threshold` 默认 12，必须是有限正数。

- W 达到阈值：键为 `(0, ready_since, D_or_infinity, truck_id)`。
- 未达到：键为 `(1, D_or_infinity, ready_since, truck_id)`。

老化层优先；老化层内部先看谁等得更久，普通层内部按 EDF。例：A 等了 15 分钟、没有截止时间；B 只等 1 分钟、D 很早。阈值 12 时选 A。它改变获台顺序，不改变真实截止时间，不中断正在装卸的车。

## 5. DA：固定的多因素依赖感知

不再提供“原始两计数 DA / 增强 DA”的两套实现，也不按 simulation_mode 回退。分数越大越优先，默认公式：

```text
S_DA = 100I + 5B + 20R + 10P×is_IN + 2W
```

- I：已到站 BLOCKED OUT 中，仅差当前 IN 的卸货即可就绪的数量。
- B：仍依赖当前 IN 的 BLOCKED OUT 数量，包含 I；OUT 候选两项恒为 0。
- R：当前批次资源适配，`(1 + min(1, C/F)) / K`。C 为当前调用的兼容 READY 候选数；F 为批次开始时空闲月台总数；K 为本车在这些空闲月台中的兼容台数。当前请求台保证计入，所以 K≥1。
- P：历史观测的车流压力，`min(1, 最近60分钟观测到站车辆数 / (60×0.5))`。阻塞/作业车辆也可由规划快照观测；没有未来到达预测，没有按调用次数重复 EMA 平滑。
- W：真实就绪等待，线性增长，保护所有久等车辆。

例：两辆 IN 依赖收益相同，两个 IN 台都空闲；A 两台都能去，B 只能去 D1。D1 上 C=2、F=2，所以 A 的 R=1、B 的 R=2，B 获得额外 20 分资源适配收益。若 A 已经久等，等待收益也可能让它获选。

DA 是综合评分，不再宣称 I 对其他因素绝对优先、两计数均零必为 FCFS。资源项基于批次初始空闲集合，不宣称完成跨台全局负载优化。去掉 defer、无排序作用的公共负载乘数、伪死锁检测及与算法结果无关的开关。

可调权重：`da_immediate_weight=100`、`da_blocked_weight=5`、`da_resource_weight=20`、`da_traffic_weight=10`、`da_wait_weight=2`，有限非负；`da_arrival_window=60`、`da_pressure_rate=0.5`，有限正数。精确同分按 FCFS 键。

## 6. JointDA：当前批次的联合匹配

先最大化本批次可同时分配的车辆数，再最大化车辆综合优先级之和：

```text
S_Joint = 100I + 5B + 20U + 2W
U = 1 - slack / (30 + abs(slack))
OUT slack = departure_deadline - now - a - s - e
IN  slack = D - now - a - s
```

无截止时间时 U=0；slack 越小，U 越大，范围为 (0,2)。例如 slack=30/0/-30，U=0.5/1/1.5。相对松弛时间替代了旧的“1000减绝对截止时间”；等待奖励统一为线性。

在月台×READY车辆兼容图上使用匈牙利匹配。不可兼容边禁止使用，虚拟空位确保“匹配数量优先于分数”；按兼容连通分量分解仅为等价计算优化。所有候选参与，没有前60辆截断、旧计划硬锁或叉车距离代理项。

例：A 可去 D1/D2，B 只能去 D1；联合安排 D1←B、D2←A，避免先把 A 给 D1 后让 D2 空闲。修复了旧匹配增广路径的前驱错误，并以小规模穷举交叉验证。

缓存只属于同一 decision_id，新事件即使 now 未变也重算；返回前验证候选仍存在、READY、兼容且未重复。它优化当前批次评分，不承诺整个场景的全局最优。

可调权重：`joint_immediate_weight=100`、`joint_blocked_weight=5`、`joint_urgency_weight=20`、`joint_wait_weight=2`（有限非负）；`joint_slack_scale=30`（有限正数）。

## 7. RH-DA：真正的有限时域预测决策

```text
读取当前状态
→ 构造几种当前批次的可行安排
→ 在状态副本中向前推演 H 分钟
→ 比较预测总出站逾期，平局再比较总等待
→ 只落地当前批次分配
→ 新事件发生后读取新状态，重新推演
```

- 读取已到站 READY/BLOCKED/作业中车辆、依赖、真实 OUT 截止时间、月台预计释放时间。不会读取未到站车辆或调用真实引擎提前看未来。
- 搜索保持最大可行并行分配，提议来自资源稀缺、EDF、依赖收益、SPT、FCFS 等规则。默认最多保留 8 种初始安排，每台最多提议 4 个候选；另含不截断车辆的可行最大匹配保底，避免独占车被候选筛选遗漏。
- 每种初始安排分别用 EDF、依赖优先、SPT 三种规则继续预测；默认最多 24 次推演。
- 推演真实的驶入、装卸完成、驶离释放、依赖解锁及后续获台；零时长事件也先结算再分配。IN 在卸货完成而不是驶离时解锁下游。
- H 是事件时间窗口，默认 `horizon_window=30` 分钟，不再是“窗口/步长换候选数量”。没有每5分钟固定执行步长，新事件就是重规划触发点。
- 目标先最小化所有已知 OUT 的预测逾期总时长，再最小化所有已知车辆的预测等待总时长，最后稳定签名打平局。
- 窗口结束仍未完成的车辆，用当前已排作业的预计完成时刻或乐观终端估计计入，不能因未完成就把逾期记成零。终端估计忽略窗口外完整队列竞争；未到站上游不会被虚构成已到站，其缺失会计入 unresolved_dependency_count。因此预测是有限信息估计，不是保证。
- 只返回本轮当前空闲台的分配；预测中的后续分配不写入真实状态。decision_id 更新后废弃旧预测。

例：A 卸货8分钟能解锁3辆宽松 OUT；B 卸货2分钟能解锁1辆截止第4分钟、装货1分钟的紧急 OUT。即使后续优先处理紧急车，先 A 也会让它至少逾期7分钟；先 B 可以让它第3分钟离站。RH比较后选择 B，即使 A 的立即解锁数更多。

参数：`horizon_window=30`，有限正数；`rh_beam_width=8`，整数1–64；`rh_candidates_per_dock=4`，整数1–16。搜索规模受限，不宣称所有可能安排中的最优解。

`last_plan_summary` 和真实 DECISION_SNAPSHOT.forecast 提供 H、候选数、推演次数、预测离站、预测总逾期、终端估计数量与实际模拟到的最晚时刻，供检查器解释。

## 实验与复现

默认七策略共用同一冻结Scenario和设置。标准场景为dependency_concentration、deadline_pressure；通用扫描支持dock_count/arrival_density/dependency_ratio。Aging专用扫描仅接受EDF/EDF+Aging。真实结果和输入均保存；墙钟decision_cost不参与确定性断言或跨种子质量指标比较。
