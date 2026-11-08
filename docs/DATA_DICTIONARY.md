# 数据字典

## 目录

- `data/`：主实验（中等/高负载、扫描、等待分布）
- `data/extended/`：多场景、规模、冻结实例、消融
- `data/research/`：AQEDF、独立验证、网格、离线最优、真实切片、统计量
- `research/slices/`：3 个 Mendeley 时间切片场景 JSON
- `vendor/dockflow/scenario_21.json`：Mendeley 冻结实例原始场景

## 主实验

| 文件 | 内容 | 生成脚本 |
|---|---|---|
| `e1_algorithm_baseline.csv` | 七种基线在中等负载上的指标 | `collect_experiments.py` |
| `e2_dependency_sweep.csv` / `_series.json` | 依赖比例扫描 | `collect_experiments.py` |
| `e3_dock_sweep.csv` / `_series.json` | 月台数扫描 | `collect_experiments.py` |
| `e4_aging_sweep.csv` | 老化阈值扫描 | `collect_experiments.py` |
| `e5_deadlock_prevention.csv` | 非法依赖用例 | `collect_experiments.py` |
| `e6_waiting_distribution.csv` | 逐车等待分布 | `collect_experiments.py` |
| `summary.json` / `summary.md` | 汇总 | `summarize_experiments.py` |

## 扩展实验

| 文件 | 内容 | 生成脚本 |
|---|---|---|
| `extended/ea_multi_scenario.csv` | 低/中/高负载 × 八种策略 × 20 种子 | `collect_extended.py` |
| `extended/eb_mendeley.csv` | Mendeley 冻结实例 × 八种策略 | `collect_extended.py` |
| `extended/ec_scale.csv` | 20–80 辆规模扫描 | `collect_extended.py` |
| `extended/ed_dependency.csv` | 依赖比例扫描 | `collect_extended.py` |
| `extended/ee_docks.csv` | 月台数扫描 | `collect_extended.py` |
| `extended/ef_aging.csv` | 老化阈值 | `collect_extended.py` |
| `extended/eg_ablation.csv` | DA 权重消融（中等负载） | `collect_extended.py` |
| `extended/eg_ablation_high.csv` | DA 权重消融（高负载） | `collect_extended.py` |
| `extended/eh_waiting.csv` | 等待分布 | `collect_extended.py` |
| `extended/stats_summary.json` | 扩展统计 | `stats_analysis.py` |

## 研究实验

| 文件 | 内容 | 生成脚本 |
|---|---|---|
| `research/rq_qedf.csv` | 无门控 QEDF | `collect_research.py` |
| `research/rq_dependency.csv` | 依赖扫描下的 QEDF | `collect_research.py` |
| `research/rq_lower_bound.csv` | 极松弛下界 | `collect_research.py` |
| `research/rq_large_scale.csv` | 120/160 辆 | `collect_research.py` |
| `research/rq_adaptive.csv` | AQEDF 自适应实验 | `collect_adaptive.py` |
| `research/validation_selection.csv` | 选择集 λ×γ 扫描 | `collect_validation.py` |
| `research/validation_report.csv` | 确认集逐实例 EDF/AQEDF | `collect_validation.py` |
| `research/validation_summary.json` | 不劣计数与失败案例 | `collect_validation.py` |
| `research/validation_fairness.csv` | 确认集公平性指标 | `collect_derived.py` |
| `research/grid_load_dependency.csv` | 3×3 规模×依赖网格 | `collect_gap.py` |
| `research/all_vehicle_wait.csv` | 全部车辆等待口径 | `collect_gap.py` |
| `research/real_slices.csv` | 3 个切片的八策略指标 | `collect_derived.py` |
| `research/scale_unified.csv` | 20–160 辆统一规模表 | `collect_derived.py` |
| `research/cpsat_offline.json` | 20 车 CP-SAT 最优与在线策略 | `cpsat_offline.py` |
| `research/offline_bruteforce.json` | 6 车顺序穷举 | `offline_bruteforce.py` |
| `research/offline_bruteforce_8.json` | 8 车顺序穷举 | `offline_bruteforce.py` |
| `research/stats_adaptive.json` / `.md` | AQEDF 统计 | `analyze_adaptive.py` |
| `research/stats_research.json` / `.md` | 研究实验统计 | `analyze_research.py` |

## 口径说明

- 逾期率：离站晚于截止期的出站车比例。
- 等待：开始服务时刻 − 到达时刻，仅统计完成车辆；`all_vehicle_wait.csv` 为全部车辆口径。
- 置信区间：默认 95%；TOST 判定使用 90% CI（见报告 §4.2）。
- `real_slices.csv` 是派生切片，不是独立数据集；三个切片存在重叠，统计量不可相加。
- `scale_unified.csv` 的 20–80 辆使用 `arrival_horizon=120`、5 月台、依赖 0.5；120/160 辆来自 `rq_large_scale.csv` / `rq_adaptive.csv`。