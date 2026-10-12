"""生成客观题测试子集清单：审计后保留且运维相关度 ≥ 2 的题（Oct 12 决定，见 Spec v2.2）。

输入：
  data/processed/teleqna_items.csv                     审计标记（drop_reason 为空即保留；gold_fixed 为修正后答案，1 起）
  data/processed/teleqna_relevance.csv                 相关度与能力维度
  data/processed/teleqna_answer_check_result.csv       300 题抽样核验结果
  data/processed/teleqna_answer_check_full_result.csv  全量核验结果（analysis/answer_check_full.py 生成）
输出：
  data/processed/teleqna_test_subset.csv   id、dimension、relevance、gold（1 起，已含修正）、shuffle_policy、answer_check
  并在终端打印题数、各维度题数与覆盖检查（子集内题须已通过答案核验或修正过答案；
  没有相关度标注的保留题——去重簇改选的代表题——不进子集）

先运行 analysis/answer_check_full.py 与 scripts/audit_teleqna.py。
用法：uv run python scripts/build_test_subset.py
"""

import csv
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / "data/processed"
DIMS = ["RAN", "CORE", "TRANSPORT", "OAM", "SERVICE", "SECURITY", "OTHER"]


def read(name):
    with (P / name).open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    items = {r["id"]: r for r in read("teleqna_items.csv")}
    rel = {r["id"]: r for r in read("teleqna_relevance.csv")}
    sample = {r["id"]: r["status"] for r in read("teleqna_answer_check_result.csv")}
    full = {r["id"]: r["status"] for r in read("teleqna_answer_check_full_result.csv")}

    kept = [i for i, r in items.items() if not r["drop_reason"]]
    no_label = [i for i in kept if i not in rel]
    rows, problems = [], []
    for qid in sorted(kept, key=lambda x: int(x.split()[-1])):
        if qid not in rel or int(rel[qid]["relevance"]) < 2:
            continue
        it = items[qid]
        check = ("sample:" + sample[qid]) if qid in sample else ("full:" + full.get(qid, "missing"))
        if not it["gold_fixed"] and check.split(":")[1] not in ("correct", "screen_pass", "pass", "pass_screen",
                                                                 "pass_review", "pass_vote"):
            problems.append(f"{qid} 答案核验状态 {check}")
        rows.append({"id": qid, "dimension": rel[qid]["dimension"], "relevance": rel[qid]["relevance"],
                     "gold": it["gold_fixed"] or int(it["answer_idx"]) + 1,
                     "gold_fixed": bool(it["gold_fixed"]), "shuffle_policy": it["shuffle_policy"],
                     "answer_check": check})

    out = P / "teleqna_test_subset.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    dim = Counter(r["dimension"] for r in rows)
    print(f"测试子集 {len(rows)} 题 → {out.relative_to(ROOT)}")
    print("各维度：" + "、".join(f"{d} {dim[d]}" for d in DIMS if dim[d]))
    print("相关度：" + "、".join(f"{k} 级 {v}" for k, v in sorted(Counter(r["relevance"] for r in rows).items())))
    print(f"修正过答案 {sum(r['gold_fixed'] for r in rows)} 题；打乱策略："
          + "、".join(f"{k} {v}" for k, v in Counter(r["shuffle_policy"] for r in rows).most_common()))
    if no_label:
        # 去重簇原代表题因答案问题被剔除后，audit_teleqna.py 会改选同簇另一题；这些题未做相关度标注与答案核验，
        # 且近重复题多半有同样的问题，不进测试子集（Oct 12）
        print(f"未进子集：{len(no_label)} 道改选的去重代表题，无相关度标注与答案核验：{no_label}")
    for p in problems:
        print("  覆盖问题：", p)
    if problems:
        sys.exit(1)


if __name__ == "__main__":
    main()
