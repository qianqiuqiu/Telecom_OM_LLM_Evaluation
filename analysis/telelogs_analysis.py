"""TeleLogs 子集分析：results/telelogs/predictions.csv → reports/telelogs/telelogs_main.md。

口径见 STATUS 决定日志（Oct 15，跑之前定）：
- 各模型正确率 + Wilson 95% 区间；对随机水平 12.5% 做单侧二项检验。抽取失败（含截断）记错并单列。
- 21 对（实际跑了几个模型就是几对）exact McNemar + Holm（α = 0.05），附 80% 功效最小可检出差距（正态近似）。
- 分档：正确率最高者与所有和它差异不显著（Holm）的模型为一档，剩下的依此类推（同场景题横评）（Oct 16 改为单调：按均分从高往低，遇到第一个与本档最高者显著不同的模型就开新档，均分低的不会进更靠前的档；见 STATUS 第五节）。
- 只作描述：按 8 类根因的正确率；与场景题诊断题根因段得分率（Haiku，main_off）的 Spearman（7 个点，不做检验）。
"""
import csv
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np
from scipy.stats import binomtest, norm, spearmanr

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "results/telelogs/predictions.csv"
SAMPLE = ROOT / "data/processed/telelogs_sample.csv"
SCN_SCORES = ROOT / "results/judge/main_off/claude_claude-haiku-5-5_medium.scores.csv"
OUT = ROOT / "reports/telelogs/telelogs_main.md"
ALPHA = 0.05
CHANCE = 1 / 8
CAUSES = {
    "C1": "下倾过大致远端弱覆盖", "C2": "覆盖距离超 1km 越区", "C3": "邻区吞吐更高", "C4": "非共站同频邻区重叠覆盖",
    "C5": "频繁切换", "C6": "PCI 模 30 相同干扰", "C7": "车速超 40km/h", "C8": "平均调度 RB 低于 160"}


def wilson(k, n, z=1.96):
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return c - h, c + h


def holm(ps):
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    adj, run = [0.0] * len(ps), 0.0
    for k, i in enumerate(order):
        run = max(run, min(1.0, (len(ps) - k) * ps[i]))
        adj[i] = run
    return adj


def scenario_root_cause():
    """场景题诊断题根因段得分率（Haiku 判定，一票否决前），按模型平均。"""
    if not SCN_SCORES.exists():
        return {}
    acc = defaultdict(list)
    with SCN_SCORES.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("stage_root_cause"):
                acc[r["source"].split(":")[0]].append(float(r["stage_root_cause"]))
    return {m: sum(v) / len(v) for m, v in acc.items()}


