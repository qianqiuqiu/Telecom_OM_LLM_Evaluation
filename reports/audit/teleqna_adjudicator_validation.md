# 近重复裁决器校验

由 `analysis/pair_adjudicator_agreement.py` 生成，请勿手改。

抽样 148 对（分层：裁决为重复的对、高相似的变体对、随机变体对、相关对），每对由 3 名独立标注者盲标（不看裁决结果），取多数票。
标注者为 Claude 子 agent，不是人工；它们与裁决模型来自不同厂商。

## 一致性

| 指标 | 数值 |
| --- | --- |
| 裁决 vs 多数票，三分类 Cohen's kappa | 0.731（95% CI 0.638–0.818） |
| 裁决 vs 多数票，重复 / 非重复 Cohen's kappa | 0.932（95% CI 0.865–0.986） |
| 裁决判重复的精确率（以多数票为准） | 63/68 = 92.6% |
| 多数票判重复中被裁决找到的比例 | 63/63 = 100.0% |
| 标注者之间 Fleiss' kappa（三分类，148 对） | 0.882 |
| 标注者全票一致的对 | 131/148 |
| 双方都判重复时，答案一致性判断相同 | 61/63 |

## 混淆矩阵（行：裁决，列：多数票）

| | duplicate | variant | related |
| --- | --- | --- | --- |
| duplicate | 63 | 2 | 3 |
| variant | 0 | 39 | 21 |
| related | 0 | 0 | 20 |

## 分歧样本（26 对，交人工复核）

| pair_id | 题对 | 题干 Jaccard | 裁决 | 多数票 | 票型 |
| --- | --- | --- | --- | --- | --- |
| P009 | question 2029 / question 5223 | 0.57 | variant | related | related, related, variant |
| P020 | question 9 / question 4326 | 0.59 | variant | related | related, related, related |
| P021 | question 2534 / question 5521 | 0.52 | variant | related | related, related, related |
| P035 | question 8150 / question 8283 | 0.50 | variant | related | related, related, related |
| P036 | question 3747 / question 6789 | 0.56 | variant | related | related, related, related |
| P042 | question 9 / question 5470 | 0.62 | variant | related | related, related, related |
| P043 | question 5267 / question 6487 | 0.76 | variant | related | related, related, related |
| P047 | question 6155 / question 7901 | 0.62 | variant | related | related, related, related |
| P052 | question 6005 / question 8636 | 0.51 | variant | related | related, related, related |
| P053 | question 3289 / question 7959 | 0.71 | variant | related | related, related, related |
| P059 | question 8283 / question 8678 | 0.51 | variant | related | related, related, related |
| P063 | question 5248 / question 8417 | 0.36 | duplicate | variant | variant, variant, variant |
| P065 | question 1178 / question 1224 | 0.82 | variant | related | related, related, related |
| P067 | question 3289 / question 8739 | 0.72 | variant | related | related, related, related |
| P077 | question 7675 / question 8283 | 0.69 | variant | related | related, related, related |
| P082 | question 7481 / question 7963 | 0.68 | duplicate | related | related, related, related |
| P093 | question 7452 / question 7943 | 0.24 | duplicate | related | related, related, related |
| P095 | question 5993 / question 6337 | 0.67 | duplicate | variant | variant, variant, duplicate |
| P100 | question 5181 / question 7948 | 0.74 | variant | related | related, related, variant |
| P101 | question 6455 / question 7675 | 0.71 | variant | related | related, related, related |
| P104 | question 5894 / question 6845 | 0.71 | variant | related | related, related, related |
| P111 | question 8283 / question 8596 | 0.52 | variant | related | related, related, related |
| P113 | question 1178 / question 6487 | 0.73 | variant | related | related, related, related |
| P124 | question 4326 / question 6517 | 0.56 | variant | related | related, related, variant |
| P141 | question 3789 / question 7096 | 0.44 | duplicate | related | duplicate, related, related |
| P143 | question 1178 / question 4072 | 0.73 | variant | related | related, related, related |
