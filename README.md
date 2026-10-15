# 通信网络运维助手 · 大模型选型评测

模拟运营商为网络运维助手选底座大模型：客观题横评、场景题 judge 打分与元评测、追问施压、量化精度回归。
方案详见 [Spec](通信网络运维助手%20·%20大模型选型评测%20Spec.md)，进展、下一步与决定日志见 [STATUS](STATUS.md)。

## 环境

```bash
uv sync
cp .env.example .env   # 填入百炼工作空间的 LLM_BASE_URL 与 LLM_API_KEY
```

原始数据集需在 Hugging Face 同意使用条件后自行下载到 `data/raw/`（仓库不重新分发）：

- TeleQnA：`netop/TeleQnA` → `data/raw/TeleQnA/`

## 目录

| 目录 | 内容 |
| --- | --- |
| `data/raw/` | 原始数据集（不入库） |
| `data/processed/` | 审计筛选后的题目 ID 清单 |
| `data/scenarios/` | 自写中文场景题、rubric 与参考答案；judge 探针（`judge_probes/`）、调试 / 留出划分、分歧仲裁表（`arbitration/`） |
| `configs/` | 被测模型清单、EvalScope 任务配置 |
| `scripts/` | 数据审计、污染检测、追问施压、模型探测 |
| `analysis/` | 统计检验、judge 元评测与两档 / 跨厂商对照、场景题横评、回归门禁 |
| `results/` | 原始请求与响应。不被 `.gitignore` 忽略；已入库 `answers/`、`judge/`、`audit/`，其余（横评 `evalscope/`、核验原始响应、`answers/raw/`）只在本地，提交时手动排除 |
| `reports/` | 生成的报告与图表 |
| `docs/` | 文档与历史版本 |

## 常用命令

```bash
uv run python scripts/probe_models.py   # 检查被测模型可用性与思考开关
```

TeleQnA 审计（选项结构 + 近重复），按顺序执行：

```bash
uv run python scripts/audit_teleqna.py               # 选项结构、字面近重复候选
uv run python scripts/embed_teleqna.py               # 题干 embedding（语义候选）
uv run python scripts/adjudicate_pairs.py            # LLM 裁决候选对
uv run python scripts/build_pair_validation.py       # 分层抽样，生成盲标批次
uv run python analysis/pair_adjudicator_agreement.py # 裁决器与盲标的一致性
uv run python scripts/audit_teleqna.py               # 汇总，生成最终标记与报告
```

盲标结果存于 `data/processed/teleqna_pair_validation.csv`（由 Claude 子 agent 标注，非脚本产出）。

答案全量核验与测试子集（运维相关度 ≥ 2），按顺序执行：

```bash
uv run python scripts/answer_check_full.py           # 生成全量核验 workflow（Haiku 盲答 → 粗筛 → 默认模型复查）
uv run python scripts/ingest_workbuddy_review.py     # 收回 WorkBuddy（MiniMax-M3）复查，校验 ID 并与默认模型校准
uv run python scripts/ingest_haiku_review.py         # 收回 Haiku 复查（workflow 输出），校准并给出投票规则所需数据
uv run python analysis/answer_check_full.py          # 汇总决定：默认模型复查；其余按 4 人投票（≥3 判正确保留）
uv run python scripts/audit_teleqna.py               # 写入审计表 data/processed/teleqna_items.csv
uv run python analysis/relevance_summary.py          # 相关度报告
uv run python scripts/build_test_subset.py           # 最终测试子集 data/processed/teleqna_test_subset.csv
```

复查原始输出与证据文字在 `results/audit/answer_check_full/`（已入库）。

费用估算与客观题横评（7 模型 × 731 题 × 5 子集），按顺序执行：

```bash
uv run python analysis/cost_estimate.py              # 费用估算 → reports/cost_estimate.md
uv run python scripts/build_mcq_variants.py          # 生成 5 子集变体（orig/rep/s1–s3）
uv run python scripts/run_objective.py --limit 3 --models qwen3.8-flash   # 冒烟
uv run python scripts/run_objective.py               # 全量（缓存补缺，结果在 results/evalscope/objective/）
uv run python analysis/objective_analysis.py         # 分析层 → reports/objective/objective_main.md
```

场景题（45 道中文场景题 + rubric）起草与两层事实核验，按顺序执行：

```bash
uv run python scripts/merge_scenario_drafts.py       # 合并各批次 v1 起最高版本的草稿 → scenarios_draft.json（稳定 ID，被替换题留空号）
uv run python scripts/check_scenarios.py             # 机器校验：ID/权重和/verifiability/stage/分布（0 错 0 警为通过）
uv run python scripts/verify_three_vote.py           # 三票跨厂商事实核验（glm-5.2/kimi-k2.6/qwen3.8-27b，缓存增量）
uv run python scripts/consolidate_verification.py    # 汇总三票 + subagent 逐题判定为分级清单
uv run python scripts/apply_verification_fixes.py    # 应用确认的修订，生成 v2 草稿
uv run python scripts/apply_freeze_fixes.py          # 定稿前修订（补参考答案缺口），生成 v3 草稿；之后重跑 merge 与 check
```

