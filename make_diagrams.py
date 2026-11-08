#!/usr/bin/env python3
"""生成 UML / 架构图（graphviz dot）。输出 docs/os-report/figures/ 与可编辑 .dot 源。"""
from __future__ import annotations

import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIG_DIR = HERE / "figures"
DOT_DIR = FIG_DIR / "src"
FIG_DIR.mkdir(exist_ok=True)
DOT_DIR.mkdir(exist_ok=True)

FONT = "Hiragino Sans GB"
HEAD = f'''
  graph [bgcolor="white", fontname="{FONT}", fontsize=12];
  node [fontname="{FONT}", fontsize=11];
  edge [fontname="{FONT}", fontsize=10, color="#4b5b6b"];
'''

USE_CASE = f'''digraph usecase {{
{HEAD}
  rankdir=LR; splines=true; nodesep=0.30; ranksep=1.4;
  subgraph cluster_actors {{
    label="参与者"; fontsize=13; color="#8aa0b5"; style="rounded";
    user [label="调度员（前端用户）", shape=box, style="rounded,filled", fillcolor="#e8eef4"];
    engine [label="仿真引擎", shape=box, style="rounded,filled", fillcolor="#e8eef4"];
    scheduler [label="调度算法", shape=box, style="rounded,filled", fillcolor="#e8eef4"];
    db [label="数据库", shape=box, style="rounded,filled", fillcolor="#e8eef4"];
  }}
  subgraph cluster_system {{
    label="DockFlow 系统用例"; fontsize=13; color="#a8bdd0"; style="rounded";
    uc1 [label="生成 / 导入场景", shape=ellipse];
    uc2 [label="启动单次仿真", shape=ellipse];
    uc3 [label="七算法对照", shape=ellipse];
    uc4 [label="参数扫描实验", shape=ellipse];
    uc5 [label="3D 事件回放", shape=ellipse];
    uc6 [label="查询历史运行", shape=ellipse];
    uc7 [label="查看决策快照", shape=ellipse];
    uc8 [label="持久化结果与事件", shape=ellipse];
  }}
  user -> {{uc1 uc2 uc3 uc4 uc5 uc6 uc7}} [arrowhead=none, color="#7a8fa6"];
  uc1 -> engine [style=dashed, arrowhead=vee, color="#9aa7b4"];
  uc2 -> engine [style=dashed, arrowhead=vee, color="#9aa7b4"];
  uc3 -> scheduler [style=dashed, arrowhead=vee, color="#9aa7b4"];
  uc4 -> scheduler [style=dashed, arrowhead=vee, color="#9aa7b4"];
  uc8 -> db [style=dashed, arrowhead=vee, color="#9aa7b4"];
  uc6 -> db [style=dashed, arrowhead=vee, color="#9aa7b4"];
  uc5 -> db [style=dashed, arrowhead=vee, color="#9aa7b4"];
}}
'''

ARCHITECTURE = f'''digraph architecture {{
{HEAD}
  rankdir=TB; nodesep=0.35; ranksep=0.55; compound=true;
  subgraph cluster_fe {{
    label="前端（Vue 3 + three.js + ECharts）"; color="#5b8b69"; style="rounded";
    fe [label="3D 园区回放 · 指标图表 · 实验面板", shape=box, style="rounded,filled", fillcolor="#e9f3ee"];
  }}
  subgraph cluster_be {{
    label="后端（FastAPI + SQLite）"; color="#4275ad"; style="rounded";
    api [label="REST API（14 端点）\\n校验 · 分页 · 错误统一", shape=box, style="rounded,filled", fillcolor="#e8f0f8"];
    svc [label="services 编排\\nqueries / comparisons / experiments / mendeley", shape=box, style="rounded,filled", fillcolor="#e8f0f8"];
    client [label="simulation_client.py\\n（唯一收口）", shape=box, style="rounded,filled", fillcolor="#fff3df"];
    db [label="SQLite（10 张表）\\n快照 · 运行 · 事件 · 实验", shape=cylinder, style="filled", fillcolor="#f2f4f7"];
  }}
  subgraph cluster_sim {{
    label="仿真层（1 号）"; color="#8769ad"; style="rounded";
    engine [label="离散事件引擎\\n时间 / 状态 / 依赖 / 月台 / 指标", shape=box, style="rounded,filled", fillcolor="#f1ecf7"];
    exps [label="实验 · 扫描 · 评分", shape=box, style="rounded,filled", fillcolor="#f1ecf7"];
  }}
  subgraph cluster_sched {{
    label="调度层（2 号）"; color="#be8254"; style="rounded";
    sched [label="七种确定性策略\\nselect_next（只读快照）", shape=box, style="rounded,filled", fillcolor="#fbf0e7"];
  }}
  data [label="Mendeley 冻结 JSON\\n（白名单只读）", shape=cylinder, style="filled", fillcolor="#eef2f7"];

  fe -> api [label="HTTPS /api\\nJSON 事件与指标", color="#4275ad"];
  api -> svc [arrowhead=vee];
  svc -> client [arrowhead=vee];
  client -> engine [label="Python 调用\\n（不写库）", color="#8769ad"];
  engine -> sched [label="create_scheduler()\\nselect_next()", color="#be8254"];
  svc -> db [label="事务持久化", color="#4b5b6b"];
  data -> svc [label="只读白名单", style=dashed, color="#9aa7b4"];
  exps -> engine [style=dashed, arrowhead=vee, color="#9aa7b4"];
}}
'''

