"""跨厂商 judge：自家偏好检验与对照仲裁样本（Spec「Judge 元评测」偏差实验 2；规则见 STATUS 决定日志 Oct 14，`81bcf26`）。

- 自家偏好：e = 跨厂商 judge 总分 − 最终主分；每题取与 judge 同厂商的被测模型的 e 均值减其余模型的 e 均值，
  得每题一个值，单侧符号翻转置换检验（H1：> 0，B = 10000，种子 20261015），p < 0.05 判为有自家偏好。
  另报不计一票否决的同一检验（跨厂商 judge 与主分的要点来源 judge 各取「要点 + 扣分」）与各模型 e 均值。
  减去主分抵消了 judge 整体偏松 / 偏严，只有专门对自家模型多给的分才会显著。
- 对照仲裁样本（事后描述，规则里没有，不据此改任何结论）：在用户仲裁过的分歧项上，跨厂商 judge 的判定
  与仲裁认定正确的一方是否相同。

跨厂商 judge 的结果不进主分。

用法：uv run python analysis/judge_cross_vendor.py --run main_off --answers results/answers/main_off.jsonl
输出：reports/judge/<run>_cross_vendor.md（脚本生成，请勿手改）
"""
import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path

import numpy as np

from judge_agreement import ARB, LEVELS, REPORTS, ROOT, SCENARIOS, SEED, SHORT, flags, load_judge, wilson

OUT = ROOT / "results/judge"
B = 10000


def sign_flip(v, rng):
    """单侧（H1：均值 > 0）符号翻转置换检验。"""
    v = np.asarray(v)
    perm = (rng.choice([-1.0, 1.0], size=(B, len(v))) @ v) / len(v)
    return v.mean(), (np.sum(perm >= v.mean() - 1e-12) + 1) / (B + 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="main_off")
    ap.add_argument("--answers", required=True, type=Path)
    ap.add_argument("--judge", default="bailian_deepseek-v4.1-flash", help="跨厂商 judge 的日志名")
    ap.add_argument("--vendor", default="deepseek", help="judge 所属厂商：被测模型名以此开头的算自家")
    ap.add_argument("--points", default="claude_claude-haiku-5-5_medium", help="主分的要点来源 judge")
    args = ap.parse_args()

    scns = {q["id"]: q for q in json.loads(SCENARIOS.read_text(encoding="utf-8"))}
    answers = [json.loads(line) for line in args.answers.read_text(encoding="utf-8").splitlines() if line.strip()]
    ans = {a["answer_id"]: a for a in answers}
    jx, _, px, X = load_judge(OUT / args.run / f"{args.judge}.jsonl", answers, scns)
    _, _, _, P = load_judge(OUT / args.run / f"{args.points}.jsonl", answers, scns)
    with (OUT / args.run / "final_scores.csv").open(encoding="utf-8") as f:
        fin = {r["answer_id"]: float(r["total"]) for r in csv.DictReader(f)}
    ids = sorted(set(X) & set(fin))
    models = sorted({ans[a]["source"] for a in ids})
    own = [m for m in models if m.startswith(args.vendor)]

    def nov(rec):
        s = rec["score"]
        return min(100.0, max(0.0, s["raw"] + s["deduction"]))

    e = {a: X[a]["score"]["total"] - fin[a] for a in ids}
    e_nov = {a: nov(X[a]) - nov(P[a]) for a in ids}
    rng = np.random.default_rng(SEED)
    res = {}
    for name, ev in (("总分（含一票否决）", e), ("不计一票否决", e_nov)):
        per = defaultdict(lambda: {"own": [], "other": []})
        for a in ids:
            per[ans[a]["scenario_id"]]["own" if ans[a]["source"] in own else "other"].append(ev[a])
        v = [statistics.mean(x["own"]) - statistics.mean(x["other"]) for x in per.values() if x["own"] and x["other"]]
        res[name] = (*sign_flip(v, rng), len(v))
    primary = res["总分（含一票否决）"]

    L = [f"# 跨厂商 judge：自家偏好与仲裁对照（{args.run}）", "",
         "由 `analysis/judge_cross_vendor.py` 生成，请勿手改。规则见 STATUS 决定日志（Oct 14，检验前提交）。", "",
         f"- 跨厂商 judge：{jx}（提示词 {px}），判成 {len(ids)} 份；自家模型：{'、'.join(own)}；其余 {len(models) - len(own)} 个。",
         "- e = 跨厂商 judge 总分 − 最终主分。不计一票否决时，两边都取「要点 + 扣分」（主分一侧的要点来自 "
         f"{args.points}）。", "",
         "## 自家偏好检验", "",
         "每题：自家模型 e 均值 − 其余模型 e 均值；单侧符号翻转置换检验（H1：> 0）。", "",
         "| 口径 | 题数 | 均值（分） | 单侧 p |", "| --- | --- | --- | --- |"]
    L += [f"| {k} | {n} | {m:+.1f} | {p:.4f} |" for k, (m, p, n) in res.items()]
    L += ["", "结论（主口径为含一票否决的总分）：" +
          ("**检出自家偏好**（p < 0.05）。" if primary[1] < 0.05 else "未检出自家偏好（p ≥ 0.05）。不显著 ≠ 没有偏好，只是现有样本分辨不出。"), "",
          "| 被测模型 | 自家 | e 均值（含否决） | e 均值（不计否决） |", "| --- | --- | --- | --- |"]
    for m in models:
        L.append(f"| {m} | {'是' if m in own else ''} | {statistics.mean(e[a] for a in ids if ans[a]['source'] == m):+.1f} | "
                 f"{statistics.mean(e_nov[a] for a in ids if ans[a]['source'] == m):+.1f} |")

    # ---------- 仲裁样本对照（事后描述） ----------
    sheet, key_path = ARB / f"{args.run}.csv", ARB / f"{args.run}_key.csv"
    if sheet.exists() and key_path.exists():
        with sheet.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        with key_path.open(encoding="utf-8") as f:
            key = {r["item"]: r for r in csv.DictReader(f)}
        hit = defaultdict(lambda: [0, 0])
        for r in rows:
            k, h = key[r["item"]], r["human"].strip()
            if h not in ("A", "B") or k["answer_id"] not in X:
                continue
            truth = r[h]
            pt = r["point"]
            rec = X[k["answer_id"]]
            if pt.startswith("H"):
                mine = SHORT[flags(rec, "high_risk")[int(pt[1:])]["triggered"]]
                cat = "高危项"
            else:
                mine = SHORT[next(p["verdict"] for p in rec["parsed"]["points"] if p["id"] == pt)]
                cat = "要点"
            assert mine in SHORT.values() and (truth in SHORT.values() or truth in LEVELS)
            for c in (cat, "合计"):
                hit[c][0] += mine == truth
                hit[c][1] += 1
        L += ["", "## 仲裁样本上的对照（事后描述，不据此改结论）", "",
              "在用户仲裁过的两档 Claude 分歧项上，跨厂商 judge 的判定与仲裁认定正确的一方相同的比例。"
              "这些项是 Claude 两档判法不一的难项，不代表跨厂商 judge 的整体准确率。", ""]
        L += [f"- {c}：{wilson(*hit[c])}" for c in ("高危项", "要点", "合计") if hit[c][1]]
    L.append("")

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"{args.run}_cross_vendor.md"
    out.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    print(f"→ {out}")


if __name__ == "__main__":
    main()
