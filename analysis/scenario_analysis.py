"""场景题横评分析：7 模型关思考 × 45 题的最终主分（Spec「场景题」；规则见 STATUS 决定日志 Oct 14，`81bcf26`）。

输入：
- results/judge/<run>/final_scores.csv            最终主分（analysis/judge_agreement.py 按仲裁规则生成）
- results/judge/<run>/<主 judge>.scores.csv         要点来源 judge 的分项（诊断题根因 / 处置段得分率、不计否决的分数）
- data/scenarios/judge_split.csv                   题型

口径：
- 均分 + 按题 bootstrap 95% CI（B = 10000，percentile）。
- 21 对模型以题为单元做配对符号翻转置换检验（B = 10000，双侧），Holm 校正（α = 0.05）；
  附每对 80% 功效的最小可检出差距（正态近似，未校正 / Holm 最严档）。不显著 ≠ 无差异。
- 分档：均分最高者与所有和它差异不显著（Holm）的模型为第 1 档，剩下的模型里再取均分最高者及与其不显著的为下一档，依此类推（Oct 16 改为单调：按均分从高往低，遇到第一个与本档最高者显著不同的模型就开新档，均分低的不会进更靠前的档；见 STATUS 第五节）。
- 只作描述：按题型均分、诊断题根因段与处置段得分率（扣分前）、一票否决率（Wilson 区间）。
- 稳健性：Haiku 单独、Sonnet 单独、不计一票否决三种口径下的名次与主口径的 Kendall τ。

用法：uv run python analysis/scenario_analysis.py --run main_off
输出：reports/scenarios/<run>_main.md（脚本生成，请勿手改）
"""
import argparse
import csv
import math
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np
from scipy.stats import kendalltau, norm

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/judge"
SPLIT = ROOT / "data/scenarios/judge_split.csv"
REPORTS = ROOT / "reports/scenarios"
SEED = 20261015
B = 10000
ALPHA = 0.05
TYPE_NAME = {"consulting": "方案咨询", "diagnosis": "故障诊断", "kpi": "KPI 解读"}


def read_csv(path):
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def matrix(rows, models, scns, value):
    """rows -> 模型 × 题 的分数矩阵；value(row) 取值。"""
    idx = {(r["model"], r["scenario_id"]): value(r) for r in rows}
    return np.array([[idx[(m, s)] for s in scns] for m in models])


def holm(ps):
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    adj, run = [0.0] * len(ps), 0.0
    for k, i in enumerate(order):
        run = max(run, min(1.0, (len(ps) - k) * ps[i]))
        adj[i] = run
    return adj


def wilson(k, n, z=1.96):
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return f"{p:.0%}（{k}/{n}，[{max(0, c - h):.0%}, {min(1, c + h):.0%}]）"


