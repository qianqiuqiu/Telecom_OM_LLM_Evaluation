# TeleQnA 全量答案核验（两阶段）

由 `analysis/answer_check_full.py` 生成，请勿手改。

范围：审计后保留、未在抽样中核验过的 3113 题；按 Oct 12 决定只对其中运维相关（相关度 ≥ 2）的 752 题下结论。流程：Haiku 盲答 → 不一致的题由两名 Haiku 核查 → Haiku 未一致判对的题由两名强模型复查定论。

| 状态 | 子集内题数 | 含义 |
| --- | --- | --- |
| pass | 610 | Haiku 盲答与标准答案一致 |
| pass_screen | 11 | 不一致，但两名 Haiku 核查者都判标准答案正确 |
| pass_review | 12 | 强模型复查两人都判正确 |
| fix | 1 | 强模型复查两人都判错且正确选项一致 → 改答案 |
| drop | 9 | 复查判为错误无正确选项、有歧义、无法核实或意见不一 → 剔除 |
| pass_vote | 23 | 默认模型未复查；Haiku ×2 + MiniMax ×2 中 ≥ 3 人判正确 → 保留 |
| drop_vote | 86 | 默认模型未复查；判正确不足 3 人 → 剔除 |
| incomplete | 0 | 盲答或复查缺失，需补跑 |

- 子集内进入 Haiku 核查 142 题，进入复查 131 题：vote 109、claude-default 22
- 子集内问题题（fix + drop + drop_vote）占比：96/752 = 12.8%（95% CI 10.6%–15.3%）；对照：300 题抽样核验的估计为 12.3%
- 子集外 2361 题不写入决定；其中 422 题按决定不再复查
- 复查来源：默认模型（Claude）；其未覆盖的题用 Haiku 5.5 ×2 + MiniMax-M3 ×2 投票。两者单独与默认模型的一致性都未达标（kappa 0.21 / 0.29），见 `teleqna_review_calibration_haiku.md`、`teleqna_review_calibration_minimax.md`；投票规则在校准题上的保留精确率 81%，即 pass_vote 中约有 1/5 可能是默认模型会判有问题的题
- 局限：全量筛查只有 Haiku 一路盲答，Haiku 恰好选中错误标准答案的题会漏检