三票核验与逐题判定的原始响应在 `results/scenarios/{three_vote,perquestion}/`（不入库）。

场景题 judge 与元评测（构造真值探针），按顺序执行：

```bash
uv run python scripts/make_judge_split.py            # 调试集 / 留出集（按题划分，已生成并入库，不再重抽）
uv run python scripts/build_judge_probes.py segment  # 参考答案切分映射（百炼 qwen3.8-max，缓存增量）
uv run python scripts/build_judge_probes.py build    # 构造探针 + 参考答案缺口清单 + drop 探针抽查表
uv run python scripts/judge_scenarios.py --answers data/scenarios/judge_probes/probes.jsonl \
    --judge claude:claude-haiku-5-5 --prompt v2 --run probes_v2 --split debug   # judge 判探针（云端会话，订阅额度；v2 已锁定）
uv run python analysis/judge_meta.py --run probes_v1 --split debug              # 元评测报告 → reports/judge/
```

真实回答判分、两档对照与仲裁、场景题横评（云端会话）：

```bash
uv run python scripts/judge_scenarios.py --answers results/answers/main_off.jsonl \
    --judge claude:claude-haiku-5-5 --prompt v2 --run main_off                   # Sonnet 同样再判一遍
uv run python analysis/judge_agreement.py --run main_off --answers results/answers/main_off.jsonl
    # 一致性、长度偏差、仲裁抽样 → data/scenarios/arbitration/；仲裁表填完后重跑 → 最终主分 final_scores.csv
uv run python analysis/scenario_analysis.py --run main_off                      # 横评分档 → reports/scenarios/main_off_main.md
```

跨厂商 judge（Mac，百炼 key；规则见 STATUS 决定日志 Oct 14）：

```bash
uv run python scripts/judge_scenarios.py --answers results/answers/main_off.jsonl \
    --judge bailian:deepseek-v4.1-flash --prompt v2 --run main_off --limit 2     # 先冒烟 2 条，看 jsonl 里 ok 与 parsed
uv run python scripts/judge_scenarios.py --answers data/scenarios/judge_probes/probes.jsonl \
    --judge bailian:deepseek-v4.1-flash --prompt v2 --run probes_v2 --split holdout --workers 4
uv run python scripts/judge_scenarios.py --answers results/answers/main_off.jsonl \
    --judge bailian:deepseek-v4.1-flash --prompt v2 --run main_off --workers 4
git add results/judge/probes_v2/bailian_deepseek-v4.1-flash.* results/judge/main_off/bailian_deepseek-v4.1-flash.*
```

跨厂商 judge 的分析（云端会话，只读入库数据）：

```bash
uv run python analysis/judge_meta.py --run probes_v2 --split holdout          # 三个 judge 的留出集探针元评测同表
uv run python analysis/judge_agreement.py --run main_off --answers results/answers/main_off.jsonl \
    --main bailian_deepseek-v4.1-flash --second claude_claude-haiku-5-5_medium --compare-only   # 对 Sonnet 同理
uv run python analysis/judge_cross_vendor.py --run main_off --answers results/answers/main_off.jsonl   # 自家偏好检验
```

judge 后端：`claude:<模型 ID>` 经 Claude Code 无头模式（`claude -p`，订阅额度），`bailian:<模型 ID>` 经百炼。加 `--dry-run` 只看发送的提示，加 `--repeats 3` 测 judge 自身稳定性。判定记录在 `results/judge/<run>/`（入库）。

**运行位置（Oct 14 起）**：`claude` 后端的 judge 一律在 Claude Code 云端会话里跑（仓库已带齐探针、题目、提示词与划分，容器自带已登录的 `claude`），每跑完一轮立即把 `results/judge/<run>/` 与 `reports/judge/` 提交推送，容器回收前没提交的会丢（缓存可续跑补回）。需要百炼 key（`.env`）的步骤仍在 Mac 上跑：回答生成、`build_judge_probes.py segment`、三票核验、`bailian:` judge；生成的 `results/answers/<run>.jsonl` 提交入库后再到云端判分。`results/` 其余内容（横评、核验原始响应、`results/answers/raw/`）仍只在 Mac 本地。**注意：三票在「标准条款引用」上误报率高，只作粗筛；改题前必须逐题人工/强 subagent 复核，TS 条款号需人工查证。**

不依赖 judge 的并行项（Mac；规则见 STATUS 决定日志 Oct 15）：

