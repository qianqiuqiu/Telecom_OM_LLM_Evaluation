# 项目状态（STATUS）

项目：通信网络运维助手 · 大模型选型评测。最后更新：2026-10-13。

本文件是唯一的状态文档：现状、下一步、待定决定、决定日志、注意事项都在这里。方案只看 `通信网络运维助手 · 大模型选型评测 Spec.md`（v2.3），用法与命令看 `README.md`。接手顺序：本文件 → Spec → `CLAUDE.md` → `README.md`。用户用中文交流。

## 一、现在在哪

```
1 准备考卷（TeleQnA 审计与清洗）               已完成：客观题测试集 731 题
2 客观题横评（7 模型 × 731 题 × 5 子集）        已完成：分析层 + 三方复核，reports/objective/objective_main.md
3 出主观题（40–50 道中文场景题 + rubric）       初稿完成：45 题，两层事实核验 + TS 引用人工查证 ← 现在
4 阅卷（规则判分 + LLM judge）                 未开始
5 检验裁判（judge 元评测）                     未开始，验证方式待定（见第三节 D2）
6 出结论（横评、思考对照、追问施压、精度回归、选型报告） 未开始
```

第 3 阶段还差收尾（第二节第 1 步）。第 4/5 阶段在动手前要先定 judge 方案和验证方式，这是整个项目最容易返工的地方：场景题 → 模型回答 → judge 验证 → judge 提示词 → 全量判分环环相扣，上游一改，下游作废。

## 二、下一步（建议顺序）

标「待定」的步骤依赖第三节的决定，定之前不动手。每一步定稿后打 git tag，下游只认 tag。

1. **场景题收尾**：37/45 题仍有 `unverified_residuals`，能从标准核验的补 `source_note`，不能的按 Spec「一律去掉不可核验内容」删除或降级为 constructed / common_sense。
2. **天花板试跑**：用 2 个便宜模型（如 qwen3.8-flash、deepseek-v4.1-flash，花费在 ¥1 以内）跑 45 题看分数分布。客观题已有 440/731 题全员答对；场景题如果也全员高分，排序和 judge 验证都会失效，此时调难度比事后补救便宜。
3. **场景题定稿 v1.0**（打 tag）。之后改题只能出勘误版本，并标出受影响的回答和判分。
4. **只生成、不判分**：7 模型关思考 × 45 题（约 ¥9）；思考对照的回答也可先生成（约 ¥130，花钱前确认）。判分等 judge 锁定后一次性跑，不要先用早期 judge 判一遍再全量重判。
5. **judge**（待定，D1/D2）：judge 脚本（多后端）→ 提示词 v1→v2→v3 只在调试集上改 → 锁定 → 留出集报最终数字 → 一次性判全部回答。调试集 / 留出集按题划分（45 题按题型分层约 22/23），不按回答划分，否则同一道题的 rubric 两边都有。
6. **不依赖 judge 的并行项**：精度回归客观题部分（门禁阈值先提交打 tag，见 D3）、污染检测 TS-Guessing、TeleLogs 子集、干扰项质量抽查（72 对选项完全相同的非重复题）。
7. 追问施压 → 选型报告、数据卡、回归报告 → 简历 bullet 与模拟面试。

## 三、待定决定（需用户拍板）

