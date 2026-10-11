"""校验近重复 LLM 裁决器：与独立标注者多数票的一致性。

输入：
  results/audit/validation/sample.jsonl        抽样对与 LLM 裁决标签
  data/processed/teleqna_pair_validation.csv   独立标注者的逐票标签（pair_id, annotator, relation, answers）
输出：
  reports/audit/teleqna_adjudicator_validation.md

用法：uv run python analysis/pair_adjudicator_agreement.py
"""

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from statsmodels.stats.inter_rater import cohens_kappa, fleiss_kappa

ROOT = Path(__file__).resolve().parents[1]
RELATIONS = ["duplicate", "variant", "related"]
N_BOOT = 2000
SEED = 20261011


def kappa_2x(y1, y2, cats):
    table = np.zeros((len(cats), len(cats)))
    for a, b in zip(y1, y2):
        table[cats.index(a), cats.index(b)] += 1
    return cohens_kappa(table).kappa


def boot_ci(y1, y2, cats):
    rng = np.random.default_rng(SEED)
    y1, y2 = np.array(y1), np.array(y2)
    vals = []
    for _ in range(N_BOOT):
        idx = rng.integers(0, len(y1), len(y1))
        k = kappa_2x(y1[idx], y2[idx], cats)
        if not np.isnan(k):
            vals.append(k)
    return np.percentile(vals, [2.5, 97.5])


def main():
    sample = {json.loads(l)["pair_id"]: json.loads(l)
              for l in (ROOT / "results/audit/validation/sample.jsonl").open(encoding="utf-8")}
    votes = defaultdict(list)
    with (ROOT / "data/processed/teleqna_pair_validation.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            votes[r["pair_id"]].append(r)

    ids = [pid for pid in sample if votes.get(pid)]
    n_ann = Counter(len(votes[pid]) for pid in ids)
    majority, unanimous = {}, 0
    for pid in ids:
        c = Counter(v["relation"] for v in votes[pid]).most_common()
        # 无多数时（三票各不同）按“更保守”的顺序取：variant > related > duplicate，避免误删题
        top = [lab for lab, cnt in c if cnt == c[0][1]]
        majority[pid] = top[0] if len(top) == 1 else next(l for l in ["variant", "related", "duplicate"] if l in top)
        unanimous += len(c) == 1

    llm = [sample[pid]["llm_relation"] for pid in ids]
    maj = [majority[pid] for pid in ids]
    k3 = kappa_2x(llm, maj, RELATIONS)
    ci3 = boot_ci(llm, maj, RELATIONS)
    bin_llm = ["dup" if x == "duplicate" else "not" for x in llm]
    bin_maj = ["dup" if x == "duplicate" else "not" for x in maj]
    k2 = kappa_2x(bin_llm, bin_maj, ["dup", "not"])
    ci2 = boot_ci(bin_llm, bin_maj, ["dup", "not"])

    # 标注者之间的一致性（只用票数齐全的对）
    full = [pid for pid in ids if len(votes[pid]) == max(n_ann)]
    fk_table = np.array([[sum(v["relation"] == c for v in votes[pid]) for c in RELATIONS] for pid in full])
    fk = fleiss_kappa(fk_table) if len(full) else float("nan")

    conf = Counter(zip(llm, maj))
    tp = conf[("duplicate", "duplicate")]
    llm_dup = sum(x == "duplicate" for x in llm)
    maj_dup = sum(x == "duplicate" for x in maj)

    # 答案一致性：双方都判 duplicate 的对
    both_dup = [pid for pid in ids if sample[pid]["llm_relation"] == "duplicate" and majority[pid] == "duplicate"]
    ans_agree = sum(1 for pid in both_dup if sample[pid]["llm_answers"] ==
                    Counter(v["answers"] for v in votes[pid] if v["relation"] == "duplicate").most_common(1)[0][0])

    disagreements = [pid for pid in ids if sample[pid]["llm_relation"] != majority[pid]]

    lines = [
        "# 近重复裁决器校验",
        "",
        "由 `analysis/pair_adjudicator_agreement.py` 生成，请勿手改。",
        "",
        f"抽样 {len(ids)} 对（分层：裁决为重复的对、高相似的变体对、随机变体对、相关对），"
        f"每对由 {'/'.join(map(str, sorted(n_ann)))} 名独立标注者盲标（不看裁决结果），取多数票。",
        "标注者为 Claude 子 agent，不是人工；它们与裁决模型来自不同厂商。",
        "",
        "## 一致性",
        "",
        "| 指标 | 数值 |",
        "| --- | --- |",
        f"| 裁决 vs 多数票，三分类 Cohen's kappa | {k3:.3f}（95% CI {ci3[0]:.3f}–{ci3[1]:.3f}） |",
        f"| 裁决 vs 多数票，重复 / 非重复 Cohen's kappa | {k2:.3f}（95% CI {ci2[0]:.3f}–{ci2[1]:.3f}） |",
        f"| 裁决判重复的精确率（以多数票为准） | {tp}/{llm_dup} = {tp / llm_dup:.1%} |" if llm_dup else "| 精确率 | — |",
        f"| 多数票判重复中被裁决找到的比例 | {tp}/{maj_dup} = {tp / maj_dup:.1%} |" if maj_dup else "| 召回 | — |",
        f"| 标注者之间 Fleiss' kappa（三分类，{len(full)} 对） | {fk:.3f} |",
        f"| 标注者全票一致的对 | {unanimous}/{len(ids)} |",
        f"| 双方都判重复时，答案一致性判断相同 | {ans_agree}/{len(both_dup)} |",
        "",
        "## 混淆矩阵（行：裁决，列：多数票）",
        "",
        "| | " + " | ".join(RELATIONS) + " |",
        "| --- | " + " | ".join("---" for _ in RELATIONS) + " |",
        *[f"| {a} | " + " | ".join(str(conf[(a, b)]) for b in RELATIONS) + " |" for a in RELATIONS],
        "",
        f"## 分歧样本（{len(disagreements)} 对，交人工复核）",
        "",
        "| pair_id | 题对 | 题干 Jaccard | 裁决 | 多数票 | 票型 |",
        "| --- | --- | --- | --- | --- | --- |",
        *[f"| {pid} | {sample[pid]['a']} / {sample[pid]['b']} | {sample[pid]['stem_jaccard']:.2f} | "
          f"{sample[pid]['llm_relation']} | {majority[pid]} | "
          f"{', '.join(v['relation'] for v in votes[pid])} |" for pid in disagreements],
        "",
    ]
    out = ROOT / "reports/audit/teleqna_adjudicator_validation.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"写出 {out.relative_to(ROOT)}：kappa3={k3:.3f} kappa2={k2:.3f} 分歧 {len(disagreements)}")


if __name__ == "__main__":
    main()