```bash
uv run python analysis/distractor_audit.py prepare --out <scratchpad 目录>  # 干扰项抽查：抽样与标注批次（含原文，不入库）
uv run python analysis/distractor_audit.py report                          # 读标注 data/processed/teleqna_distractor_labels.csv → reports/audit/teleqna_distractors.md
uv run python scripts/contamination_ts_guessing.py --dry-run               # TS-Guessing：调用次数与粗估花费
uv run python scripts/contamination_ts_guessing.py                         # 7 模型 × 727 题 → results/contamination/ts_guessing.csv
uv run python analysis/ts_guessing_analysis.py                             # → reports/contamination/ts_guessing.md
uv run python scripts/run_telelogs.py --dry-run                            # TeleLogs：200 题分层抽样（data/processed/telelogs_sample.csv）
uv run python scripts/run_telelogs.py                                      # → results/telelogs/predictions.csv
uv run python analysis/telelogs_analysis.py                                # → reports/telelogs/telelogs_main.md
```

两个脚本的逐调用缓存（`results/{contamination,telelogs}/raw/`）含原题文本，已加进 `.gitignore`；入库的是只有 ID 与指标的 csv。

追问施压（10 个场景 × 3 轮写死的追问，第 1 轮复用 `main_off`；生成在 Mac，judge 走 `claude -p`）：

```bash
uv run python scripts/run_pressure.py --dry-run                            # 同时生成判分探针 data/scenarios/pressure/probes.jsonl
uv run python scripts/run_pressure.py                                      # → results/answers/pressure_off.jsonl
uv run python scripts/judge_pressure.py --answers data/scenarios/pressure/probes.jsonl \
    --judge claude:claude-haiku-5-5 --run pressure_probes                  # 先判探针（Sonnet 同样再判一遍）
uv run python scripts/judge_pressure.py --answers results/answers/pressure_off.jsonl \
    --judge claude:claude-haiku-5-5 --run pressure_off                     # 真实对话（Sonnet 同样再判一遍）
uv run python analysis/pressure_analysis.py                                # 探针合格检查 + 汇总 → reports/pressure/pressure_main.md
```

精度回归（qwen3.8-27b BF16 / FP8 / W4A16，同卡同引擎；一次只起一档，`<档>` 取 bf16 / fp8 / w4a16）：

```bash
bash serve.sh <档>        # 把 scripts/regression/serve.sh 传到 AutoDL 上跑，起 SGLang（127.0.0.1:30000）
ssh -f -N -L 30000:127.0.0.1:30000 -p <端口> root@connect.weste.seetacloud.com   # Mac 上开隧道
uv run python scripts/run_objective.py --models qwen3.8-27b-<档> --batch 16      # 客观题 5 子集
uv run python scripts/generate_answers.py --run regression_<档> \
    --model qwen3.8-27b-<档> --mode off                                    # 场景题（BF16 加 --repeats 2 作噪声参照）
uv run python scripts/run_pressure.py --model qwen3.8-27b-<档> \
    --t1 results/answers/regression_<档>.jsonl --out results/answers/pressure_regression.jsonl
uv run python scripts/judge_scenarios.py --answers results/answers/regression_<档>.jsonl \
    --judge claude:claude-haiku-5-5 --prompt v2 --run regression            # Sonnet 同样再判一遍
uv run python scripts/judge_pressure.py --answers results/answers/pressure_regression.jsonl \
    --judge claude:claude-haiku-5-5 --prompt v1 --run pressure_regression   # Sonnet 同样再判一遍
uv run python analysis/regression_gate.py                                  # 四条门禁 → reports/regression/regression_gate.md
```

场景题回答生成与天花板试跑（被测模型只看题干，统一用中性系统提示 `configs/assistant/system_v1.md`）：

```bash
uv run python scripts/generate_answers.py --run ceiling_pilot --model qwen3.8-flash \
    --model deepseek-v4.1-flash --mode off --dry-run                 # 先看调用次数与粗估花费，不调用
uv run python scripts/generate_answers.py --run ceiling_pilot --model qwen3.8-flash \
    --model deepseek-v4.1-flash --mode off                           # 生成（Mac）→ results/answers/ceiling_pilot.jsonl，提交入库
uv run python scripts/judge_scenarios.py --answers results/answers/ceiling_pilot.jsonl \
    --judge claude:claude-haiku-5-5 --prompt v1 --run ceiling_pilot  # 判分（订阅额度；试跑当时在 Mac 上跑）
uv run python analysis/ceiling_pilot.py --run ceiling_pilot          # 触顶判断 → reports/scenarios/ceiling_pilot.md
```

生成脚本按调用缓存（`results/answers/raw/<模型>__<mode>.jsonl`，不入库），中断后重跑同一命令续上。题目与参数不变时已有回答直接复用，例如正式的 7 模型关思考（`--group main --mode off`）会复用试跑的 90 份；思考对照用 `--mode on --repeats 3`。
