# TeleQnA 答案核验

由 `analysis/answer_check.py` 生成，请勿手改。

## 方法

- 抽样：审计后保留的题中按类别分层随机抽 300 题；另加近重复审计中答案互相矛盾的题 7 道（单独报告，不计入错误率）。
- 盲答筛查：两个来自不同厂商的模型只看题干与选项作答——`qwen3.8-2.4t-a95b`（因成本只跑了部分题）与 Claude 子 agent。任一与标准答案不一致即进入核查。
- 深度核查：两名 Claude 子 agent 独立核查，可查阅 3GPP / IEEE / ETSI 原文，判为 correct / wrong / ambiguous / unverifiable。
- 局限：两路盲答都与一个错误的标准答案一致时会漏检，错误率是下界；核查者不是人工，“疑似错误”需人工确认。

## 盲答筛查

- Qwen 盲答覆盖 267/300 题，与标准答案一致 221 题
- Claude 盲答覆盖 300/300 题，与标准答案一致 256 题
- 两路都覆盖的 267 题中，两路答案相同 227 题
- 进入核查：68/300 题

## 错误率（随机抽样部分）

| 状态 | 题数 |
| --- | --- |
| screen_pass | 232 |
| correct | 31 |
| suspect_wrong | 3 |
| needs_review | 34 |
| missing_verdict | 0 |

- 疑似错误率（两名核查者都判错）：3/300 = 1.0%（95% CI 0.3%–2.9%）
- 含待复核的上界：37/300 = 12.3%（95% CI 9.1%–16.5%）

| 类别 | 抽样题数 | 疑似错误 | 待复核 |
| --- | --- | --- | --- |
| Lexicon | 43 | 1 | 0 |
| Standards overview | 86 | 1 | 9 |
| Standards specifications | 171 | 1 | 25 |

## 答案矛盾题

| 题目 | 标准答案 | 核查结果 | 建议改为 |
| --- | --- | --- | --- |
| question 1143 | 5 | ambiguous|ambiguous | — |
| question 3663 | 1 | correct|correct | — |
| question 4450 | 1 | correct|correct | — |
| question 4536 | 2 | wrong|wrong | — |
| question 4588 | 2 | correct|ambiguous | — |
| question 7935 | 4 | correct|correct | — |
| question 9424 | 2 | correct|correct | — |
