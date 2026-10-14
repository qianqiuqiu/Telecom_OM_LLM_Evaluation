# 项目状态（STATUS）

项目：通信网络运维助手 · 大模型选型评测。最后更新：2026-10-13。

本文件是唯一的状态文档：现状、下一步、待定决定、决定日志、注意事项都在这里。方案只看 `通信网络运维助手 · 大模型选型评测 Spec.md`（v2.4），用法与命令看 `README.md`。接手顺序：本文件 → Spec → `CLAUDE.md` → `README.md`。用户用中文交流。

## 一、现在在哪

```
1 准备考卷（TeleQnA 审计与清洗）               已完成：客观题测试集 731 题
2 客观题横评（7 模型 × 731 题 × 5 子集）        已完成：分析层 + 三方复核，reports/objective/objective_main.md
3 出主观题（40–50 道中文场景题 + rubric）       收尾已做（v3）；天花板试跑已完成（触顶 3/45，照常定稿），待定稿 v1.0 ← 现在
4 阅卷（规则判分 + LLM judge）                 judge 工具链已就绪（见第四节第 4 项），未正式判分
5 检验裁判（judge 元评测）                     探针已生成（337 个，参考答案缺口 0）
6 出结论（横评、思考对照、追问施压、精度回归、选型报告） 未开始
```

探针已生成，场景题收尾已做，天花板试跑已完成（触顶 3/45 → 照常定稿），下一步定稿 v1.0。这一段是整个项目最容易返工的地方：场景题 → 模型回答 → judge 验证 → judge 提示词 → 全量判分环环相扣，上游一改，下游作废，所以按第二节的顺序走。

## 二、下一步（建议顺序）

每一步定稿后打 git tag，下游只认 tag。花钱或大批量调用前先列清单确认。

1. ~~**切分映射**~~（Oct 13 完成，`8acabc0`）：45/45 题映射合格，探针 337 个，参考答案缺口 10 个。
2. ~~**场景题收尾**~~（Oct 13 完成，v3 草稿）：10 个缺口已补（见第四节第 3 项）；48 条待核验项已分诊（`data/scenarios/residuals_triage.csv`），无需删题或降级。改过的 10 题已在 Mac 上重切（`53d5dbe`）：45/45 题映射合格，探针仍为 337 个，缺口 0，每个补写的要点都映射到了补的那句话。剩一件小事：4 条进入计分的取值建议用户对照协议原文核对（表中 `建议核对`），定稿前做完即可。
3. ~~**天花板试跑**~~（Oct 13 完成，报告 `reports/scenarios/ceiling_pilot.md`）：90 份回答（`e5c3f35`）全部判成，0 失败。触顶 **3/45**（SC-K02、SC-D26、SC-K01），未超过 15 → **照常定稿，不加难度**。均值 deepseek-v4.1-flash 62.7、qwen3.8-flash 47.9，单题 ≥85 的分别有 12 题、5 题。结论稳健：把一票否决和扣分全部去掉、只看要点原始分，触顶也只有 5 题，门槛降到 80 是 8 题，要降到 75 才到 16 题。需要留意：一票否决 22/90 条（qwen 14、deepseek 8），摘录核对找不到 19/657。这是未经验证的 Haiku v1 的判定，可能有误触发，留到第 5 步用探针检验，不据此改提示词。原计划：qwen3.8-flash、deepseek-v4.1-flash 关思考各答 45 题（`scripts/generate_answers.py`，90 次调用，粗估 ¥0.8），Haiku + 提示词 v1 判这 90 份（订阅额度），`analysis/ceiling_pilot.py` 按事先定的规则出结论：某题两个模型都 ≥ 85 分记为触顶，触顶超过 15 题（三分之一）就在定稿前给触顶题加难度，否则照常定稿（规则见第五节，跑之前入库）。Haiku v1 未经验证，只用来发现明显触顶；这批判定不拿来改 judge 提示词。客观题已有 440/731 题全员答对；场景题如果也全员高分，排序和 judge 验证都会失效，此时调难度比事后补救便宜。定稿不改题时，这 90 份回答在第 6 步直接复用。
4. **场景题定稿 v1.0**（打 tag）。之后改题只能出勘误版本，并标出受影响的回答和判分。定稿后重跑 `segment`（只重切改过的题）与 `build`，用户填 `spotcheck_drop.csv`（约 30 条，对照文字判断「是否还写到这个要点」）。
5. **judge 提示词迭代**：Haiku、Sonnet 各判调试集探针（约 165 个），`analysis/judge_meta.py` 出报告 → 改提示词 v2、v3（只看调试集）→ 锁定 → 留出集报最终数字，并抽一部分重复判 3 次测稳定性。
6. **生成与判分**：7 模型关思考 × 45 题（约 ¥9）；思考对照的回答（约 ¥130，花钱前确认）。用锁定的 judge 一次性判全部回答；跨厂商 judge（百炼）只判验证子集；两档 judge 分歧的要点抽 50–80 个由用户仲裁。
7. **不依赖 judge 的并行项**：精度回归客观题部分（门禁阈值先提交打 tag，见 D3）、污染检测 TS-Guessing、TeleLogs 子集、干扰项质量抽查（72 对选项完全相同的非重复题）。
8. 追问施压 → 选型报告、数据卡、回归报告 → 简历 bullet 与模拟面试。