STATE_MACHINE = f'''digraph states {{
{HEAD}
  rankdir=TB; nodesep=0.6; ranksep=0.28;
  node [shape=box, style="rounded,filled"];

  vtitle [label="车辆状态机（DockFlow）", shape=plaintext, fontsize=13, fontcolor="#288b85"];
  ptitle [label="进程状态机（操作系统）", shape=plaintext, fontsize=13, fontcolor="#8769ad"];
  {{ rank=same; vtitle; ptitle; }}

  v1 [label="PENDING（还在路上）", fillcolor="#e9f3ee"];
  v2 [label="BLOCKED（等货物依赖）", fillcolor="#fdeeee"];
  v3 [label="READY（可被调度）", fillcolor="#e9f3ee"];
  v4 [label="APPROACHING / PROCESSING（驶入与装卸）", fillcolor="#e9f3ee"];
  v5 [label="EXITING（驶向出口）", fillcolor="#e9f3ee"];
  v6 [label="DEPARTED（已离开）", fillcolor="#eef2f7"];

  p1 [label="新建 New", fillcolor="#f1ecf7"];
  p2 [label="阻塞 Blocked（等待 I/O 或事件）", fillcolor="#f1ecf7"];
  p3 [label="就绪 Ready", fillcolor="#f1ecf7"];
  p4 [label="运行 Running", fillcolor="#f1ecf7"];
  p5 [label="终止 Terminated", fillcolor="#f1ecf7"];

  {{ rank=same; v1; p1; }}
  {{ rank=same; v2; p2; }}
  {{ rank=same; v3; p3; }}
  {{ rank=same; v4; p4; }}
  {{ rank=same; v6; p5; }}

  v1 -> v2 [label="到站但依赖未满足"];
  v2 -> v3 [label="依赖全部卸完（SERVICE_FINISHED）"];
  v3 -> v4 [label="被算法选中并靠台"];
  v4 -> v5 [label="装卸完成"];
  v5 -> v6 [label="驶离（月台此时才释放）"];
  v2 -> v3 [style=dashed, color="#be8254"];

  p1 -> p2 [label="等待资源/事件"];
  p2 -> p3 [label="资源就绪"];
  p3 -> p4 [label="被调度"];
  p4 -> p2 [label="等待事件", constraint=false];
  p4 -> p5 [label="结束"];

  v2 -> p2 [style=invis];
  v3 -> p3 [style=invis];
  v4 -> p4 [style=invis];
  v6 -> p5 [style=invis];

  v2 -> p2 [style=dotted, color="#9aa7b4", dir=both, label="同构", fontcolor="#7a8fa6"];
  v3 -> p3 [style=dotted, color="#9aa7b4", dir=both];
  v4 -> p4 [style=dotted, color="#9aa7b4", dir=both];
  v6 -> p5 [style=dotted, color="#9aa7b4", dir=both];
}}
'''

DEPENDENCY = f'''digraph dependency {{
{HEAD}
  rankdir=LR; nodesep=0.3; ranksep=1.1;
  node [shape=box, style="rounded,filled"];

  subgraph cluster_in {{
    label="入站车（IN）"; color="#288b85"; style="rounded";
    i1 [label="IN-1\\n卸货 8 min", fillcolor="#e9f3ee"];
    i2 [label="IN-2\\n卸货 5 min", fillcolor="#e9f3ee"];
  }}
  subgraph cluster_pallet {{
    label="托盘（货物，Mendeley 场景）"; color="#8aa0b5"; style="rounded";
    p1 [label="P1", shape=ellipse, fillcolor="#eef2f7"];
    p2 [label="P2", shape=ellipse, fillcolor="#eef2f7"];
    p3 [label="P3", shape=ellipse, fillcolor="#eef2f7"];
    px [label="P4（未匹配）", shape=ellipse, style="rounded,filled,dashed", fillcolor="#f7f7f7", fontcolor="#8a8a8a"];
  }}
  subgraph cluster_out {{
    label="出站车（OUT）"; color="#be8254"; style="rounded";
    o1 [label="OUT-1\\n截止 90 min", fillcolor="#fbf0e7"];
    o2 [label="OUT-2\\n截止 120 min", fillcolor="#fbf0e7"];
  }}

  i1 -> {{p1 p2}} [color="#288b85"];
  i2 -> {{p3 px}} [color="#288b85"];
  p1 -> o1 [color="#be8254"];
  p2 -> o2 [color="#be8254"];
  p3 -> o2 [color="#be8254"];

  o1 -> i1 [style=dashed, color="#b66b79", label="depends_on\\n（前驱约束）", constraint=false];
  o2 -> i1 [style=dashed, color="#b66b79", constraint=false];
  o2 -> i2 [style=dashed, color="#b66b79", constraint=false];

  note [shape=note, style=filled, fillcolor="#fffbe6", label="解锁时机：IN 卸完货（SERVICE_FINISHED）\\n释放时机：车辆驶离后月台才空出\\n未匹配托盘（P4）不得伪造成已出库", fontsize=9];
}}
'''


def render(name: str, source: str) -> None:
    dot_path = DOT_DIR / f"{name}.dot"
    dot_path.write_text(source, encoding="utf-8")
    png_path = FIG_DIR / f"{name}.png"
    subprocess.run(
        ["dot", "-Tpng", "-Gdpi=200", str(dot_path), "-o", str(png_path)],
        check=True,
    )
    print(f"生成 {png_path.relative_to(HERE)}（源 {dot_path.name}）")


def main() -> None:
    render("fig01_architecture", ARCHITECTURE)
    render("fig02_state_machine", STATE_MACHINE)
    render("fig03_dependency", DEPENDENCY)


if __name__ == "__main__":
    main()