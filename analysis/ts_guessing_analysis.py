"""TS-Guessing 污染检测分析：results/contamination/ts_guessing.csv → reports/contamination/ts_guessing.md。

口径见 STATUS 决定日志（Oct 15，跑之前定）：
- 每个模型的 EM、短选项（≤ 5 词）EM、长选项（≥ 6 词）EM，Wilson 95% 区间；ROUGE-L F1 均值。
- 主证据是长选项 EM。措辞规则：所有模型长选项 EM < 2% → 「未见逐字背题迹象（以长选项计）」；
  任一模型 ≥ 2% → 「有逐字复原长干扰项的情况」，命中项先人工看是否为通用套话（看完写进 STATUS，不进本脚本）。
- 只作描述：Rel-17 / Rel-18 的长选项 EM（探索性）；命中题与未命中题上的原题正确率（orig 子集，不作因果解读）。
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))
from objective_analysis import load_predictions  # noqa: E402

SRC = ROOT / "results/contamination/ts_guessing.csv"
ITEMS = ROOT / "data/processed/teleqna_items.csv"
OUT = ROOT / "reports/contamination/ts_guessing.md"
THRESHOLD = 0.02


def wilson(k, n, z=1.96):
    if n == 0:
        return float("nan"), float("nan")
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return c - h, c + h


def fmt(k, n):
    if not n:
        return "—"
    lo, hi = wilson(k, n)
    return f"{k}/{n}（{100 * k / n:.1f}%，[{100 * lo:.1f}, {100 * hi:.1f}]）"


def main():
    df = pd.read_csv(SRC)
    rel = pd.read_csv(ITEMS).set_index("id")["release"]
    df["release"] = df["id"].map(rel)
    models = list(dict.fromkeys(df["model"]))
    n_items = df.groupby("model")["id"].nunique()
    if n_items.nunique() != 1:
        raise SystemExit(f"各模型题数不一致：{n_items.to_dict()}")

    lines = ["# 污染检测：TS-Guessing", "",
             "由 `analysis/ts_guessing_analysis.py` 生成，请勿手改。数据 `results/contamination/ts_guessing.csv`"
             "（`scripts/contamination_ts_guessing.py`）。规则见 STATUS 决定日志 Oct 15（跑之前定）。", "",
             f"设定：测试集 {n_items.iloc[0]} 题（4 道编号引用题跳过），每题遮一个错误选项，让模型补出原文"
             "（Deng et al. 2024 的 question-multichoice 设定）；关思考、温度 0。"
             "EM = 规范化后与原文完全相同。短选项 ≤ 5 词，可能靠可猜性补出；长选项 ≥ 6 词，逐字补出更难靠猜，是主证据。", "",
             "## 各模型补出率", "",
             "| 模型 | EM（全部） | 短选项 EM | 长选项 EM | ROUGE-L F1 均值 | 截断 |",
             "| --- | --- | --- | --- | --- | --- |"]
    long_rate = {}
    for m in models:
        d = df[df["model"] == m]
        s, l = d[d["long"] == 0], d[d["long"] == 1]
        long_rate[m] = l["em"].mean()
        lines.append(f"| {m} | {fmt(d['em'].sum(), len(d))} | {fmt(s['em'].sum(), len(s))} | {fmt(l['em'].sum(), len(l))} "
                     f"| {d['rouge_l'].mean():.3f} | {(d['finish_reason'] == 'length').sum()} |")
    n_long = int(df[df["model"] == models[0]]["long"].sum())
    hits = df[(df["long"] == 1) & (df["em"] == 1)]
    by_item = hits.groupby("id")["model"].nunique()
    lines += ["", f"长选项共 {n_long} 题（每个模型相同）。", "",
              "## 结论（按事先定的措辞规则）", ""]
    over = [m for m, r in long_rate.items() if r >= THRESHOLD]
    if over:
        lines.append(f"- **有逐字复原长干扰项的情况**：长选项 EM ≥ 2% 的模型 {len(over)} 个（{', '.join(over)}）。"
                     "命中项是否为通用套话的人工核查结果见 STATUS 第四节。")
    else:
        lines.append("- **未见逐字背题迹象（以长选项计）**：所有模型长选项 EM 都低于 2%。")
    lines += [f"- 长选项命中合计 {len(hits)} 次，涉及 {len(by_item)} 题；"
              f"被 ≥ 2 个模型命中的 {int((by_item >= 2).sum())} 题，≥ 4 个模型命中的 {int((by_item >= 4).sum())} 题。",
              "- 短选项 EM 明显高于长选项，符合「短选项可以靠可猜性补出」的预期，不单独作为背题证据。", ""]

    lines += ["## 按 3GPP 版本（探索性，不做方向性结论，见 D6）", "",
              "| 模型 | Rel-17 长选项 EM | Rel-18 长选项 EM |", "| --- | --- | --- |"]
    for m in models:
        d = df[(df["model"] == m) & (df["long"] == 1)]
        r17, r18 = d[d["release"] == 17], d[d["release"] == 18]
        lines.append(f"| {m} | {fmt(r17['em'].sum(), len(r17))} | {fmt(r18['em'].sum(), len(r18))} |")

    lines += ["", "## 命中题与未命中题的原题正确率（orig 子集，只作描述）", "",
              "命中 = 该模型补出了被遮选项（全部选项长度）。题目难度、选项可猜性都会同时影响两者，不作因果解读。", "",
              "| 模型 | 命中题数 | 命中题正确率 | 未命中题正确率 |", "| --- | --- | --- | --- |"]
    for m in models:
        p = load_predictions(m)["orig"]
        d = df[df["model"] == m]
        hit = d[d["em"] == 1]["id"]
        miss = d[d["em"] == 0]["id"]
        a = lambda ids: sum(p[q]["correct"] for q in ids) / len(ids) if len(ids) else float("nan")
        lines.append(f"| {m} | {len(hit)} | {100 * a(hit):.1f}% | {100 * a(miss):.1f}% |")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"→ {OUT.relative_to(ROOT)}")
    print("长选项命中题（供人工核查）：", ", ".join(f"{q}×{n}" for q, n in by_item.sort_values(ascending=False).items()))


if __name__ == "__main__":
    main()