## 三、待定决定（需用户拍板）

D1（judge 模型）、D2（judge 验证方式）已于 Oct 13 定下，见第五节与 Spec v2.4。

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

- 产物：`data/scenarios/scenarios_draft.json`（45 题，稳定 ID）；分批草稿 `data/scenarios/drafts/<批次>.v{0,1,2,3}.json`（v2 为核验修订后版本，v3 为定稿前修订；merge 脚本读 v1 起的最高版本）。每题含 rubric_points（id / stage / text / weight / verifiability / source_note，权重和 = 100）、deductions、high_risk_actions、discriminating_trap、excluded_hypotheses、unverified_residuals。
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
- 收尾（Oct 13，`scripts/apply_freeze_fixes.py` 生成 v3 草稿，merge 改为读 v1 起的最高版本）：
  - 参考答案缺口：映射发现 10 个要点在参考答案里没写到，照抄参考答案也拿不到分（6 个是后续改进 / 效果验证类：SC-D01 P8、D02 P8、D07 P8、D20 P7、C01 P8、D25 P7；4 个是机理 / 排除类：D16 P3、D23 P3、D24 P4、D26 P4）。每处在参考答案里补一两句，内容只取该要点自身的文字；要点、权重、扣分项、高危操作都没动。
  - 待核验项分诊（48 条，37 题）：a 条款 / 取值 16、b 已声明的构造或简化 21、c 题干缺信息 10、d 区分度 1。不确定内容进入计分文字的只有 5 条：4 条是协议取值（SC-D01 T310=ms50、SC-D04 CRS 模 6 频移、SC-D07 -120 dBm、SC-K09 #26/#67），按记忆都成立，但云端会话连不上 3GPP / ETSI，没有对照原文；另 1 条（SC-C05 绕行容量）是题干写明的保守假设，结论不受影响。c 类 10 条逐条看过，要点与扣分项都不罚考生提及这些因素，题干不用改。条号凭记忆的 SC-C10 source_note 已去掉条号。`check_scenarios.py` 会检查分诊表与 `unverified_residuals` 是否逐条对应。
- 机器校验 `scripts/check_scenarios.py`：当前 0 错 0 警。

### 4. judge 工具链（Oct 13，已冒烟测试，未正式运行）

- 设计见 Spec v2.4「Judge 元评测与提示词迭代」。judge 只输出逐项判定（要点 covered / partial / missed，扣分项、高危操作是否触发，各附原文摘录），程序按权重算总分（partial 记一半，扣分下限 0，高危一票否决），诊断题另报根因 / 处置两段得分率；程序核对摘录是否在回答里，用来发现编造证据。
- 后端：`claude:<模型 ID>`（`claude -p` 无头调用，`--json-schema` 约束输出，记录实际返回的模型名）；`bailian:<模型 ID>`（关思考、温度 0）。逐条缓存（键 = 提示词 + judge + effort + 题目评分信息 + 回答文本），可断点续跑；额度用尽或限流时自动停止，重跑同一命令续上；判定校验不通过的记录落盘、计入失败率并在下次重试。
- 探针（每题约 7–8 个）：full、drop:Pk ×2、wrong_root（诊断题）、risk_add、risk_neg、pad、empty；45 题共约 335 个，调试集约 165 个。
- 调试集 / 留出集已生成并入库：`data/scenarios/judge_split.csv`（种子 20261013；consulting 6/6、diagnosis 11/11、kpi 5/6）。
- 回答生成 `scripts/generate_answers.py`（试跑与第 6 步正式生成共用）：被测模型只看题干，统一用中性系统提示 `configs/assistant/system_v1.md`；思考开关与采样参数取 `configs/models.yaml`（模型条目可用 `params` 覆盖，开思考的参数待 D4 补齐），只能开思考的模型不跑 off；每次调用记录最终答案、推理过程、token（含思考）、首 token 时延、首个答案 token 时延、总时延与原价花费；逐条缓存（键 = 系统提示 + 模型 + 参数 + max_tokens + 题干 + 重复序号），报错或答案为空的落盘计为失败、下次重试。云端用假客户端测过缓存续跑、失败落盘、分组与守卫，未真实调用百炼。
- 冒烟测试（云端会话，临时目录，未入库）：Haiku 当映射模型切分 SC-D01、SC-K04 均合格，并发现 SC-D01 参考答案没写到 P8；Haiku judge 判 SC-D01 的 5 个探针，两个删要点都判出 missed，加高危建议触发一票否决，「不可取」提醒未误触发。也看到两处问题：映射模型认为参考答案写全了 P2，Haiku 只给 partial（full 探针的应得判定有软性）；同一段文字的 P4 一次 covered、一次 partial（judge 有波动）。只是流程检查，不作结论。

