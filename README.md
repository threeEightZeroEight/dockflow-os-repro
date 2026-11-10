# DockFlow OS 实验复现仓库

本仓库是《前驱约束下的多资源调度：策略—负载交互与截止期失效的实证研究》的独立复现包，包含实验脚本、冻结数据与图表。

它与 DockFlow 主仓库解耦：`vendor/dockflow/` 保存了运行实验所需的 `simulation`、`scheduler` 快照与 Mendeley 冻结实例，克隆本仓库即可复现，不依赖主仓库当前状态。来源版本见 `vendor/dockflow/PROVENANCE.md`。

## 与 DockFlow 项目的关系

本仓库是 DockFlow 项目的**独立 OS 实验复现包**，不是 DockFlow 主仓库的分支、镜像或替代品。

- 源项目：DockFlow（小组共享仓库，https://github.com/thetree61/DockFlow；快照提交 `e2b9d39`）
- `vendor/dockflow/` 仅固定运行实验所需的 `simulation`、`scheduler` 与 `scenario_21.json`

- 同步方式、来源与许可见 `vendor/dockflow/PROVENANCE.md`

## 快速开始

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python verify.py          # 校验冻结数据的关键数值
```


## 复现分级

| 级别 | 命令 | 说明 |
|---|---|---|
| R0 直接审阅 | 无 | 直接查看 `data/`、`figures/` |
| R1 重建图表 | `make figures` | 重建图 4–16 与附录图；图 1–3 为静态示意图 |
| R2 全量重跑 | `make all` | 重跑全部采集、统计与图 |
| R3 离线最优 | `make venv-ortools cpsat` | CP-SAT 需独立环境 |

`make verify` 会把 `data/research/` 中的原始 JSON 重新聚合并与 `data/expected_metrics.json` 比对，任何关键数值漂移都会以非零状态退出。

## 目录

```
.
├── collect_*.py            # 实验采集
├── analyze_*.py            # 统计推断
├── stats_analysis.py
├── make_*.py               # 图
├── collect_derived.py      # 真实切片、统一规模表、公平性指标的显式重建
├── verify.py               # 关键数值校验
├── research/qedf.py        # QEDF / AQEDF 研究原型（不进入产品契约）
├── research/slices/        # 3 个 Mendeley 时间切片
├── vendor/dockflow/        # simulation / scheduler 快照 + scenario_21.json
├── data/                   # 冻结结果（CSV / JSON）
└── figures/                # 17 张正文图与 1 张附录图
```

## 关键结果与校验口径

- 确认集（seeds 300–319）：AQEDF 在 60 个实例中 57 个不劣于 EDF；中负载 17/20，3 个失败实例最大 +0.067。
- 确认集绝对逾期率：高负载 0.886 → 0.790；120 辆 0.458 → 0.342；160 辆 0.603 → 0.430。
- 中等负载只在开发集满足 TOST 等价界；确认集 90% CI [-0.039, +0.012] 不满足 ±0.02。
- 表 10：CP-SAT 0.22（最优）/ 0.54 / 0.54 / 0.56 / 3.84；6 车 1.13 / 4.85 / 4.48 / 4.48 / 5.47；8 车 5.73 / 14.23 / 14.23 / 11.33 / 13.65。

这些数值由 `verify.py` 从原始 JSON 重算，而不是复制报告中的文本。

## 环境

- Python 3.13
- numpy 2.1.3、pandas 2.2.3、scipy 1.15.3、matplotlib 3.10.0

- CP-SAT：独立 venv 安装 `ortools==9.15.6755`（主环境可能因 libprotobuf 冲突失败）

## 数据来源与许可

- `vendor/dockflow/scenario_21.json` 来自 Mendeley 公开交叉转运数据集（Dataset_ch5 / DoorSet_2 / LL_21-30）；切片由 `make_slices.py` 派生，不是独立数据集。
- `vendor/dockflow/simulation`、`scheduler` 为 DockFlow 项目代码快照，来源 commit 见 `PROVENANCE.md`。
- 本仓库当前未附 LICENSE。若要公开发布，请先与 DockFlow 项目成员确认代码与数据的再分发许可。

## 复现边界

- 报告中的合成实例覆盖 20–160 辆、三种竞争强度与四类实例族；真实实例只有一个公开冻结样本。
- `cpsat_offline.py` 依赖 OR-Tools，不在默认 `requirements.txt` 中。
- `decision_ms` 为运行时测量，复现时会有毫秒级抖动；其余指标应逐位一致（浮点格式可能差最后一位）。
