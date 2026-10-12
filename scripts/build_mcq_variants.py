"""生成客观题横评的 EvalScope general_mcq 数据：测试子集 731 题 × 5 个子集。

子集（Spec「客观题评测方法」）：
  orig  原题原序
  rep   原题原序再跑一遍，与 orig 比较得噪声底
  s1–s3 打乱选项顺序；按审计的 shuffle_policy：free 全打乱，pin_last 把“All / None of the above”
        类选项固定在原位、其余打乱，no_shuffle（选项互相引用编号）不打乱
打乱用固定种子（题号 × 子集），可复现；保证 s1–s3 的排列与原序及彼此尽量不同。

输入：data/processed/teleqna_test_subset.csv、data/raw/TeleQnA/TeleQnA.json
输出（含原文，不入库）：
  results/evalscope_data/teleqna_ops/{orig,rep,s1,s2,s3}_val.jsonl   EvalScope 读取（id, question, A–E, answer）
  results/evalscope_data/teleqna_ops/permutations.json              每题每子集：新位置 → 原选项序号（1 起）

用法：uv run python scripts/build_mcq_variants.py
"""

import csv
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from audit_teleqna import POSITION_REF_RE  # noqa: E402

OUT = ROOT / "results/evalscope_data/teleqna_ops"
SUBSETS = ["orig", "rep", "s1", "s2", "s3"]
LETTERS = "ABCDEFGHIJ"


def permute(n, policy, pinned, seed, avoid):
    """返回长度 n 的排列 perm，perm[新位置] = 原位置（0 起）。"""
    ident = list(range(n))
    if policy == "no_shuffle":
        return ident
    free = [i for i in ident if i not in pinned]
    rng = random.Random(seed)
    best = None
    for _ in range(50):  # 尽量避开原序与已用过的排列
        f = free[:]
        rng.shuffle(f)
        it = iter(f)
        perm = [i if i in pinned else next(it) for i in ident]
        if perm not in avoid:
            return perm
        best = perm
    return best


def main():
    raw = json.loads((ROOT / "data/raw/TeleQnA/TeleQnA.json").read_text(encoding="utf-8"))
    with (ROOT / "data/processed/teleqna_test_subset.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    OUT.mkdir(parents=True, exist_ok=True)
    files = {s: (OUT / f"{s}_val.jsonl").open("w", encoding="utf-8") for s in SUBSETS}
    perms = {}
    for r in rows:
        v = raw[r["id"]]
        opts = [v[k] for k in sorted((k for k in v if k.startswith("option ")), key=lambda k: int(k.split()[1]))]
        gold = int(r["gold"]) - 1
        pinned = {i for i, o in enumerate(opts) if POSITION_REF_RE.match(o)} if r["shuffle_policy"] == "pin_last" else set()
        num = int(r["id"].split()[-1])
        used = [list(range(len(opts)))]
        perms[r["id"]] = {}
        for k, s in enumerate(SUBSETS):
            if s in ("orig", "rep"):
                perm = list(range(len(opts)))
            else:
                perm = permute(len(opts), r["shuffle_policy"], pinned, seed=num * 10 + k, avoid=used)
                used.append(perm)
            perms[r["id"]][s] = [p + 1 for p in perm]
            rec = {"id": r["id"], "question": v["question"]}
            rec.update({LETTERS[i]: opts[p] for i, p in enumerate(perm)})
            rec["answer"] = LETTERS[perm.index(gold)]
            files[s].write(json.dumps(rec, ensure_ascii=False) + "\n")
    for f in files.values():
        f.close()
    (OUT / "permutations.json").write_text(json.dumps(perms, indent=0), encoding="utf-8")
    moved = sum(perms[q]["s1"] != perms[q]["orig"] for q in perms)
    print(f"{len(rows)} 题 × {len(SUBSETS)} 个子集 → {OUT.relative_to(ROOT)}；s1 中选项顺序有变化的题 {moved}")


if __name__ == "__main__":
    main()
