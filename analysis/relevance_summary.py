"""运维相关度与能力维度：全量标注汇总。

输入：
  data/processed/teleqna_relevance.csv   全量标注（Haiku；v2，引用规则 2 的题以 v3 重标）
  data/processed/teleqna_items.csv       审计标记（只统计最终保留的题）
输出：reports/audit/teleqna_relevance.md

用法：uv run python analysis/relevance_summary.py
"""

import csv
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIMS = ["RAN", "CORE", "TRANSPORT", "OAM", "SERVICE", "SECURITY", "OTHER"]


def spotcheck_line():
    """本人盲标 40 题（scripts/relevance_spotcheck.py 抽样）：Y/N 与当前标签是否 ≥ 2 的一致性。"""
    path = ROOT / "data/processed/teleqna_relevance_spotcheck_human.csv"
    if not path.exists():
        return "- 人工抽检：待本人完成。"
    with (ROOT / "data/processed/teleqna_relevance.csv").open(encoding="utf-8") as f:
        rel = {r["id"]: int(r["relevance"]) for r in csv.DictReader(f)}
    with path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    used = [r for r in rows if r["human"] in ("Y", "N")]
    h = [r["human"] == "Y" for r in used]
    m = [rel[r["id"]] >= 2 for r in used]
    n = len(used)
    po = sum(a == b for a, b in zip(h, m)) / n
    pa, pb = sum(h) / n, sum(m) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    yn = sum(a and not b for a, b in zip(h, m))
    ny = sum(b and not a for a, b in zip(h, m))
    return (f"- 人工抽检（Oct 12）：本人盲标 40 题（标签 ≥2 / =1 / =0 分层 16 / 16 / 8），只判“运维日常是否会用到”。"
            f"有效 {n} 题（其余 {len(rows) - n} 题标“不确定”），与当前标签（≥2 视为会用到）一致率 {po:.0%}、kappa {(po - pe) / (1 - pe):.2f}；"
            f"本人判会用到而标签 ≤1 的 {yn} 题，反之 {ny} 题。一致性很低：单人、非领域专家、样本小，"
            "且本人的尺度更接近“运维人员实际掌握”，与规范的“工作中会用到”不同。"
            "结论：运维相关度筛选未获人工验证，测试集的“运维相关”属性只能作为模型判定报告。")


def main():
    with (ROOT / "data/processed/teleqna_items.csv").open(encoding="utf-8") as f:
        keep = {r["id"] for r in csv.DictReader(f) if not r["drop_reason"]}
    with (ROOT / "data/processed/teleqna_relevance.csv").open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["id"] in keep]
    n = len(rows)
    rel = Counter(int(r["relevance"]) for r in rows)
    rubric = Counter(r["rubric"] for r in rows)
    ops = [r for r in rows if int(r["relevance"]) >= 2]
    lines = [
        "# 运维相关度与能力维度",
        "",
        "由 `analysis/relevance_summary.py` 生成，请勿手改。规范见 `docs/rubrics/`。",
        "",
        f"范围：清洗后最终保留的 {n} 题。标注者 Haiku；"
        + "，".join(f"{k} 规范 {v} 题" for k, v in sorted(rubric.items()))
        + "（v2 中引用规则 2 的题在发现误用后以 v3 重标）。",
        "",
        "## 相关度分布",
        "",
        "| 等级 | 题数 |",
        "| --- | --- |",
        *[f"| {k} | {rel[k]}（{rel[k] / n:.1%}） |" for k in (3, 2, 1, 0)],
        "",
        f"运维相关子集（2–3 级）：**{len(ops)} 题（{len(ops) / n:.1%}）**，用于单独排序；全部 {n} 题用于主排序。",
        "",
        "## 能力维度 × 相关度",
        "",
        "| 维度 | 全部 | 运维相关（≥2） | 相关占比 |",
        "| --- | --- | --- | --- |",
    ]
    for d in DIMS:
        a = sum(r["dimension"] == d for r in rows)
        b = sum(r["dimension"] == d for r in ops)
        lines.append(f"| {d} | {a} | {b} | {b / a:.0%} |" if a else f"| {d} | 0 | 0 | — |")
    lines += [
        "",
        "## 标注质量",
        "",
        "- v1 → v2：试标 200 题，默认模型与 Haiku 在“是否运维相关（≥2）”上的 kappa 0.60 → 0.73（见 `teleqna_relevance_pilot.md`）。",
        "- v2 → v3：全量标注后抽查 40 条引用规则 2（新 / 小众特性封顶）的标注，35% 实为主流特性（标注者把 Release 标签当成特性引入版本）；"
        "v3 明确标签含义后重标这 936 题，同一抽样中的误用降至约 5%。",
        spotcheck_line(),
        "",
    ]
    out = ROOT / "reports/audit/teleqna_relevance.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[6:]))


if __name__ == "__main__":
    main()