def ranks(means, models):
    order = sorted(range(len(models)), key=lambda i: -means[i])
    r = [0] * len(models)
    for k, i in enumerate(order):
        r[i] = k + 1
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="main_off")
    ap.add_argument("--main", default="claude_claude-haiku-5-5_medium", help="要点来源 judge 的日志名")
    args = ap.parse_args()

    fin = read_csv(OUT / args.run / "final_scores.csv")
    pts = read_csv(OUT / args.run / f"{args.main}.scores.csv")
    pts = [r for r in pts if r["repeat"] == "0"]
    for r in pts:
        r["model"] = r["source"]
    typ = {r["scenario_id"]: r["type"] for r in read_csv(SPLIT)}
    models = sorted({r["model"] for r in fin})
    scns = sorted({r["scenario_id"] for r in fin})
    n = len(scns)

    X = matrix(fin, models, scns, lambda r: float(r["total"]))
    means = X.mean(axis=1)
    rng = np.random.default_rng(SEED)
    boot = rng.integers(0, n, size=(B, n))
    bm = X[:, boot].mean(axis=2)  # 模型 × B
    lo, hi = np.percentile(bm, 2.5, axis=1), np.percentile(bm, 97.5, axis=1)

    # ---------- 配对置换检验 ----------
    signs = rng.choice([-1.0, 1.0], size=(B, n))
    z80, z_unc = norm.ppf(0.8), norm.ppf(1 - ALPHA / 2)
    z_holm = norm.ppf(1 - ALPHA / (2 * math.comb(len(models), 2)))
    pairs = []
    for i, j in combinations(range(len(models)), 2):
        d = X[i] - X[j]
        obs = d.mean()
        perm = (signs @ d) / n
        p = (np.sum(np.abs(perm) >= abs(obs) - 1e-12) + 1) / (B + 1)
        sd = d.std(ddof=1)
        pairs.append({"i": i, "j": j, "diff": obs, "p": p,
                      "mde": (z_unc + z80) * sd / math.sqrt(n), "mde_h": (z_holm + z80) * sd / math.sqrt(n)})
    for pr, a in zip(pairs, holm([pr["p"] for pr in pairs])):
        pr["p_holm"] = a
    sig = {(pr["i"], pr["j"]): pr["p_holm"] < ALPHA for pr in pairs}
    sig.update({(j, i): v for (i, j), v in list(sig.items())})

    # ---------- 分档 ----------
    left = sorted(range(len(models)), key=lambda i: -means[i])
    tiers = []
    while left:
        top = left[0]
        # 按均分往下走，遇到第一个与本档最高者显著不同的就开新档（单调：均分低的不会进更靠前的档）
        tier = [top]
        for k in left[1:]:
            if sig[(top, k)]:
                break
            tier.append(k)
        tiers.append(tier)
        left = [k for k in left if k not in tier]
    tier_of = {k: t + 1 for t, tier in enumerate(tiers) for k in tier}

    r_main = ranks(means, models)
    L = [f"# 场景题横评（{args.run}）", "",
         "由 `analysis/scenario_analysis.py` 生成，请勿手改。规则见 STATUS 决定日志（Oct 14，检验前提交）。", "",
         f"{len(models)} 个模型 × {n} 题，关思考。主分 = 要点与扣分项取 Haiku，一票否决须同一高危项 Haiku 与 Sonnet 都触发"
         "（依据分歧仲裁，见 `reports/judge/main_off_agreement.md`）。45 题只支撑分档，不做严格排序。", "",
         "## 均分与分档", "",
         "分档：按均分从高往低，与本档最高者差异不显著（配对置换检验，Holm 校正，α = 0.05）的归入本档，遇到第一个显著不同的模型就开新档，依此类推。", "",
         "| 名次 | 模型 | 均分 | 95% CI（按题 bootstrap） | 档 |", "| --- | --- | --- | --- | --- |"]
    for i in sorted(range(len(models)), key=lambda k: r_main[k]):
        L.append(f"| {r_main[i]} | {models[i]} | {means[i]:.1f} | [{lo[i]:.1f}, {hi[i]:.1f}] | {tier_of[i]} |")
    L += ["", "## 两两配对检验", "",
          "差值 = 前者 − 后者（按题配对）；MDE 为 80% 功效下的最小可检出差距（正态近似）。", "",
          "| 模型对 | 差值 | p | Holm p | MDE（未校正） | MDE（Holm） |", "| --- | --- | --- | --- | --- | --- |"]
    for pr in sorted(pairs, key=lambda x: x["p"]):
        a, b = (pr["i"], pr["j"]) if pr["diff"] >= 0 else (pr["j"], pr["i"])
        L.append(f"| {models[a]} − {models[b]} | {abs(pr['diff']):.1f} | {pr['p']:.4f} | "
                 f"{pr['p_holm']:.4f}{' *' if pr['p_holm'] < ALPHA else ''} | {pr['mde']:.1f} | {pr['mde_h']:.1f} |")
    n_sig = sum(pr["p_holm"] < ALPHA for pr in pairs)
    L += ["", f"Holm 校正后显著 {n_sig}/{len(pairs)} 对（* 标出）。MDE 中位数：未校正 "
          f"{np.median([p['mde'] for p in pairs]):.1f} 分，Holm {np.median([p['mde_h'] for p in pairs]):.1f} 分。", ""]

    # ---------- 描述 ----------
    types = sorted({typ[s] for s in scns})
    L += ["## 按题型（只作描述）", "", "| 模型 | " + " | ".join(f"{TYPE_NAME.get(t, t)}（{sum(typ[s] == t for s in scns)} 题）"
                                                   for t in types) + " |",
          "| --- | " + " | ".join("---" for _ in types) + " |"]
    for i in sorted(range(len(models)), key=lambda k: r_main[k]):
        L.append(f"| {models[i]} | " + " | ".join(
            f"{np.mean([X[i][k] for k, s in enumerate(scns) if typ[s] == t]):.1f}" for t in types) + " |")
    diag = [s for s in scns if typ[s] == "diagnosis"]
    stage = defaultdict(lambda: defaultdict(list))
    for r in pts:
        if r["scenario_id"] in diag:
            for st in ("root_cause", "action"):
                if r.get(f"stage_{st}"):
                    stage[r["model"]][st].append(float(r[f"stage_{st}"]))
    vetoes = defaultdict(int)
    for r in fin:
        vetoes[r["model"]] += int(r["veto"])
    L += ["", "## 诊断题分段与一票否决（只作描述）", "",
          f"根因段 / 处置段得分率为扣分与一票否决之前、按要点权重算的覆盖率（{len(diag)} 道诊断题，要点来自 Haiku）。"
          "一票否决率按全部题目算，只报点估计与区间（Spec）。", "",
          "| 模型 | 根因段 | 处置段 | 一票否决率 |", "| --- | --- | --- | --- |"]
    for i in sorted(range(len(models)), key=lambda k: r_main[k]):
        m = models[i]
        L.append(f"| {m} | {np.mean(stage[m]['root_cause']):.1f} | {np.mean(stage[m]['action']):.1f} | "
                 f"{wilson(vetoes[m], n)} |")

    # ---------- 稳健性 ----------
    alt = {"Haiku 单独": matrix(fin, models, scns, lambda r: float(r["main_total"])),
           "Sonnet 单独": matrix(fin, models, scns, lambda r: float(r["second_total"])),
           "不计一票否决": matrix(pts, models, scns, lambda r: min(100.0, max(0.0, float(r["raw"]) + float(r["deduction"]))))}
    L += ["", "## 稳健性：其他口径下的名次", "", "| 模型 | 主口径 | " + " | ".join(alt) + " |",
          "| --- | --- | " + " | ".join("---" for _ in alt) + " |"]
    alt_r = {k: ranks(v.mean(axis=1), models) for k, v in alt.items()}
    alt_m = {k: v.mean(axis=1) for k, v in alt.items()}
    for i in sorted(range(len(models)), key=lambda k: r_main[k]):
        L.append(f"| {models[i]} | {r_main[i]}（{means[i]:.1f}） | " +
                 " | ".join(f"{alt_r[k][i]}（{alt_m[k][i]:.1f}）" for k in alt) + " |")
    L += ["", "与主口径的 Kendall τ：" + "，".join(f"{k} {kendalltau(r_main, alt_r[k]).statistic:.2f}" for k in alt) + "。", ""]

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"{args.run}_main.md"
    out.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    print(f"→ {out}")


if __name__ == "__main__":
    main()