**D1. judge 模型：用 Claude Haiku 5.5 / Sonnet 5.5，经 Claude Code 无头模式走 Pro 订阅（用户 Oct 13 提议）。**
可行：`claude -p --model claude-sonnet-5-5 --tools "" --system-prompt … --json-schema … --output-format json` 可以被 Python 脚本逐条调用，走订阅登录，不花百炼预算。建议采用，附以下条件：
- 用完整模型 ID（`claude-haiku-5-5`、`claude-sonnet-5-5`），不用 `sonnet` 这类别名，避免别名被静默更新导致复跑对不上（与百炼用快照同理）；每次记录实际返回的模型名。
- 这两个模型不接受自定义 temperature（API 也一样），judge 自身稳定性只能测量：同一条回答重复判 3 次，报分数标准差与通过 / 不通过翻转率（Spec 已有此项）。
- Pro 订阅有用量窗口，之前 Claude 复查 108 题就用完过额度。judge 脚本必须逐条缓存、可断点续跑，`--effort` 设 low 或 medium 省额度；约 1,500 条回答预计要分多个窗口跑完。
- Claude 不是被测厂商，主排序不受自家偏好污染，这是优点；但 Haiku 与 Sonnet 同厂商，满足不了 Spec 的「两个不同厂商的 judge 互相对照」，也做不了「自家模型偏好」实验。补法：再加一个百炼上的便宜 judge（如 deepseek-v4.1-flash），只判验证子集，花费约几元。
- Haiku 在 TeleQnA 答案复查上与默认模型的 kappa 只有 0.21。那是靠知识的任务，judge 有参考答案和 rubric 对照，难度低得多，但 Haiku 仍须先验证再用，不能默认可信。
- 复现：判分原始输出全部落盘，报告数字从落盘结果复算；重跑 judge 需要 Claude 订阅或 API key，脚本留出 API 后端（按价目表 Haiku 5.5 全量判分约 1–2 美元）。

**D2. judge 验证方式：不做大规模人工标注（用户 Oct 13：缺领域知识，也无预算请人）。**
建议用两层替代：
1. **构造真值（主要证据）**：用每道题已有的字段造出「正确得分已知」的回答变体，看 judge 能不能判对，不需要领域知识。
   - 完整参考答案：应接近满分。
   - 删掉某个要点：该要点应判未覆盖。
   - 把根因换成 `excluded_hypotheses` 里的错误假设：根因要点应判未覆盖，且触发扣分项。
   - 插入一条 `high_risk_actions`：应触发高危一票否决。
   - 同义改写、注水加长：分数应不变（顺带完成 Spec 的长度偏差实验）。

   报告指标是各类检查的检出率与误报率。变体由模型按指令生成，用户抽查约 30 条「这句话还在不在」即可，属于对照文本的检查，不需要专业判断。
2. **真实回答上的分歧仲裁（补充证据）**：几个 judge 在真实回答上判法不一致的要点，用户对照参考答案仲裁其中 50–80 个（约 1–2 小时）。连对照参考答案都判断不了的要点本身就是结论：这类必须交给专家。

局限要写进报告：构造真值只覆盖界限清楚的情况，真实回答里的模糊表述正是需要人判断的地方。Spec 的「Judge 元评测」一节和验收标准「judge 与人工的一致性在留出集上报告」需随之修订；Spec 该节已标注待修订，定了再改。

**D3. 精度回归设置**：建议三档（FP16 / INT8 / INT4）都在 AutoDL 上用同一推理引擎跑，笔记本只用来调试；否则硬件、引擎、量化格式同时变化，违背「只改精度一个变量」。门禁条件 3「高危错误率任一上升即不通过」在 45 题上多一次就触发，要么写明刻意从严，要么改为与 FP16 重跑的噪声底比较，跑之前定。

**D4. 思考对照的客观题抽样**：150 题 × 1 次，粗算 80% 功效下最小可检出差距约 7–9pt，而 440 题是全员答对的天花板题，大概率得到「不显著」。可选：接受并在报告写明可检出差距；或从 284 道有区分度的题里抽，但不能按「关思考时答错」选题（会有均值回归，重跑本身就会「变好」），要按跨模型区分度选，并以噪声底那一遍（rep）作对照。另外 `configs/models.yaml` 里开思考的采样参数还没填。

**D5. 提前降级**（建议）：砍 CMMLU / C-Eval 锚点（只有 7 个模型，排序相关性几乎没有检验力）；污染检测改写对照降级（造并核验 100–200 道改写题人工成本高），保留 TS-Guessing；追问施压直接按 10 个场景做；TeleLogs 抽约 200 题。

**D6. 版本梯度的口径**：见第四节第 2 项「版本梯度」。补置换检验，或把措辞改为「未见显著版本梯度（探索性）」。修改 `analysis/objective_analysis.py` 的说明文字后需在本地 Mac 上重新生成报告（`results/` 只在本地）。

## 四、已完成部分的关键结果（都可脚本复算）

### 1. TeleQnA 审计（第 1 阶段，Oct 12）

