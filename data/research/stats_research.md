# 研究增强实验统计

## QEDF vs EDF（配对，20 种子）

| 场景 | 指标 | 均值差 [95% CI] | t p | Wilcoxon p | Cohen's d |
|---|---|---|---|---|---|
| medium | outbound_deadline_miss_rate | +0.0150 [-0.0134, +0.0434] | 0.283 | 0.173 | +0.247 |
| medium | avg_waiting_time | -0.0122 [-0.0699, +0.0456] | 0.664 | 0.784 | -0.099 |
| high | outbound_deadline_miss_rate | -0.1040 [-0.1250, -0.0830] | 2.84e-09 | 0.000127 | -2.323 |
| high | avg_waiting_time | +0.4186 [-0.2433, +1.0804] | 0.201 | 0.216 | +0.296 |

## 相对离线下界的差距（medium/high）

| 场景 | 算法 | 等待/(下界) | 逾期率绝对差 |
|---|---|---|---|
| medium | edf | 0.83× | +0.053 |
| medium | qedf | 0.83× | +0.068 |
| medium | spt | 0.82× | +0.135 |
| medium | dependency_aware | 0.83× | +0.190 |
| medium | joint_da | 0.83× | +0.105 |
| medium | rh_da | 0.81× | +0.055 |
| high | edf | 11.71× | +0.896 |
| high | qedf | 11.77× | +0.792 |
| high | spt | 10.61× | +0.814 |
| high | dependency_aware | 12.21× | +0.930 |
| high | joint_da | 12.09× | +0.907 |
| high | rh_da | 11.09× | +0.866 |