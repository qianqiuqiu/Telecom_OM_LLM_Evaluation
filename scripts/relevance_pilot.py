"""运维相关度试标：从审计后保留的题中抽 200 题，生成不带标签的标注批次。

同一批题由默认模型与 Haiku 子 agent 分别标注，对照一致性后决定全量标注用哪个模型；
本人再对这 200 题人工抽检，报告与模型标注的一致率（Spec「公开集的审计与重构」第 5 项）。

输出：
  data/processed/teleqna_relevance_pilot_ids.csv   试标题目 ID（可入库）
  results/audit/relevance/pilot_batches/*.jsonl    标注批次，含原文（不入库）

用法：uv run python scripts/relevance_pilot.py [--all]
  --all：为审计后保留的全部题生成全量标注批次（results/audit/relevance/full_batches）
"""

import argparse
import csv
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from audit_teleqna import load_items  # noqa: E402

SEED = 20261013
N = 200
BATCH = 25
OUT = ROOT / "results/audit/relevance/pilot_batches"
IDS = ROOT / "data/processed/teleqna_relevance_pilot_ids.csv"


def write_batches(out, ids, by_id):
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.jsonl"):
        old.unlink()
    for b in range(0, len(ids), BATCH):
        with (out / f"batch_{b // BATCH:03d}.jsonl").open("w", encoding="utf-8") as f:
            for qid in ids[b:b + BATCH]:
                it = by_id[qid]
                f.write(json.dumps({"id": qid, "question": it["question"], "options": it["options"],
                                    "correct_answer": it["answer_text"]}, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    with (ROOT / "data/processed/teleqna_items.csv").open(encoding="utf-8") as f:
        keep = {r["id"] for r in csv.DictReader(f) if not r["drop_reason"]}
    items = [it for it in load_items() if it["id"] in keep]
    if args.all:
        ids = [it["id"] for it in sorted(items, key=lambda x: x["num"])]
        out = ROOT / "results/audit/relevance/full_batches"
        write_batches(out, ids, {it["id"]: it for it in items})
        print(f"全量 {len(ids)} 题，{(len(ids) + BATCH - 1) // BATCH} 个批次 → {out.relative_to(ROOT)}")
        return
    if IDS.exists():  # 抽样冻结，避免题集标记变化后重抽
        with IDS.open(encoding="utf-8") as f:
            ids = [r["id"] for r in csv.DictReader(f)]
    else:
        rng = random.Random(SEED)
        ids = [it["id"] for it in rng.sample(sorted(items, key=lambda x: x["num"]), N)]
        with IDS.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["id"])
            w.writerows([[i] for i in ids])
    write_batches(OUT, ids, {it["id"]: it for it in items})
    print(f"试标 {len(ids)} 题，{(len(ids) + BATCH - 1) // BATCH} 个批次 → {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
