#!/usr/bin/env python3
"""图 15：独立验证（选择集 γ 敏感性 + 确认集逐实例不劣比例）。"""
import csv, json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "research"
plt.rcParams.update({"font.sans-serif":["Hiragino Sans GB","Arial Unicode MS","STHeiti"],
                     "axes.unicode_minus":False,"figure.dpi":150,"savefig.dpi":220,
                     "axes.grid":True,"grid.alpha":0.25})
rows=list(csv.DictReader(open(DATA/"validation_selection.csv",encoding="utf-8")))
S=json.load(open(DATA/"validation_summary.json",encoding="utf-8"))
fig,axes=plt.subplots(1,2,figsize=(13,4.8))
ax=axes[0]
for metric,color,label in (("select_medium_miss","#8769ad","中负载"),("select_high_miss","#c0392b","高负载")):
    xs=[];ys=[]
    for r in rows:
        if float(r["lambda"])==1.0:
            xs.append(float(r["gamma"])); ys.append(float(r[metric]))
    ax.plot(xs,ys,marker="o",color=color,label=label)
ax.set_xlabel("门控阈值 γ（λ=1.0）"); ax.set_ylabel("逾期率")
ax.set_title("(a) 选择集上的 γ 敏感性",fontsize=10); ax.legend(fontsize=8)
ax=axes[1]
labels={"medium":"中负载","high":"高负载","n120":"120 辆","n160":"160 辆"}
names=[labels[k] for k in ("medium","high","n120","n160")]
vals=[S["by_scenario"][k]["ratio"]*100 for k in ("medium","high","n120","n160")]
bars=ax.bar(names,vals,color="#5b8b69")
ax.set_ylim(0,110); ax.set_ylabel("不劣实例比例 (%)")
ax.set_title("(b) 独立确认集：逐实例不劣比例",fontsize=10)
for b,v in zip(bars,vals): ax.text(b.get_x()+b.get_width()/2,v+2,f"{v:.0f}%",ha="center",fontsize=9)
fig.suptitle("图 15 独立验证：参数在选择集上确定，效果在独立种子集上报告",fontsize=12)
fig.tight_layout(); fig.savefig(HERE/"figures"/"fig15_validation.png"); plt.close(fig)
print("生成 figures/fig15_validation.png")
