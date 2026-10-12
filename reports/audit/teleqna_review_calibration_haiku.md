# 复查模型校准：Haiku 5.5 vs 默认模型

由 `scripts/ingest_haiku_review.py` 生成，请勿手改。复查提示词与默认模型复查相同（每块 5 题、两名复查者、可联网）。

校准题：默认模型已有两名复查者判定的 108 题，两边结果都齐全 108 题。
每题“有问题” = 两名复查者不都判 correct（与保留规则一致）。

| | Haiku 无问题 | Haiku 有问题 |
| --- | --- | --- |
| 默认模型无问题 | 14 | 41 |
| 默认模型有问题 | 2 | 51 |

- 合并判定二分类 kappa：**0.21**（MiniMax-M3 为 0.29；门槛 0.6）
- 一致率 60.2%；单名 Haiku 复查者 vs 默认模型合并判定 kappa：inv1 0.34、inv2 0.27；Haiku 两名复查者之间 kappa 0.46
- 最终决定（保留 / 改答案且选项一致 / 剔除）一致：62/108 = 57.4%
- Haiku 判“保留”的 16 题中，默认模型也判保留 14 题（精确率 88%）；默认模型判保留共 55 题
- 决定交叉表（默认模型 → Haiku）：drop→drop 46、drop→fix 2、drop→keep 2、fix→drop 1、fix→fix 2、keep→drop 40、keep→fix 1、keep→keep 14
- Haiku 判定分布（校准题）：unverifiable 77、correct 54、ambiguous 54、wrong 31

## 待复查 109 题按 Haiku 结论的决定（未采用，供用户决定）

两名复查者齐全 109 题：drop 85、keep 15、fix 9
