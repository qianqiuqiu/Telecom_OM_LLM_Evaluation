# 通信网络运维助手 · 大模型选型评测

模拟运营商为网络运维助手选底座大模型：客观题横评、场景题 judge 打分与元评测、追问施压、量化精度回归。
方案详见 [Spec](通信网络运维助手%20·%20大模型选型评测%20Spec.md)。

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
| `data/scenarios/` | 自写中文场景题、rubric 与参考答案 |
| `configs/` | 被测模型清单、EvalScope 任务配置 |
| `scripts/` | 数据审计、污染检测、追问施压、模型探测 |
| `analysis/` | 统计检验、judge 元评测、回归门禁 |
| `results/` | 原始请求与响应（不入库） |
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
