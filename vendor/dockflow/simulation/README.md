# Simulation — 仿真、对照实验与接口

唯一七种算法：fcfs / spt / edf / edf_aging / dependency_aware / joint_da / rh_da。

## 快速调用

~~~python
from simulation import generate_scenario, run_simulation, run_experiment

scenario = generate_scenario({
    "scenario_preset": "normal", "random_seed": 42,
    "inbound_count": 10, "outbound_count": 8,
    "dependency_ratio": 0.5,
})
result = run_simulation(scenario, "joint_da")
print(result["metrics"])
~~~

## 核心模块

| 模块 | 职责 |
|---|---|
| models.py | Scenario 校验 |
| generator.py | 固定种子的 normal/rush/heavy 生成器 |
| engine.py | 多月台离散事件循环与调度工厂调用 |
| dependency.py | 依赖解锁与优先级快照输入 |
| metrics.py | baseline 指标、导出 CSV |
| competition.py | 预设与控制变量实验场景生成 |
| experiments/scans.py | 参数扫描及多种子汇总 |
| experiments/scoring.py | DockScore 同场景相对综合评分 |
| experiments/comparison.py | 依赖集中与截止压力两组场景批量对照 |

数据集适配位于 dataset_adapter.py / mendeley_reader.py。
算法实现在 scheduler/，决策解释快照工具属于 JointDA 的辅助逻辑，
不是额外的算法。

## 对外契约

run_simulation(scenario, algorithm, settings=None) -> SimulationResult

输入 Scenario 不变。返回车辆、月台、真实事件与质量指标。
唯一物理模型为 baseline；可省略 `simulation_mode` 或显式填写
`baseline`，`enhanced` 及已删除的物理资源参数被拒绝。
IN 装卸完成即可解锁下游 OUT，月台在该车驶离后释放。

run_experiment(config) -> {config, runs, series}

~~~json
{
  "competition_level": "medium",
  "base_config": {
    "scenario_preset": "normal",
    "inbound_count": 30,
    "outbound_count": 30,
    "dock_count": 5,
    "arrival_horizon": 90,
    "dependency_ratio": 0.5
  },
  "vary_parameter": "dock_count",
  "parameter_values": [2, 3, 5, 8],
  "seeds": [42, 43, 44],
  "algorithms": ["fcfs", "spt", "edf", "edf_aging", "dependency_aware", "joint_da", "rh_da"]
}
~~~

扫描变量：dock_count、arrival_density、dependency_ratio。
不传 base_config 时使用 low/medium/high 旧预设。
每个参数点/种子下七种算法共享冻结场景，其余输入不变。
七种算法的具体评分、预测规则与限制见 `scheduler/README.md`。
DockScore 是结果评价，不是第八种调度算法。

## 数据一致性

- 调度只选择 READY 且月台兼容车辆；仿真拥有时间和状态。
- 仿真在真实 IN 完成后解除 OUT 货物依赖。
- 同输入、同设置、同算法应生成相同事件与指标（真实墙钟耗时除外）。
- 不写数据库、不实现 HTTP、不访问前端；持久化由 backend 负责。

详见根目录 contract.md 和 frontend/README.md。
