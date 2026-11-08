# 代码与数据来源

## DockFlow 快照

- 源仓库：`DockFlow`
- 源 commit：`e2b9d39`
- 复制内容：
  - `simulation/`（仿真引擎、生成器、模型、竞争场景）
  - `scheduler/`（七种调度算法与工厂）
  - `data/processed/scenario_21.json`（Mendeley 冻结实例）

## 为什么带快照

实验脚本直接 import `simulation` 与 `scheduler`。若只复制 `docs/os-report/`，脚本无法运行；若用 submodule，主仓库后续改动会让复现漂移。因此本仓库固定一份最小快照，保证“克隆即跑”。

## 同步方式

当 DockFlow 的仿真/调度语义有意更新时，手动同步并更新本文件：

```bash
cp -R /path/to/DockFlow/simulation vendor/dockflow/
cp -R /path/to/DockFlow/scheduler vendor/dockflow/
cp /path/to/DockFlow/data/processed/scenario_21.json vendor/dockflow/
```

同步后必须重跑：

```bash
make data
make verify
```

若关键数值变化，说明语义改变，需要同时更新 `data/expected_metrics.json` 与报告正文，而不是只改脚本。

## 数据来源

- `scenario_21.json`：Mendeley 公开交叉转运数据集，Dataset_ch5 / DoorSet_2 / LL_21-30 中的第 21 个实例，53 入站 / 54 出站 / 10 月台 / 1378 托盘。
- 时间切片由 `make_slices.py` 按到达时间窗派生，保留完整前驱；切片共享同一来源，不是独立数据集。

## 许可

本仓库尚未附 LICENSE。DockFlow 项目当前也没有 LICENSE 文件。公开发布前需与项目成员确认：
- 代码快照的再分发许可；
- Mendeley 数据集的再分发条款；
- 报告作者署名与引用方式。