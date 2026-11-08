# 环境说明

## Python

- 版本：3.13
- 依赖：见 `requirements.txt`
- CP-SAT：见 `requirements-ortools.txt`，必须使用独立 venv

验证版本：

```bash
python -c "import numpy,pandas,scipy,matplotlib,docx; print(numpy.__version__, pandas.__version__, scipy.__version__, matplotlib.__version__, docx.__version__)"
```

本次冻结环境：numpy 2.1.3、pandas 2.2.3、scipy 1.15.3、matplotlib 3.10.0、python-docx 1.2.0。

## 系统工具

| 工具 | 版本 | 用途 |
|---|---|---|
| pandoc | 2.12 | `report.md` → `report.docx` |
| Graphviz `dot` | 16.1.0 | 图 1–3 |

macOS 安装：

```bash
brew install pandoc graphviz
```

## 字体

`make_figures.py` 优先使用 `Hiragino Sans GB`、`Arial Unicode MS`、`STHeiti`。若图中中文显示为方框，安装任一中文字体，或在脚本 `plt.rcParams["font.sans-serif"]` 中加入本机字体。

`make_docx.py` 使用 python-docx 设置中文字体；Word/WPS 打开时若缺少对应字体，会回退到系统字体，不影响表格结构。

## OR-Tools

`cpsat_offline.py` 使用 `ortools==9.15.6755`：

```bash
make venv-ortools
.venv-ortools/bin/python cpsat_offline.py
```

不要在 Anaconda 主环境安装 OR-Tools：实测会因 `libprotobuf` 冲突在导入 `cp_model` 时崩溃。

## 可重复性说明

- 所有随机性来自固定种子，仿真为纯标准库实现，不依赖系统随机源。
- `decision_ms` 是运行时测量，复现时会有毫秒级抖动；其余指标应一致。
- 图与 docx 的像素级外观可能因 matplotlib/pandoc 版本略有差异，数据与表格内容不变。