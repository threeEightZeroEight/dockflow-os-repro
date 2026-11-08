# 复现指南

## 1. 准备

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

确认系统工具：

```bash
pandoc --version
dot -V
```

## 2. 只校验冻结结果

```bash
.venv/bin/python verify.py
```

预期输出：

```
校验通过：表 10、确认集不劣计数、选择集参数与关键产物一致。
```

该命令不重跑仿真，只从 `data/research/*.json` 重算均值并核对 `data/expected_metrics.json`。

## 3. 重建图表与 docx（不重跑仿真）

```bash
make figures docx
```

生成 `figures/` 下 18 张图与 `report.docx`。若字体缺失，图中中文可能显示为方框，见 `ENVIRONMENT.md`。

## 4. 全量重跑

```bash
make all
```

顺序：

1. `collect_experiments.py`：主实验（中等/高负载、依赖/月台/老化扫描、等待分布）
2. `collect_extended.py`：多场景、规模、冻结实例、消融
3. `collect_adaptive.py`：AQEDF 自适应实验
4. `collect_validation.py`：选择集定参与确认集评估
5. `collect_gap.py`：二维网格、全车辆等待、消融检验
6. `collect_research.py`：QEDF、下界、大规模
7. `make_slices.py`：Mendeley 时间切片
8. `collect_derived.py`：真实切片指标、统一规模表、公平性指标
9. `offline_bruteforce.py`：6/8 车顺序空间穷举
10. `analyze_adaptive.py`、`analyze_research.py`、`stats_analysis.py`：统计量
11. 绘图与 `make_docx.py`

## 5. CP-SAT（可选）

```bash
make venv-ortools
make cpsat
```

`ortools==9.15.6755` 装在 `.venv-ortools`，不要装进主环境；主环境可能因 libprotobuf 冲突在导入时崩溃。

## 6. 预期数值

`verify.py` 覆盖：

| 项目 | 期望 |
|---|---|
| CP-SAT 离线最优 / EDF / AQEDF / RH-DA / SPT | 0.22 / 0.54 / 0.54 / 0.56 / 3.84 |
| 6 车穷举 | 1.13 / 4.85 / 4.48 / 4.48 / 5.47 |
| 8 车穷举 | 5.73 / 14.23 / 14.23 / 11.33 / 13.65 |
| 确认集不劣 | 57/60（中 17/20、高 20/20、120 辆 10/10、160 辆 10/10） |
| 选择集参数 | λ=1.0、γ=1.5 |

## 7. 常见问题

**`ModuleNotFoundError: simulation`**
脚本必须从仓库根运行，且 `vendor/dockflow/` 存在。不要单独复制某个脚本到别处。

**`No module named ortools`**
只影响 `cpsat_offline.py`。按第 5 节建独立 venv。

**docx 中表格被压扁或丢列**
确认 `pandoc` 可用；`make_docx.py` 会在转换后修复 `tblW`/`tblGrid`。若仍异常，检查 `report.md` 中表格分隔行 `---` 数量是否与表头列数一致。

**图 1–3 生成失败**
需要 `dot`（Graphviz）。图 4–16 只需要 matplotlib。

**结果与报告不一致**
先跑 `verify.py`：若通过，说明冻结数据一致，差异在报告文本或图；若失败，说明数据被改动。`decision_ms` 是运行时测量，允许毫秒级抖动。