"""相关度人工抽检（v3 标签）：从试标 200 题中分层抽 40 题，生成给本人盲标的清单（不显示模型标签）。

设计（Oct 12）：本人只做二分类——“运维工程师日常会不会用到这道题考的知识”（会 / 不会 / 不确定），
对应相关度 ≥ 2（进入测试集）与 ≤ 1 的边界；抽检的目的是检验测试集筛选是否可信，四级细分不作要求。
分层：当前标签 ≥ 2 抽 16 题、= 1 抽 16 题、= 0 抽 8 题（只从审计后保留的题中抽）。

输入：
  data/processed/teleqna_relevance_pilot_ids.csv   试标 200 题
  data/processed/teleqna_relevance.csv              当前（v2/v3）全量标签
  data/processed/teleqna_items.csv                  审计标记
  data/raw/TeleQnA/TeleQnA.json                     题干（不入库）
输出：
  data/processed/teleqna_relevance_spotcheck_ids.csv   抽检序号与题目 ID（不含标签，可入库）
  results/audit/relevance/spotcheck_v3.md               盲标清单（含题干，不入库）

用法：uv run python scripts/relevance_spotcheck.py
"""

import csv
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = 20261012
QUOTA = {"ops": 16, "weak": 16, "none": 8}


def main():
    with (ROOT / "data/processed/teleqna_relevance_pilot_ids.csv").open(encoding="utf-8") as f:
        pilot = [r["id"] for r in csv.DictReader(f)]
    with (ROOT / "data/processed/teleqna_items.csv").open(encoding="utf-8") as f:
        keep = {r["id"] for r in csv.DictReader(f) if not r["drop_reason"]}
    with (ROOT / "data/processed/teleqna_relevance.csv").open(encoding="utf-8") as f:
        rel = {r["id"]: int(r["relevance"]) for r in csv.DictReader(f)}
    raw = json.loads((ROOT / "data/raw/TeleQnA/TeleQnA.json").read_text(encoding="utf-8"))

    group = lambda q: "ops" if rel[q] >= 2 else ("weak" if rel[q] == 1 else "none")
    pool = {g: sorted([q for q in pilot if q in keep and q in rel and group(q) == g],
                      key=lambda x: int(x.split()[-1])) for g in QUOTA}
    rng = random.Random(SEED)
    picked = [q for g, n in QUOTA.items() for q in rng.sample(pool[g], n)]
    rng.shuffle(picked)  # 打乱顺序，标注时看不出分层

    with (ROOT / "data/processed/teleqna_relevance_spotcheck_ids.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["no", "id"])
        w.writerows([[i + 1, q] for i, q in enumerate(picked)])
    lines = ["# 相关度人工抽检（40 题，盲标）", ""]
    for i, q in enumerate(picked, 1):
        lines.append(f"{i}. {raw[q]['question']}")
    out = ROOT / "results/audit/relevance/spotcheck_v3.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"抽样 {len(picked)} 题（池：" + "、".join(f"{g} {len(pool[g])}" for g in QUOTA) + f"）→ {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
