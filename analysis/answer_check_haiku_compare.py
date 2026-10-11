"""对照：用 Haiku 子 agent 重跑答案核验流程，与默认模型的结论是否一致。

两轮流程、题目、Qwen 盲答完全相同，只把 Claude 盲答与核查者换成 Haiku。
判定规则与 analysis/answer_check.py 相同。

输入：
  data/processed/teleqna_answer_check_sample.csv
  data/processed/teleqna_answer_check_votes.csv         默认模型
  data/processed/teleqna_answer_check_votes_haiku.csv   Haiku
输出：reports/audit/teleqna_answer_check_haiku.md

用法：uv run python analysis/answer_check_haiku_compare.py
"""

import csv
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from statsmodels.stats.inter_rater import cohens_kappa

ROOT = Path(__file__).resolve().parents[1]
STATUSES = ["screen_pass", "correct", "suspect_wrong", "needs_review"]


def load_votes(path):
    solves, verdicts = {}, defaultdict(list)
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["kind"] == "solve":
                solves[r["id"]] = int(r["choice"])
            else:
                verdicts[r["id"]].append(r["verdict"])
    return solves, verdicts


def status(s, solve, labels):
    gold = int(s["gold"])
    qwen = int(s["qwen_choice"]) if s["qwen_choice"] else None
    flagged = (solve is not None and solve != gold) or (qwen is not None and qwen != gold) \
        or s["source"] == "conflict"
    if not flagged:
        return "screen_pass"
    if len(labels) < 2:
        return "needs_review"   # 核查缺失按待复核处理
    if all(l == "wrong" for l in labels):
        return "suspect_wrong"
    if all(l == "correct" for l in labels):
        return "correct"
    return "needs_review"


def kappa(a, b, cats):
    t = np.zeros((len(cats), len(cats)))
    for x, y in zip(a, b):
        t[cats.index(x), cats.index(y)] += 1
    return cohens_kappa(t).kappa


def main():
    with (ROOT / "data/processed/teleqna_answer_check_sample.csv").open(encoding="utf-8") as f:
        sample = {r["id"]: r for r in csv.DictReader(f) if r["source"] == "random"}
    ds, dv = load_votes(ROOT / "data/processed/teleqna_answer_check_votes.csv")
    hs, hv = load_votes(ROOT / "data/processed/teleqna_answer_check_votes_haiku.csv")
    ids = sorted(sample, key=lambda q: int(q.split()[-1]))
    d = [status(sample[q], ds.get(q), dv.get(q, [])) for q in ids]
    h = [status(sample[q], hs.get(q), hv.get(q, [])) for q in ids]
    prob = lambda s: "problem" if s in ("suspect_wrong", "needs_review") else "ok"
    dp, hp = [prob(x) for x in d], [prob(x) for x in h]
    gold = {q: int(sample[q]["gold"]) for q in ids}
    d_acc = sum(ds.get(q) == gold[q] for q in ids)
    h_acc = sum(hs.get(q) == gold[q] for q in ids)
    both_prob = sum(a == b == "problem" for a, b in zip(dp, hp))
    conf = Counter(zip(d, h))
    n = len(ids)
    lines = [
        "# 答案核验：Haiku 与默认模型对照",
        "",
        "由 `analysis/answer_check_haiku_compare.py` 生成，请勿手改。",
        "",
        f"同一批随机抽样 {n} 题、同一份 Qwen 盲答、同一判定规则，只把 Claude 盲答者与核查者从默认模型换成 Haiku。",
        "",
        "| 指标 | 默认模型 | Haiku |",
        "| --- | --- | --- |",
        f"| 盲答与标准答案一致 | {d_acc}/{n} | {h_acc}/{n} |",
        f"| 进入核查 | {sum(x != 'screen_pass' for x in d)} | {sum(x != 'screen_pass' for x in h)} |",
        f"| 疑似错误 | {d.count('suspect_wrong')} | {h.count('suspect_wrong')} |",
        f"| 待复核 | {d.count('needs_review')} | {h.count('needs_review')} |",
        f"| 问题题合计（疑似错误 + 待复核） | {dp.count('problem')} | {hp.count('problem')} |",
        "",
        f"- 有问题 / 无问题二分类 Cohen's kappa：{kappa(dp, hp, ['ok', 'problem']):.3f}",
        f"- 默认模型判为有问题的 {dp.count('problem')} 题中，Haiku 也判为有问题 {both_prob} 题"
        f"（召回 {both_prob / max(dp.count('problem'), 1):.0%}）",
        f"- Haiku 判为有问题的 {hp.count('problem')} 题中，默认模型也判为有问题 {both_prob} 题"
        f"（精确率 {both_prob / max(hp.count('problem'), 1):.0%}）",
        "",
        "## 状态混淆矩阵（行：默认模型，列：Haiku）",
        "",
        "| | " + " | ".join(STATUSES) + " |",
        "| --- | " + " | ".join("---" for _ in STATUSES) + " |",
        *[f"| {a} | " + " | ".join(str(conf[(a, b)]) for b in STATUSES) + " |" for a in STATUSES],
        "",
    ]
    out = ROOT / "reports/audit/teleqna_answer_check_haiku.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[6:17]))


if __name__ == "__main__":
    main()
