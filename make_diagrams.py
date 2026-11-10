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
  graph [bgcolor="white", fontname="{FONT}", fontsize=11, pad=0.22,
         nodesep=0.32, ranksep=0.45, splines=true];
  node [fontname="{FONT}", fontsize=10.5, shape=box, style="rounded,filled",
        color="#94A3B8", penwidth=1.0, fillcolor="#F8FAFC", margin="0.12,0.08"];
  edge [fontname="{FONT}", fontsize=9, color="#64748B", penwidth=1.05, arrowsize=0.65];
'''

ARCHITECTURE = '''digraph architecture {
''' + HEAD + '''
  rankdir=TB; newrank=true; compound=true;

  subgraph cluster_fe {
    label=<<b>前端</b><br/><font point-size="9">Vue 3 · three.js · ECharts</font>>;
    fontsize=12; fontcolor="#166534"; color="#86EFAC"; penwidth=1.1;
    style="rounded,filled"; fillcolor="#F0FDF4"; margin=10;
    fe [label="3D 园区回放 · 指标图表 · 实验面板", fillcolor="#DCFCE7", color="#86EFAC"];
  }

  subgraph cluster_be {
    label=<<b>后端</b><br/><font point-size="9">FastAPI · SQLite</font>>;
    fontsize=12; fontcolor="#1E40AF"; color="#93C5FD"; penwidth=1.1;
    style="rounded,filled"; fillcolor="#EFF6FF"; margin=10;
    api [label="REST API（14 端点）\\n校验 · 分页 · 统一错误", fillcolor="#DBEAFE", color="#93C5FD"];
    svc [label="services 编排\\nqueries · comparisons · experiments · mendeley", fillcolor="#DBEAFE", color="#93C5FD"];
    client [label="simulation_client.py\\n（唯一收口）", fillcolor="#FEF3C7", color="#FCD34D"];
    db [label="SQLite（10 张表）\\n快照 · 运行 · 事件 · 实验", shape=cylinder, fillcolor="#F1F5F9", color="#CBD5E1"];
  }

  subgraph cluster_sim {
    label=<<b>仿真层</b><br/><font point-size="9">离散事件引擎</font>>;
    fontsize=12; fontcolor="#6D28D9"; color="#C4B5FD"; penwidth=1.1;
    style="rounded,filled"; fillcolor="#F5F3FF"; margin=10;
    engine [label="时间 · 状态 · 依赖 · 月台 · 指标", fillcolor="#EDE9FE", color="#C4B5FD"];
    exps [label="实验 · 扫描 · 评分", fillcolor="#EDE9FE", color="#C4B5FD"];
  }

  subgraph cluster_sched {
    label=<<b>调度层</b><br/><font point-size="9">只读快照</font>>;
    fontsize=12; fontcolor="#C2410C"; color="#FDBA74"; penwidth=1.1;
    style="rounded,filled"; fillcolor="#FFF7ED"; margin=10;
    sched [label="七种确定性策略\\nselect_next()", fillcolor="#FFEDD5", color="#FDBA74"];
  }

  data [label="Mendeley 冻结 JSON\\n（白名单只读）", shape=cylinder, fillcolor="#F1F5F9", color="#CBD5E1"];

  fe -> api [label="HTTPS /api"];
  api -> svc;
  svc -> client;
  client -> engine [label="Python 调用\\n（不写库）"];
  engine -> sched [label="create_scheduler()"];
  svc -> db [label="事务持久化", constraint=false];
  data -> svc [label="只读", style=dashed, color="#94A3B8", tailport=w];
  exps -> engine [style=dashed, color="#94A3B8"];

  { rank=same; engine; exps; }
  { rank=same; db; data; }
}'''

STATE_MACHINE = '''digraph states {
''' + HEAD + '''
  rankdir=TB; newrank=true; nodesep=0.20; ranksep=0.16;
  node [width=2.75, height=0.62, fixedsize=true, fontsize=10, margin="0.08,0.04"];

  subgraph cluster_vehicle {
    label=<<b>车辆状态机（DockFlow）</b>>;
    fontsize=12; fontcolor="#0F766E"; color="#5EEAD4"; penwidth=1.1;
    style="rounded,filled"; fillcolor="#F0FDFA"; margin=10;
    v1 [label="PENDING\\n（还在路上）", fillcolor="#CCFBF1", color="#5EEAD4"];
    v2 [label="BLOCKED\\n（等货物依赖）", fillcolor="#FEE2E2", color="#FCA5A5"];
    v3 [label="READY\\n（可被调度）", fillcolor="#CCFBF1", color="#5EEAD4"];
    v4 [label="APPROACHING / PROCESSING\\n（驶入与装卸）", fillcolor="#CCFBF1", color="#5EEAD4"];
    v5 [label="EXITING\\n（驶向出口）", fillcolor="#CCFBF1", color="#5EEAD4"];
    v6 [label="DEPARTED\\n（已离开）", fillcolor="#F1F5F9", color="#CBD5E1"];
  }

  subgraph cluster_process {
    label=<<b>进程状态机（操作系统）</b>>;
    fontsize=12; fontcolor="#6D28D9"; color="#C4B5FD"; penwidth=1.1;
    style="rounded,filled"; fillcolor="#F5F3FF"; margin=10;
    p1 [label="新建 New", fillcolor="#EDE9FE", color="#C4B5FD"];
    p2 [label="阻塞 Blocked\\n（等待 I/O 或事件）", fillcolor="#EDE9FE", color="#C4B5FD"];
    p3 [label="就绪 Ready", fillcolor="#EDE9FE", color="#C4B5FD"];
    p4 [label="运行 Running", fillcolor="#EDE9FE", color="#C4B5FD"];
    p5 [label="终止 Terminated", fillcolor="#F1F5F9", color="#CBD5E1"];
    p_gap [style=invis, label="", width=0.1, height=0.1];
  }

  { rank=same; v1; p1; }
  { rank=same; v2; p2; }
  { rank=same; v3; p3; }
  { rank=same; v4; p4; }
  { rank=same; v5; p_gap; }
  { rank=same; v6; p5; }

  v1 -> v2 [label="到站但依赖未满足"];
  v2 -> v3 [label="依赖全部卸完\\n（SERVICE_FINISHED）"];
  v3 -> v4 [label="被算法选中并靠台"];
  v4 -> v5 [label="装卸完成"];
  v5 -> v6 [label="驶离\\n（月台此时才释放）"];

  p1 -> p2 [label="等待资源 / 事件"];
  p2 -> p3 [label="资源就绪"];
  p3 -> p4 [label="被调度"];
  p4 -> p5 [label="结束"];
  p4 -> p2 [label="等待事件", constraint=false, style=dashed,
            color="#C4B5FD", penwidth=0.8, tailport=e, headport=e];

  v2 -> p2 [style=dotted, color="#94A3B8", dir=none, constraint=false];
  v3 -> p3 [style=dotted, color="#94A3B8", dir=none, constraint=false, label="同构", fontcolor="#64748B"];
  v4 -> p4 [style=dotted, color="#94A3B8", dir=none, constraint=false];
  v6 -> p5 [style=dotted, color="#94A3B8", dir=none, constraint=false];
}'''

DEPENDENCY = '''digraph dependency {
''' + HEAD + '''
  rankdir=LR; newrank=true; nodesep=0.38; ranksep=0.95;
  node [fontsize=10, margin="0.10,0.06"];

  subgraph cluster_in {
    label=<<b>入站车（IN）</b>>;
    fontsize=12; fontcolor="#0F766E"; color="#5EEAD4"; penwidth=1.1;
    style="rounded,filled"; fillcolor="#F0FDFA"; margin=10;
    i1 [label="IN-1\\n卸货 8 min", fillcolor="#CCFBF1", color="#5EEAD4", width=1.45];
    i2 [label="IN-2\\n卸货 5 min", fillcolor="#CCFBF1", color="#5EEAD4", width=1.45];
  }

  subgraph cluster_pallet {
    label=<<b>托盘（货物）</b>>;
    fontsize=12; fontcolor="#475569"; color="#CBD5E1"; penwidth=1.1;
    style="rounded,filled"; fillcolor="#F8FAFC"; margin=10;
    p1 [label="P1", shape=ellipse, fillcolor="#E2E8F0", color="#94A3B8", width=0.62, height=0.42];
    p2 [label="P2", shape=ellipse, fillcolor="#E2E8F0", color="#94A3B8", width=0.62, height=0.42];
    p3 [label="P3", shape=ellipse, fillcolor="#E2E8F0", color="#94A3B8", width=0.62, height=0.42];
    px [label="P4\\n（未匹配）", shape=ellipse, style="rounded,filled,dashed",
        fillcolor="#F8FAFC", color="#CBD5E1", fontcolor="#94A3B8", width=1.05, height=0.55];
  }

  subgraph cluster_out {
    label=<<b>出站车（OUT）</b>>;
    fontsize=12; fontcolor="#C2410C"; color="#FDBA74"; penwidth=1.1;
    style="rounded,filled"; fillcolor="#FFF7ED"; margin=10;
    o1 [label="OUT-1\\n截止 90 min\\n依赖 IN-1", fillcolor="#FFEDD5", color="#FDBA74", width=1.65];
    o2 [label="OUT-2\\n截止 120 min\\n依赖 IN-1、IN-2", fillcolor="#FFEDD5", color="#FDBA74", width=1.85];
  }

  i1 -> p1 [color="#0F766E"];
  i1 -> p2 [color="#0F766E"];
  i2 -> p3 [color="#0F766E"];
  i2 -> px [color="#94A3B8", style=dashed];
  p1 -> o1 [color="#C2410C"];
  p2 -> o2 [color="#C2410C"];
  p3 -> o2 [color="#C2410C"];


  note [shape=note, style="filled", fillcolor="#FFFBEB", color="#FCD34D",
        fontsize=9, margin="0.18,0.12",
        label="depends_on 前驱约束\\n· 每个 OUT 依赖其托盘来源 IN（见 OUT 标签）\\n· 解锁：IN 卸完货（SERVICE_FINISHED）\\n· 释放：车辆驶离后月台才空出\\n· 未匹配托盘（P4）不得伪造成已出库"];
  { rank=sink; note; }
}'''


def render(name: str, source: str) -> None:
    dot_path = DOT_DIR / f"{name}.dot"
    dot_path.write_text(source, encoding="utf-8")
    png_path = FIG_DIR / f"{name}.png"
    subprocess.run(
        ["dot", "-Tpng", "-Gdpi=220", str(dot_path), "-o", str(png_path)],
        check=True,
    )
    print(f"生成 {png_path.relative_to(HERE.parents[1])}（源 {dot_path.name}）")


def main() -> None:
    render("fig01_architecture", ARCHITECTURE)
    render("fig02_state_machine", STATE_MACHINE)
    render("fig03_dependency", DEPENDENCY)


if __name__ == "__main__":
    main()