## 五、决定日志（按时间）

| 日期 | 决定 |
| --- | --- |
| Oct 11 | 场景题由 60–80 压到 40–50 题，省下的时间投入人工标注（人工标注 Oct 13 取消，见下方 D2 一行）。 |
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
| Oct 13 | judge 提示词 v1→v2→v3 迭代保留。 |
| Oct 13 | judge 定为 Claude Haiku 5.5 / Sonnet 5.5 两档，经 Claude Code 无头模式走 Pro 订阅（D1）；另加一个百炼 judge 只判验证子集，做跨厂商对照与自家偏好实验。 |
| Oct 13 | 不做大规模人工标注与 test-retest（缺领域知识，也无预算请人）；judge 元评测改为构造真值探针为主、judge 间一致性与 50–80 个分歧要点的人工仲裁为辅（D2）。Spec 升为 v2.4。 |
| Oct 13 | 场景题收尾：参考答案缺口一律补参考答案（不改 / 删要点），只用要点自身文字；改动走新一层草稿 v3，保留 v1 / v2 审计痕迹。待核验项按「是否进入计分文字」分诊，不进入计分的保留说明，不删题。 |
| Oct 13 | 天花板试跑判定规则（跑之前定，看完数据不改）：某题两个便宜模型（qwen3.8-flash、deepseek-v4.1-flash，关思考）得分都 ≥ 85 记为触顶；触顶超过 15 题（三分之一）则定稿前给触顶题加难度，否则照常定稿。Haiku v1 的试跑判定只用于这一判断，不用于改 judge 提示词。被测模型统一用中性系统提示，只给题干、不透露评分信息。 |
| Oct 13 | 天花板试跑结果：触顶 3/45，按事先定的规则照常定稿，不给触顶题加难度。 |

## 六、环境、费用与账号