- 数据：`data/raw/TeleQnA/TeleQnA.json`（1 万题，以此为准，`test.json` 不用）；`data/raw/TeleLogs/troubleshooting/{train,test}.json`（测试集 864 题，8 类根因各 108 题，答案在 `\boxed{}`，可规则判分）。
- 取三类 3500 题；审计后保留 3381 题（去重剔 58、结构清洗、答案核验）。
- 答案抽样核验（300 题分层，Oct 11）：疑似错误 1.0%（95% CI 0.3–2.9%），有歧义或无法核实约 11%，全部剔除或修正（3 题改答案，37 题剔除）。
- 全量答案复查（只覆盖测试集）：Haiku 粗筛 + 默认模型复查，默认模型复查 108 题后额度耗尽。替代复查者与默认模型校准（门槛 kappa ≥ 0.6）：MiniMax-M3 0.29、Haiku 5.5 0.21，均不达标。剩余 109 题按投票（Haiku×2 + MiniMax×2 中 ≥3 判正确保留）：保留 23、剔除 86；该规则在校准题上保留精确率 81%，估计约 4 道有问题的题留在测试集（0.6%）。投票规则的依据：同一 300 题上，Haiku 找到默认模型所判问题题的 89%，但其标为有问题的题只有 54% 得到默认模型认可（二分类 kappa 0.61），单用 Haiku 会误删约一半。
- 运维相关度（规范 `docs/rubrics/ops_relevance_v3.md`）：v1→v2 试标 200 题，默认模型与 Haiku 在「≥2」上的 kappa 由 0.60 升至 0.73；v2 下约 19% 的题运维相关（≥2），3 级约 1%。全量由 Haiku 按 v3 标注，相关度 ≥2 共 826 题。
- **客观题测试集 731 题**（`data/processed/teleqna_test_subset.csv`）：RAN 209、CORE 163、TRANSPORT 227、OAM 78、SERVICE 41、SECURITY 13；打乱策略 free 667 / pin_last 60 / no_shuffle 4。
- 相关度人工抽检（用户盲标 40 题，二分类）：与模型标签一致率 58%、kappa 0.11，很低。已作为局限写入 `reports/audit/teleqna_relevance.md`：「运维相关」只能作为模型判定报告。用户认为很多题「看着有必要但运维人员实际不掌握」。
- 报告：`reports/audit/*.md`。

### 2. 客观题横评（第 2 阶段，Oct 12 夜）

- 执行：`scripts/build_mcq_variants.py`（5 子集变体，答案映射核验 0 不符）→ `scripts/run_objective.py`（EvalScope，温度 0、关思考、max_tokens 256、缓存补缺）。7 模型 × 731 题 × 5 子集（orig / rep / s1–s3）= 25,585 次调用全部成功，抽取失败 4 例（deepseek-v4.1-flash 3、kimi-k3 1，记 0 分）。原始结果在本地 `results/evalscope/objective/<模型>/`。
- 分析层：`analysis/objective_analysis.py` → `reports/objective/objective_main.md`，已按三方复核（统计方法 / 数据完整性 / Spec 合规）修订；35 格正确率、抽取失败、打乱映射方向、噪声底、维度拆分均独立复算一致。
- 正确率（5 子集 pooled）：kimi-k3 90.1% > qwen3.8-max 89.4% > qwen3.7-plus 87.5% > deepseek-v4-pro 87.0% > deepseek-v4.1-flash 86.1% > qwen3.8-flash 86.0% > glm-5.2 85.3%。
- 检验：McNemar（orig，exact，Holm 21 对）+ 题级配对置换检验。Holm 后显著：kimi-k3、qwen3.8-max 强于 glm-5.2、qwen3.8-flash、deepseek-v4.1-flash；中游 4 模型两两不可分。
- 功效（事后补算）：不一致对率约 11%，80% 功效最小可检出差距 ≈3.5pt（未校正）/ ≈4.8pt（Holm）；相邻名次差距 0.3–1.9pt，现有规模分辨不出，「不显著」≠「无差异」。场景题 40–50 题只能分档。
- 噪声底：orig 与 rep 逐题同答案率 94.5–99.5%（glm-5.2 最低，rep 差 1.37pt）。
- 打乱掉分（free 667 题）：+0.45 ~ +1.60pt。
- 区分度：35 次判定全对 440/731 题、全错 7 题，区分度偏低本身是可报告的负结果。
- **版本梯度（口径有问题，待处理，见 D6）**：Rel-18 打乱掉分 +2.17%，Rel-17 +0.39%（各约 173 / 147 道 free 题）。报告与旧进展文档写的是「越新的 Release 越可能进预训练语料、方向符合预期」，但 Spec 事先写的是「看信号是否随版本变新而**减弱**」，方向相反，属于看完数据改假设。差值没做显著性检验，粗估其标准误约 2pt，差值在噪声范围内；两组金标位置分布接近（前两位占比 0.49 vs 0.50），位置偏置解释不了，也撑不起显著性。补检验前只作探索性观察，不当发现写进报告。

