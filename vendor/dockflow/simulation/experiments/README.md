# baseline对比实验与参数扫描

所有实验只运行baseline模型，默认七种在线算法。每个seed冻结同一Scenario共享，完整保存输入与真实事件结果，不保证某自研算法必胜。

| 模块 | 用途 | 入口 |
|------|------|------|
| `scans.py` | 单参数扫描实验（dock_count / arrival_density / dependency_ratio），当前扫描 API | `run_experiment(config)` |
| `comparison.py` | **两组 baseline 对比实验**：固定场景 × 7 算法 × 多随机种子，批量仿真并导出 CSV | `run_comparison_experiment(...)`、`python -m simulation.experiments` |

| 名称 | 研究问题 |
|---|---|
| dependency_concentration | 少量IN阻塞大量OUT时，依赖感知与联合/预测策略的差异 |
| deadline_pressure | 紧宽截止时间混合时，时限、依赖与公平性的取舍 |

旧forklift_bottleneck/dock_disturbance已删除，不再模拟叉车或月台故障。scale=small用于演示，large用于统计；都使用明确的生成参数，不宣称企业实测。

```python
from simulation.experiments import (
    run_comparison_experiment, export_comparison_csv, COMPARISON_ALGORITHMS,
)

experiment = run_comparison_experiment(
    "dependency_concentration",        # 场景名（见上表）
    seeds=[1, 2, 3],                   # 多随机种子，减少随机误差
    algorithms=COMPARISON_ALGORITHMS,  # 默认全部 7 种算法
    scale="large",                     # small=演示规模 / large=统计规模
)
export_comparison_csv(experiment, "build/experiments/dep.csv")

# summary：按算法对核心指标求均值（None 跳过）
print(experiment["summary"]["joint_da"]["avg_waiting_time"])
```

## 命令行批量运行

```bash
# 全部 2 组场景 × 7 算法 × 种子 1/2/3，large 规模，输出到 build/experiments/
python -m simulation.experiments
python -m simulation.experiments --scenario deadline_pressure --seeds 1 --scale small --algorithms dependency_aware joint_da rh_da
```

## 通用单因素扫描

`run_experiment`支持dock_count/arrival_density/dependency_ratio，默认七算法。只改变声明变量，其余车辆属性按合同冻结。配置含competition_level、vary_parameter、parameter_values、seeds，可选algorithms/settings。settings支持aging_threshold、long_wait_threshold、兼容baseline标记。结果为config/runs/series，曲线按五个核心质量指标组织，另报告未完成数。

## Aging专用扫描

`run_aging_threshold_sweep`默认edf_aging，仅允许edf/edf_aging，以免给不使用该阈值的策略制造无意义曲线。相同seed各阈值共用冻结输入。

## 结果纪律

CSV保留scenario_id/algorithm/simulation_mode=baseline/random_seed及真实指标。decision_cost为真实墙钟，仅观测，不汇入算法质量均值或确定性比较。跨种子均值采用逐运行同口径；未完成样本数量必须可见。历史不同模型结果不得与当前模型混算。
