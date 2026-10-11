# 答案核验：Haiku 与默认模型对照

由 `analysis/answer_check_haiku_compare.py` 生成，请勿手改。

同一批随机抽样 300 题、同一份 Qwen 盲答、同一判定规则，只把 Claude 盲答者与核查者从默认模型换成 Haiku。

| 指标 | 默认模型 | Haiku |
| --- | --- | --- |
| 盲答与标准答案一致 | 256/300 | 244/300 |
| 进入核查 | 68 | 78 |
| 疑似错误 | 3 | 4 |
| 待复核 | 34 | 57 |
| 问题题合计（疑似错误 + 待复核） | 37 | 61 |

- 有问题 / 无问题二分类 Cohen's kappa：0.614
- 默认模型判为有问题的 37 题中，Haiku 也判为有问题 33 题（召回 89%）
- Haiku 判为有问题的 61 题中，默认模型也判为有问题 33 题（精确率 54%）

## 状态混淆矩阵（行：默认模型，列：Haiku）

| | screen_pass | correct | suspect_wrong | needs_review |
| --- | --- | --- | --- | --- |
| screen_pass | 214 | 6 | 0 | 12 |
| correct | 6 | 9 | 1 | 15 |
| suspect_wrong | 0 | 0 | 1 | 2 |
| needs_review | 2 | 2 | 2 | 28 |