### 3. 场景题初稿（第 3 阶段，Oct 13）

- 产物：`data/scenarios/scenarios_draft.json`（45 题，稳定 ID）；分批草稿 `data/scenarios/drafts/<批次>.v{0,1,2}.json`（v2 为核验修订后版本，merge 脚本优先取 v2）。每题含 rubric_points（id / stage / text / weight / verifiability / source_note，权重和 = 100）、deductions、high_risk_actions、discriminating_trap、excluded_hypotheses、unverified_residuals。
- 构成：diagnosis 22 / consulting 12 / kpi 11；RAN 15、CORE 7、TRANSPORT 8、OAM 9、SERVICE 4、SECURITY 2；难度 d2 22 / d3 23；要点可核验类型 standard 64 / constructed 119 / common_sense 156；37/45 题带 `unverified_residuals`。
- 补题：跨批查重发现 4 组重复，用 `supp-a` 新写 4 道诊断题替换（SC-D23 5G 切片 #62、SC-D24 VoLTE 上行单通、SC-D25 4G EPC S6a、SC-D26 QoS/5QI GBR），RAN 由 17 降到 15、SERVICE 由 2 升到 4。被替换题 SC-D03/D06/D09/D10 留空号不重排。
- 两层事实核验：
  1. 三票跨厂商粗筛：`scripts/verify_three_vote.py`（glm-5.2 / kimi-k2.6 / qwen3.8-27b，温度 0，结构化 JSON，缓存增量）。
  2. subagent 逐题复核（5 批 × 9 题）。subagent 驳回了 74 条三票标记，包括三票一致判 must_fix 但实际正确的（SC-D04 模三干扰根因、SC-D08 T3346 确为 5GMM backoff、SC-K09 #26/#67 引用无误）。
- 已应用的修订（`scripts/apply_verification_fixes.py`，只改确认项）：1 处 major（SC-D23 #62 触发条件 + 去答案泄露 + 补前提）、3 处参考答案内部矛盾（SC-D16/K02/K06）、若干引用精度项、2 处可核验性降级（K06 P4、C12 P3）。
- TS 条款号人工查证（用户核对 8 条）：查出 3 处引用错误并已修正：
  - SC-C02 P8：NR 无「PCI confusion」同名条款，改引 TS 38.300 §15.3.3 ANR 与 §15.5.6 PCI Optimisation。
  - SC-C07 P2：同步精度改引 TS 38.133 §7.4，删除 TS 38.104。
  - SC-C01 P3：MME 池负载均衡改引 TS 23.401 §4.3.7.2/§4.3.7.3，删除只适用于 GERAN/UTRAN 的 TS 23.236 NNSF。

  其余 5 条核对无误。
- 机器校验 `scripts/check_scenarios.py`：当前 0 错 0 警。

## 五、决定日志（按时间）