- 代码：GitHub `qianqiuqiu/Telecom_OM_LLM_Evaluation`（public）。场景题已合入 main（`e2855cf`）。
- 不入库、只在用户本地 Mac 的：`results/`（全部原始请求与响应，25,585 次横评调用、核验原始输出等）、`data/raw/`（TeleQnA、TeleLogs）、`.env`、`.venv`。云端会话里没有这些，跑不了依赖它们的脚本（分析层、费用估算等），只能改代码和文档。
- 原文与证据文字只放 `results/`、`data/raw/`；`data/processed/` 只放 ID 与标签。
- 所有被测模型经阿里云百炼 OpenAI 兼容接口（`.env` 的 `LLM_BASE_URL`、`LLM_API_KEY`）。HF token 在用户 `~/.zshrc`。
- 余额（Oct 13）：学生代金券约 ¥259.7，现金 ¥9.14。主实验实际消耗远低于估算（免费额度抵了大半，代金券只扣 ¥1 多）。
- 计费规则：免费额度优先于代金券；**代金券不能抵扣打折模型和厂商直供路由**，qwen3.7-plus 限时 8 折只扣现金（Oct 12 曾因现金欠费 ¥0.03 导致全部模型 403；再遇全模型 403 先查欠费）。不用带厂商前缀的路由（`kimi/`、`ZHIPU/` 等）。
- 已定规模（`analysis/cost_estimate.py` → `reports/cost_estimate.md`）：主实验约 ¥36；思考对照约 ¥130（依据 10 题试跑，花 ¥3.35：多数模型每题思考 1.1k–2.2k token，qwen3.8-flash 约 4.9k，glm-5.3 约 9.7k 且 16384 上限会截断）。judge 与追问施压尚未估算，剩余预算约 ¥80；若 judge 走 Claude 订阅（D1），judge 不占百炼预算。
- Claude 额度：Pro 订阅，额度紧张，大批量工作优先用便宜方式。judge 走订阅额度：冒烟实测 Haiku（effort medium）每次判定输出约 2.2k–3.5k token（含思考）、10–15 秒；调试集探针一轮约 165 次。脚本按 API 价目折算的金额只用来估算额度，订阅不按此计费。

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
- judge 走 `claude -p` 时在空临时目录运行、不加载设置与 MCP，项目 CLAUDE.md 不会进入 judge 上下文；但用户级 `~/.claude/CLAUDE.md` 仍会被读入，里面不要放与评分相关的内容。云端会话里还会注入两段与评分无关的系统提醒。
- 在云端会话里跑 judge 时，`results/judge/` 随容器回收而丢失；要么在 Mac 上跑，要么跑完把结果拷出来。
- 映射模型不能与被检验的 judge 同一家（默认 qwen3.8-max），否则 judge 与「真值」共享同一套理解、一致率虚高。冒烟测试用 Haiku 当映射模型只为测流程，结果没有入库。
- 温度 0 + 固定 seed 在 API 端也不可复现（Oct 11 实测），所有模型都要测噪声底。
- 在 git worktree 里工作时，`results/`、`data/raw/`、`.env`、`.venv` 需软链到主目录（写入 `.git/info/exclude`）；worktree 里没有 `.env`，`scripts/verify_three_vote.py` 的 `load_env()` 会顺着 `.git` 文件的 gitdir 回到主目录读取，新脚本照此处理。

## 八、关键文件索引

| 文件 | 内容 |
| --- | --- |
| `通信网络运维助手 · 大模型选型评测 Spec.md` | 方案（v2.4） |
| `configs/models.yaml` | 被测模型与思考开关参数 |
| `data/processed/teleqna_test_subset.csv` | 客观题测试集（731 题） |
| `data/processed/teleqna_{items,relevance,answer_decisions}.csv` | 审计标记 / 相关度 / 答案决定 |
| `docs/rubrics/ops_relevance_v{1,2,3}.md` | 相关度标注规范 |
| `reports/audit/*.md`、`reports/cost_estimate.md` | 审计与费用报告（脚本生成） |
| `analysis/objective_analysis.py` → `reports/objective/objective_main.md` | 横评分析层与报告（脚本生成） |
| `data/scenarios/scenarios_draft.json` | 场景题初稿（45 题，稳定 ID，脚本生成） |
| `data/scenarios/drafts/<批次>.v{0,1,2,3}.json` | 场景题分批草稿（v2 = 核验修订后，v3 = 定稿前修订） |
| `scripts/merge_scenario_drafts.py`、`check_scenarios.py` | 合并草稿（读最高版本）；场景题机器校验 |
| `scripts/verify_three_vote.py`、`consolidate_verification.py`、`apply_verification_fixes.py` | 三票核验、汇总分级、应用修订（→ v2） |
| `scripts/apply_freeze_fixes.py`、`data/scenarios/residuals_triage.csv` | 定稿前修订（补参考答案缺口 → v3）；48 条待核验项分诊表 |
| `scripts/judge_scenarios.py`、`configs/judge/judge_v1.md` | 场景题 judge（claude / bailian 两种后端）与提示词 v1 |
| `scripts/make_judge_split.py` → `data/scenarios/judge_split.csv` | 调试集 / 留出集（按题划分，22 / 23 题） |
| `scripts/build_judge_probes.py` → `data/scenarios/judge_probes/` | 切分映射与构造真值探针、参考答案缺口清单、drop 探针抽查表 |
| `analysis/judge_meta.py` → `reports/judge/` | judge 元评测报告（探针检出率、误报率、稳定性） |
| `scripts/generate_answers.py`、`configs/assistant/system_v1.md` | 场景题回答生成（试跑与正式生成共用，缓存续跑）与被测模型系统提示 |
| `analysis/ceiling_pilot.py` → `reports/scenarios/` | 天花板试跑分析（按事先定的触顶规则出结论） |
| `results/`（本地） | 场景题回答（`answers/`）与判定（`judge/`）、横评逐题预测（`evalscope/objective/<模型>/`）、核验原始响应（`scenarios/{three_vote,perquestion}/`、`audit/`） |
