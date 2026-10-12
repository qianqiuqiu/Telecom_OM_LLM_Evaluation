"""全量答案核验（两阶段）的输入准备。

范围：审计后保留、且未在 300 题抽样中核验过的全部题。
流程（由 Claude workflow 执行，见输出的 workflow 脚本）：
  1. Haiku 盲答（不看标准答案）
  2. 盲答与标准答案不一致的题 → 两名 Haiku 核查者独立核查（可查原文）
  3. Haiku 判为有问题（非两人都判 correct）的题 → 两名默认模型核查者复查定论

输出：
  results/audit/answer_check_full/blind_batches/batch_XXX.jsonl   盲答批次，不含标准答案（不入库）
  results/audit/answer_check_full/items.json                      题目原文与标准答案（不入库，核查者读取）
  results/audit/answer_check_full/workflow.js                     内嵌标准答案映射的 workflow 脚本（不入库）

用法：uv run python scripts/answer_check_full.py
"""

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from audit_teleqna import load_items  # noqa: E402

BATCH = 20
OUT = ROOT / "results/audit/answer_check_full"
TEMPLATE = ROOT / "scripts/workflows/answer_check_full.template.js"


def main():
    with (ROOT / "data/processed/teleqna_items.csv").open(encoding="utf-8") as f:
        flags = {r["id"]: r for r in csv.DictReader(f)}
    with (ROOT / "data/processed/teleqna_answer_check_sample.csv").open(encoding="utf-8") as f:
        checked = {r["id"] for r in csv.DictReader(f)}
    items = [it for it in load_items() if not flags[it["id"]]["drop_reason"] and it["id"] not in checked]
    items.sort(key=lambda x: x["num"])
    for it in items:  # 已修正的答案以修正后为准
        if flags[it["id"]]["gold_fixed"]:
            it["answer_idx"] = int(flags[it["id"]]["gold_fixed"]) - 1

    blind = OUT / "blind_batches"
    blind.mkdir(parents=True, exist_ok=True)
    for old in blind.glob("*.jsonl"):
        old.unlink()
    n_batches = (len(items) + BATCH - 1) // BATCH
    for b in range(n_batches):
        with (blind / f"batch_{b:03d}.jsonl").open("w", encoding="utf-8") as f:
            for it in items[b * BATCH:(b + 1) * BATCH]:
                f.write(json.dumps({"id": it["id"], "question": it["question"],
                                    "options": {str(i + 1): o for i, o in enumerate(it["options"])}},
                                   ensure_ascii=False) + "\n")
    (OUT / "items.json").write_text(json.dumps(
        [{"id": it["id"], "question": it["question"], "options": it["options"], "gold": it["answer_idx"] + 1}
         for it in items], ensure_ascii=False, indent=1), encoding="utf-8")

    gold = {it["id"].split()[-1]: it["answer_idx"] + 1 for it in items}
    js = TEMPLATE.read_text(encoding="utf-8")
    js = js.replace("__GOLD__", json.dumps(gold, separators=(",", ":"))).replace("__N_BATCHES__", str(n_batches))
    (OUT / "workflow.js").write_text(js, encoding="utf-8")
    print(f"待核验 {len(items)} 题，{n_batches} 个盲答批次 → {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