| 日期 | 决定 |
| --- | --- |
| Oct 11 | 场景题由 60–80 压到 40–50 题，省下的时间投入人工标注（后者 Oct 13 改为待定，见 D2）。 |
| Oct 11 | 主实验与精度回归关闭思考；另做思考模式对照（上线形态），最终推荐以开思考形态为准。 |
| Oct 11 | 被测 7 模型 4 家厂商（Qwen 3、DeepSeek 2、智谱 glm-5.2、Kimi），全部经百炼；glm-5.3 只进思考对照。 |
| Oct 11 | 简单的 subagent 任务交给 Haiku（写入 `CLAUDE.md`）。 |
| Oct 11 | 答案抽样核验中有问题的题全部剔除或逐项确认；全量核验两阶段（Haiku 粗筛 + 强模型复查）。 |
| Oct 11 | 百炼上不再使用 `qwen3.8-2.4t-a95b` 等高消耗模型。 |
| Oct 12 | 客观题测试集改为运维相关子集（相关度 ≥2），全集只做审计统计；清洗不必逐题精修。 |
| Oct 12 | 替代复查者校准不达标，剩余 109 题按 4 人投票（≥3 判正确保留）。 |
| Oct 12 | 思考对照：7 模型（去掉 kimi-k3，保留 glm-5.3）× 客观题 150 题 × 1 次 + 场景题 × 3 次，约 ¥130。kimi-k3 因输出价 ¥100/百万 token 不参加上线形态排名，报告须写明这是成本原因。 |
| Oct 12 | 主实验 ¥36 获批后启动（中途因计费渠道疑虑暂停一次，确认免费额度优先抵扣后全部启动）。 |
| Oct 12 | qwen3.7-plus 限时 8 折只能走现金（全程约 ¥4），充值保留，不砍模型。 |
| Oct 13 | 场景题本轮只做去重补题，不新增 d1 难度题。 |
| Oct 13 | 场景题核验两层：三票跨厂商只作粗筛，subagent 逐题核验才定案；只改确认项，驳回项不动。修订按推荐顺序：SC-D23 major + 3 处矛盾 + 引用精度项。 |
| Oct 13 | 8 条 TS 条款号由用户人工查证，3 处错误已修正。 |
| Oct 13 | 仓库保持 public，不改 private、不重写历史；接受 `b64b88a` 中约 150 条核查证据文字（复述题目选项与答案）公开。 |
| Oct 13 | `results/`、`data/raw/` 等不入库内容只在用户本地 Mac，用户知情。 |
| Oct 13 | 状态文档合并为本文件（取代 `项目进展总结.md`、`交接文档.md`），Spec 只放方案（升为 v2.3）。 |
| Oct 13 | judge 提示词 v1→v2→v3 迭代保留。judge 模型（D1）与验证方式（D2）待定。 |

## 六、环境、费用与账号

- 代码：GitHub `qianqiuqiu/Telecom_OM_LLM_Evaluation`（public）。场景题已合入 main（`e2855cf`）。
- 不入库、只在用户本地 Mac 的：`results/`（全部原始请求与响应，25,585 次横评调用、核验原始输出等）、`data/raw/`（TeleQnA、TeleLogs）、`.env`、`.venv`。云端会话里没有这些，跑不了依赖它们的脚本（分析层、费用估算等），只能改代码和文档。
- 原文与证据文字只放 `results/`、`data/raw/`；`data/processed/` 只放 ID 与标签。
- 所有被测模型经阿里云百炼 OpenAI 兼容接口（`.env` 的 `LLM_BASE_URL`、`LLM_API_KEY`）。HF token 在用户 `~/.zshrc`。
- 余额（Oct 13）：学生代金券约 ¥259.7，现金 ¥9.14。主实验实际消耗远低于估算（免费额度抵了大半，代金券只扣 ¥1 多）。
- 计费规则：免费额度优先于代金券；**代金券不能抵扣打折模型和厂商直供路由**，qwen3.7-plus 限时 8 折只扣现金（Oct 12 曾因现金欠费 ¥0.03 导致全部模型 403；再遇全模型 403 先查欠费）。不用带厂商前缀的路由（`kimi/`、`ZHIPU/` 等）。
- 已定规模（`analysis/cost_estimate.py` → `reports/cost_estimate.md`）：主实验约 ¥36；思考对照约 ¥130（依据 10 题试跑，花 ¥3.35：多数模型每题思考 1.1k–2.2k token，qwen3.8-flash 约 4.9k，glm-5.3 约 9.7k 且 16384 上限会截断）。judge 与追问施压尚未估算，剩余预算约 ¥80；若 judge 走 Claude 订阅（D1），judge 不占百炼预算。
- Claude 额度：Pro 订阅，额度紧张，大批量工作优先用便宜方式。

