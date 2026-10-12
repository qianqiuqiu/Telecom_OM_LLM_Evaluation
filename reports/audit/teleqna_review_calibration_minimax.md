# 复查模型校准：MiniMax-M3 vs 默认模型

由 `scripts/ingest_workbuddy_review.py` 生成，请勿手改。

校准题：默认模型已有两名复查者判定的 108 题，两边结果都齐全 108 题。每题“有问题” = 两名复查者不都判 correct（与保留规则一致）。

| | MiniMax 无问题 | MiniMax 有问题 |
| --- | --- | --- |
| 默认模型无问题 | 39 | 16 |
| 默认模型有问题 | 22 | 31 |

- 合并判定二分类 kappa：**0.29**（门槛 0.6，未达到 → 不采用 MiniMax 对待复查题的结果）
- 一致率 64.8%；单名 MiniMax 复查者 vs 默认模型合并判定 kappa：inv1 0.16、inv2 0.27
- MiniMax 两次运行之间 kappa 0.33（同一模型两次运行，不是独立标注者）
- 最终决定（保留 / 改答案并选项一致 / 剔除）一致：65/108 = 60.2%
- 默认模型判为改答案的 3 题中，MiniMax 给出相同改法：2 题
- MiniMax 判定分布：correct 152、wrong 37、ambiguous 27
