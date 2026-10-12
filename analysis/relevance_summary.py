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
        "- 人工抽检：待本人对试标 200 题完成抽检后补充一致率。",
        "",
    ]
    out = ROOT / "reports/audit/teleqna_relevance.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[6:]))


if __name__ == "__main__":
    main()