## 七、工作约定与踩过的坑

**用户偏好**：讲主线、少堆细节，每次汇报先说这一步在整体流程中的位置；花钱、大批量、提交 git 之前先列清单等确认；结论要有数字且能脚本复算；常识不要包装成发现。

**踩过的坑**
- 三票 / 多模型核验在「标准条款引用」上误报率高（见第四节第 3 项）。改题前必须逐题人工或强 subagent 复核；模型给出的 TS 条款号需人工查证（本轮 8 条查出 3 条错）。
- 子 agent 会抄错题目 ID（出现过 9076↔5076）、漏标；批量标注后必做 ID 覆盖校验。
- WorkBuddy（`mcp__workbuddy__*`）worker 会沿用上一任务上下文：出现过照抄另一轮结果、编造 ID、只返回 "test"、全判 correct 不给证据、长任务卡住 70+ 分钟。对策：同块独立复查由不同 worker 做（两轮之间 `stop_workers`），每任务 ≤20 题，收回后做 ID 覆盖与独立性检查（`scripts/ingest_workbuddy_review.py`：证据平均相似度 > 0.4 视为不独立）。复查类任务不能用被测模型家族（GLM、Kimi、DeepSeek、Qwen）。
- macOS 默认 zsh：`for t in $T` 不会按空格拆分变量，后台等待脚本曾因此空等一小时；用数组或直接写列表。
- Python 判空陷阱：`'' in 'ABCDE'` 为 True，判空必须用 `list()`（已在 `analysis/objective_analysis.py` 注释）。
- `scripts/audit_teleqna.py` 在重复簇代表题被剔除时会改选同簇另一题；这类题（question 2745、4242）没有标注和核验，`scripts/build_test_subset.py` 会把它们排除在子集外。
- 场景题 ID 稳定：被替换 / 删除的题留空号（当前 SC-D03/D06/D09/D10 空缺），不要重排，否则核验记录与草稿的 `source_draft` 映射会错乱。
- 温度 0 + 固定 seed 在 API 端也不可复现（Oct 11 实测），所有模型都要测噪声底。
- 在 git worktree 里工作时，`results/`、`data/raw/`、`.env`、`.venv` 需软链到主目录（写入 `.git/info/exclude`）；worktree 里没有 `.env`，`scripts/verify_three_vote.py` 的 `load_env()` 会顺着 `.git` 文件的 gitdir 回到主目录读取，新脚本照此处理。

## 八、关键文件索引

| 文件 | 内容 |
| --- | --- |
| `通信网络运维助手 · 大模型选型评测 Spec.md` | 方案（v2.3） |
| `configs/models.yaml` | 被测模型与思考开关参数 |
| `data/processed/teleqna_test_subset.csv` | 客观题测试集（731 题） |
| `data/processed/teleqna_{items,relevance,answer_decisions}.csv` | 审计标记 / 相关度 / 答案决定 |
| `docs/rubrics/ops_relevance_v{1,2,3}.md` | 相关度标注规范 |
| `reports/audit/*.md`、`reports/cost_estimate.md` | 审计与费用报告（脚本生成） |
| `analysis/objective_analysis.py` → `reports/objective/objective_main.md` | 横评分析层与报告（脚本生成） |
| `data/scenarios/scenarios_draft.json` | 场景题初稿（45 题，稳定 ID，脚本生成） |
| `data/scenarios/drafts/<批次>.v{0,1,2}.json` | 场景题分批草稿（v2 = 核验修订后） |
| `scripts/merge_scenario_drafts.py`、`check_scenarios.py` | 合并草稿；场景题机器校验 |
| `scripts/verify_three_vote.py`、`consolidate_verification.py`、`apply_verification_fixes.py` | 三票核验、汇总分级、应用修订 |
| `results/`（本地） | 横评逐题预测（`evalscope/objective/<模型>/`）、核验原始响应（`scenarios/{three_vote,perquestion}/`、`audit/`） |
