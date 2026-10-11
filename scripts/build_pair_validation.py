"""从 LLM 裁决结果中分层抽样，生成裁决器校验用的盲标批次。

抽样（固定随机种子）：
  - 裁决为 duplicate 的对：全部纳入（数量多于 DUP_CAP 时随机抽 DUP_CAP）
  - 裁决为 variant 的对：优先抽题干 Jaccard ≥ 0.7 的高相似对（最容易误判），再补随机
  - 裁决为 related 的对：随机抽
批次文件不含裁决标签，供独立标注者盲标。

输出：results/audit/validation/sample.jsonl、batch_XX.jsonl（含原文，不入库）
用法：uv run python scripts/build_pair_validation.py
"""

import csv
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from audit_teleqna import jaccard, load_items, shingles  # noqa: E402

SEED = 20261011
DUP_CAP = 80
N_VARIANT_HIGH = 40
N_VARIANT_RANDOM = 20
N_RELATED = 20
BATCH_SIZE = 20
OUT = ROOT / "results/audit/validation"


def main():
    rng = random.Random(SEED)
    by_id = {it["id"]: it for it in load_items()}
    with (ROOT / "data/processed/teleqna_pair_labels.csv").open(encoding="utf-8") as f:
        labels = [r for r in csv.DictReader(f) if r["relation"] != "FAILED"]
    for r in labels:
        r["stem_jaccard"] = jaccard(shingles(by_id[r["a"]]["stem"]), shingles(by_id[r["b"]]["stem"]))

    dup = [r for r in labels if r["relation"] == "duplicate"]
    var = [r for r in labels if r["relation"] == "variant"]
    rel = [r for r in labels if r["relation"] == "related"]
    var_high = [r for r in var if r["stem_jaccard"] >= 0.7]

    sample = rng.sample(dup, min(DUP_CAP, len(dup)))
    vh = rng.sample(var_high, min(N_VARIANT_HIGH, len(var_high)))
    rest = [r for r in var if r not in vh]
    sample += vh + rng.sample(rest, min(N_VARIANT_RANDOM, len(rest)))
    sample += rng.sample(rel, min(N_RELATED, len(rel)))
    rng.shuffle(sample)  # 打乱，避免批次内按标签聚集

    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "sample.jsonl").open("w", encoding="utf-8") as f:
        for k, r in enumerate(sample):
            f.write(json.dumps({"pair_id": f"P{k:03d}", "a": r["a"], "b": r["b"],
                                "llm_relation": r["relation"], "llm_answers": r["answers"],
                                "stem_jaccard": round(r["stem_jaccard"], 4)}, ensure_ascii=False) + "\n")

    for old in OUT.glob("batch_*.jsonl"):
        old.unlink()
    for bi in range(0, len(sample), BATCH_SIZE):
        with (OUT / f"batch_{bi // BATCH_SIZE:02d}.jsonl").open("w", encoding="utf-8") as f:
            for k, r in enumerate(sample[bi:bi + BATCH_SIZE], start=bi):
                row = {"pair_id": f"P{k:03d}"}
                for tag in ("a", "b"):
                    it = by_id[r[tag]]
                    row[f"question_{tag}"] = it["question"]
                    row[f"options_{tag}"] = it["options"]
                    row[f"correct_answer_{tag}"] = it["answer_text"]
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"抽样 {len(sample)} 对（duplicate {min(DUP_CAP, len(dup))}/{len(dup)}，"
          f"variant 高相似 {len(vh)} + 随机 {min(N_VARIANT_RANDOM, len(rest))}，related {min(N_RELATED, len(rel))}），"
          f"{(len(sample) + BATCH_SIZE - 1) // BATCH_SIZE} 个批次 → {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
