"""运维相关度试标：默认模型与 Haiku 的一致性，以及（有人工标注时）与人工的一致性。

输入：
  data/processed/teleqna_relevance_pilot_labels.csv   每题每个标注者的 relevance / dimension
     labeler 取值：default、haiku、human（人工抽检，可选）
输出：reports/audit/teleqna_relevance_pilot.md

用法：uv run python analysis/relevance_pilot_compare.py
"""

import csv
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from statsmodels.stats.inter_rater import cohens_kappa

ROOT = Path(__file__).resolve().parents[1]
DIMS = ["RAN", "CORE", "TRANSPORT", "OAM", "SERVICE", "SECURITY", "OTHER"]
KEEP_MIN = 2   # 相关度 ≥ 2 进入客观题主体（v1 建议值）


def table(a, b, cats):
    t = np.zeros((len(cats), len(cats)))
    for x, y in zip(a, b):
        t[cats.index(x), cats.index(y)] += 1
    return t


def pair_rows(lab, x, y, ids):
    rx = [lab[q][x]["relevance"] for q in ids]
    ry = [lab[q][y]["relevance"] for q in ids]
    kx = ["keep" if r >= KEEP_MIN else "drop" for r in rx]
    ky = ["keep" if r >= KEEP_MIN else "drop" for r in ry]
    dx = [lab[q][x]["dimension"] for q in ids]
    dy = [lab[q][y]["dimension"] for q in ids]
    w = cohens_kappa(table(rx, ry, [0, 1, 2, 3]), wt="quadratic").kappa
    return [
        f"| {x} vs {y} | {len(ids)} | {sum(a == b for a, b in zip(rx, ry)) / len(ids):.0%} | {w:.3f} | "
        f"{cohens_kappa(table(kx, ky, ['drop', 'keep'])).kappa:.3f} | "
        f"{sum(a == b for a, b in zip(dx, dy)) / len(ids):.0%} | {cohens_kappa(table(dx, dy, DIMS)).kappa:.3f} |"
    ]


def main():
    lab = defaultdict(dict)
    with (ROOT / "data/processed/teleqna_relevance_pilot_labels.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            lab[r["id"]][r["labeler"]] = {"relevance": int(r["relevance"]), "dimension": r["dimension"]}
    labelers = sorted({l for v in lab.values() for l in v})
    pairs = [(a, b) for i, a in enumerate(labelers) for b in labelers[i + 1:]]

    lines = [
        "# 运维相关度试标",
        "",
        "由 `analysis/relevance_pilot_compare.py` 生成，请勿手改。规范见 `docs/rubrics/ops_relevance_v1.md`。",
        "",
        "## 一致性",
        "",
        "| 对照 | 题数 | 相关度完全一致 | 相关度加权 kappa | 入选（≥2）kappa | 维度一致 | 维度 kappa |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for a, b in pairs:
        ids = [q for q in lab if a in lab[q] and b in lab[q]]
        if ids:
            lines += pair_rows(lab, a, b, ids)
    lines += ["", "## 分布", "", "| 标注者 | 相关度 0 / 1 / 2 / 3 | 入选比例 | 维度分布 |", "| --- | --- | --- | --- |"]
    for l in labelers:
        rs = [v[l]["relevance"] for v in lab.values() if l in v]
        ds = Counter(v[l]["dimension"] for v in lab.values() if l in v)
        lines.append(f"| {l} | {' / '.join(str(rs.count(k)) for k in range(4))} | "
                     f"{sum(r >= KEEP_MIN for r in rs) / len(rs):.0%} | "
                     + "，".join(f"{d} {ds[d]}" for d in DIMS if ds[d]) + " |")
    lines.append("")
    out = ROOT / "reports/audit/teleqna_relevance_pilot.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[4:]))


if __name__ == "__main__":
    main()