def main():
    rows = list(csv.DictReader(SRC.open(encoding="utf-8")))
    n_sample = sum(1 for _ in SAMPLE.open(encoding="utf-8")) - 1
    by = defaultdict(dict)
    for r in rows:
        by[r["model"]][int(r["idx"])] = r
    models = [m for m in by if len(by[m]) == n_sample]
    partial = [m for m in by if len(by[m]) != n_sample]
    items = sorted(by[models[0]])
    gold = {i: by[models[0]][i]["gold"] for i in items}
    corr = {m: np.array([int(by[m][i]["correct"]) for i in items]) for m in models}
    acc = {m: corr[m].mean() for m in models}
    models.sort(key=lambda m: -acc[m])
    n = len(items)

    L = ["# TeleLogs 子集：5G 路测根因分析（规则判分）", "",
         "由 `analysis/telelogs_analysis.py` 生成，请勿手改。数据 `results/telelogs/predictions.csv`（`scripts/run_telelogs.py`）。"
         "规则见 STATUS 决定日志 Oct 15（跑之前定）。", "",
         f"设定：TeleLogs 测试集 864 题按 8 类根因分层各抽 25 题，共 {n} 题；关思考、温度 0、`max_tokens` 4096、"
         "只发原题文本。判分取最后一个 `\\boxed{}` 里的 C1–C8，抽不到（含截断）记错。随机水平 12.5%。", ""]
    if partial:
        L += [f"**未跑完的模型（不进本报告）**：{', '.join(f'{m}（{len(by[m])}/{n_sample}）' for m in partial)}。", ""]

    L += ["## 正确率", "",
          "| 模型 | 正确 | 正确率 | 95% CI | 对 12.5% 单侧 p | 抽取失败 | 其中截断 | 输出 token 中位数 |",
          "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for m in models:
        k = int(corr[m].sum())
        lo, hi = wilson(k, n)
        p = binomtest(k, n, CHANCE, alternative="greater").pvalue
        fails = [by[m][i] for i in items if by[m][i]["extract_fail"] == "1"]
        trunc = sum(r["finish_reason"] == "length" for r in fails)
        toks = [int(by[m][i]["output_tokens"]) for i in items if by[m][i]["output_tokens"]]
        L.append(f"| {m} | {k}/{n} | {100 * acc[m]:.1f}% | [{100 * lo:.1f}, {100 * hi:.1f}] | {p:.2g} | {len(fails)} | {trunc} "
                 f"| {int(np.median(toks)) if toks else '—'} |")

    # McNemar + Holm
    z, z80 = norm.ppf(1 - ALPHA / 2), norm.ppf(0.8)
    pairs = list(combinations(models, 2))
    res = []
    for a, b in pairs:
        b10 = int(((corr[a] == 1) & (corr[b] == 0)).sum())
        b01 = int(((corr[a] == 0) & (corr[b] == 1)).sum())
        p = binomtest(b10, b10 + b01, 0.5).pvalue if b10 + b01 else 1.0
        nd = b10 + b01
        zh = norm.ppf(1 - ALPHA / (2 * len(pairs)))
        res.append({"a": a, "b": b, "b10": b10, "b01": b01, "p": p,
                    "mde": (z + z80) * np.sqrt(nd) / n if nd else float("nan"),
                    "mde_h": (zh + z80) * np.sqrt(nd) / n if nd else float("nan")})
    for r, ph in zip(res, holm([r["p"] for r in res])):
        r["p_holm"] = ph
    sig = {}
    for r in res:
        sig[(r["a"], r["b"])] = sig[(r["b"], r["a"])] = r["p_holm"] < ALPHA
    tiers, left = [], list(models)
    while left:
        top = left[0]
        tier = [top]  # 单调分档，同 scenario_analysis.py
        for m in left[1:]:
            if sig[(top, m)]:
                break
            tier.append(m)
        tiers.append(tier)
        left = [m for m in left if m not in tier]
    L += ["", "## 分档", "", "按正确率从高往低，与本档最高者差异不显著（exact McNemar，Holm 校正，α = 0.05）的归入本档，遇到第一个显著不同的就开新档，依此类推。"
          "档是「与本档最高者分不开」，不代表档间每对都显著。", ""]
    L += [f"- 第 {t + 1} 档：{'、'.join(tier)}" for t, tier in enumerate(tiers)]
    L += ["", "## 两两配对检验", "", "| 模型 A | 模型 B | A 对 B 错 | A 错 B 对 | p | Holm p | MDE（未校正） | MDE（Holm） |",
          "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in sorted(res, key=lambda r: r["p"]):
        L.append(f"| {r['a']} | {r['b']} | {r['b10']} | {r['b01']} | {r['p']:.4f} | {r['p_holm']:.4f}"
                 f"{' *' if r['p_holm'] < ALPHA else ''} | {100 * r['mde']:.1f}pt | {100 * r['mde_h']:.1f}pt |")
    L += ["", f"Holm 后显著 {sum(r['p_holm'] < ALPHA for r in res)}/{len(res)} 对。MDE 中位数：未校正 "
          f"{100 * np.nanmedian([r['mde'] for r in res]):.1f}pt，Holm {100 * np.nanmedian([r['mde_h'] for r in res]):.1f}pt。", ""]

    # 按类
    L += ["## 按根因类别（只作描述，每类 25 题）", "",
          "| 类别 | " + " | ".join(models) + " | 被预测次数（全部模型） |", "| --- | " + " | ".join("---" for _ in models) + " | --- |"]
    pred_count = defaultdict(int)
    for m in models:
        for i in items:
            pred_count[by[m][i]["pred"] or "抽取失败"] += 1
    for c in sorted(CAUSES):
        ids = [k for k, i in enumerate(items) if gold[i] == c]
        L.append(f"| {c} {CAUSES[c]} | " + " | ".join(f"{100 * corr[m][ids].mean():.0f}%" for m in models)
                 + f" | {pred_count[c]} |")
    L += ["", f"抽取失败合计 {pred_count['抽取失败']} 次。「被预测次数」看各模型是否偏好某一类（均匀时每类约 {len(models) * n // 8} 次）。", ""]

    # 与场景题对照
    rc = scenario_root_cause()
    common = [m for m in models if m in rc]
    if len(common) >= 3:
        rho = spearmanr([acc[m] for m in common], [rc[m] for m in common]).statistic
        L += ["## 与场景题诊断题的对照（只作描述）", "",
              "场景题根因段 = `main_off` 诊断题根因要点得分率（Haiku 判定，一票否决前）。只有 "
              f"{len(common)} 个点，不做检验。", "",
              "| 模型 | TeleLogs 正确率 | 场景题根因段得分率 |", "| --- | --- | --- |"]
        L += [f"| {m} | {100 * acc[m]:.1f}% | {rc[m]:.1f} |" for m in common]
        L += ["", f"Spearman ρ = {rho:.2f}（{len(common)} 个模型）。", ""]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"→ {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
