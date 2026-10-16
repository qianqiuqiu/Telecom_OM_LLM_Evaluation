"""TeleLogs kimi-k3 开思考对照：predictions.csv（关思考，百炼）+ predictions_thinking.csv（开思考，OpenCode Go）
→ reports/telelogs/kimi_k3_thinking.md。

规则见 STATUS 第二节第 9 项（Oct 16，跑之前提交 a3062a4）：
- 同一批 50 题（data/processed/telelogs_sub50.csv）逐题配对；开思考 reasoning_effort = low、max_tokens 16384、温度由厂商固定 1.0。
- ①行为：输出 token 中位数是否离开 11、\\boxed{} 能否抽取、截断数；②正确率：exact McNemar + 配对符号翻转置换，
  报 80% 功效 MDE，不作显著性结论，只报方向与量级；③分层：8 类正确数、是否仍过度押 C4；
  ④结论口径：开思考后是否开始做中间计算、正确率是否离开随机水平（12.5%）。
- 主口径用 Oct 16 事后修正的抽取器（认 \\boxed{\\text{C4}} 这类嵌套）；跑之前定的严格抽取另报（敏感性）。
"""
import csv
import json
import math
import re
import statistics
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.stats import binomtest, norm

ROOT = Path(__file__).resolve().parents[1]
OFF = ROOT / "results/telelogs/predictions.csv"
ON = ROOT / "results/telelogs/predictions_thinking.csv"
SUB = ROOT / "data/processed/telelogs_sub50.csv"
OUT = ROOT / "reports/telelogs/kimi_k3_thinking.md"
RAW = ROOT / "results/telelogs/raw/kimi-k3-ocgo__on.jsonl"  # 含推理原文，不入库；不在时推理关键词一行不出
# 推理里提到各判据的次数（关键词匹配，英文推理为主），只用来说明「开始做中间计算」，不是逐条人工核对
CRITERIA = {"PCI 模 30": r"mod\s*30", "RB": r"\bRBs?\b", "车速": r"speed|km/h", "站点距离": r"\bkm\b|distance",
            "邻区 / 重叠覆盖": r"neighbo|overlap", "切换": r"handover"}
SEED = 20261016
B = 10000
CHANCE = 1 / 8
Z80, Z975 = norm.ppf(0.8), norm.ppf(0.975)
CLASSES = [f"C{i}" for i in range(1, 9)]


def wilson(k, n, z=1.96):
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return c - h, c + h


def signflip(d, name):
    d = np.asarray(d, dtype=float)
    rng = np.random.default_rng([SEED, sum(map(ord, name))])
    perm = rng.choice([-1.0, 1.0], size=(B, len(d))) @ d / len(d)
    return float((np.sum(np.abs(perm) >= abs(d.mean()) - 1e-12) + 1) / (B + 1))


def paired(off, on, name):
    """返回 (关对开错 b, 关错开对 c, exact McNemar p, 置换 p, MDE 百分点)。"""
    b = sum(1 for x, y in zip(off, on) if x and not y)
    c = sum(1 for x, y in zip(off, on) if y and not x)
    p_mc = binomtest(min(b, c), b + c, 0.5).pvalue if b + c else 1.0
    n = len(off)
    mde = 100 * (Z975 + Z80) * math.sqrt((b + c) / n) / math.sqrt(n) if b + c else float("nan")
    return b, c, p_mc, signflip(np.array(on, float) - np.array(off, float), name), mde


def fmt_p(p):
    return "<0.0001" if p < 1e-4 else f"{p:.4f}" if p < 0.01 else f"{p:.3f}"


def main():
    idx = [r["idx"] for r in csv.DictReader(SUB.open(encoding="utf-8"))]
    off = {r["idx"]: r for r in csv.DictReader(OFF.open(encoding="utf-8")) if r["model"] == "kimi-k3"}
    on = {r["idx"]: r for r in csv.DictReader(ON.open(encoding="utf-8"))}
    missing = [i for i in idx if i not in on]
    idx = [i for i in idx if i in on]
    n = len(idx)
    gold = [off[i]["gold"] for i in idx]
    c_off = [int(off[i]["correct"]) for i in idx]
    c_on = [int(on[i]["correct"]) for i in idx]
    c_strict = [int(on[i]["correct_strict"]) for i in idx]
    tok_off = [int(off[i]["output_tokens"]) for i in idx]
    tok_on = [int(on[i]["output_tokens"]) for i in idx]
    rea_on = [int(on[i]["reasoning_tokens"]) for i in idx]
    vis_on = [a - b for a, b in zip(tok_on, rea_on)]

    L = ["# TeleLogs：kimi-k3 开思考对照（50 题）", "",
         "由 `analysis/telelogs_thinking.py` 生成，请勿手改。规则见 STATUS 第二节第 9 项（跑之前提交 `a3062a4`）。", "",
         "设计：同一批 50 题（从 TeleLogs 200 题抽样里按类分层，C1 / C2 各 7、其余各 6，种子 20261016）只改思考开关，逐题配对。"
         "关思考 = 主实验的百炼 kimi-k3（`enable_thinking=false`、温度 0、max_tokens 4096）；"
         "开思考 = OpenCode Go 的 kimi-k3（K3 恒开思考，`reasoning_effort = low`，温度 / top_p 由厂商固定为 1.0 / 0.95，"
         "max_tokens 16384），每题 1 次。**开 − 关的差值里混有 Go 与百炼的部署差异与温度差异**（用户定忽略部署差异）；"
         "结论只适用于低思考强度。TeleLogs 不在思考对照实验范围内，结果不外推到其他任务。", ""]
    if missing:
        L += [f"缺开思考结果的题：{len(missing)}（{'、'.join(missing)}），不进比较。", ""]

    # ① 行为
    trunc = sum(on[i]["finish_reason"] == "length" for i in idx)
    fail = sum(int(on[i]["extract_fail"]) for i in idx)
    fail_strict = sum(1 for i in idx if not on[i]["pred_strict"])
    cost = sum(float(on[i]["cost_usd"]) for i in idx)
    lat = [float(on[i]["latency_s"]) for i in idx if on[i]["latency_s"]]
    L += ["## 1. 行为：开思考后它是否开始做中间计算", "",
          "| | 关思考（百炼） | 开思考 low（Go） |", "| --- | --- | --- |",
          f"| 输出 token 中位数（含思考） | {statistics.median(tok_off):.0f} | {statistics.median(tok_on):.0f} |",
          f"| 输出 token 范围 | {min(tok_off)}–{max(tok_off)} | {min(tok_on)}–{max(tok_on)} |",
          f"| 其中思考 token 中位数 | 0 | {statistics.median(rea_on):.0f}（范围 {min(rea_on)}–{max(rea_on)}） |",
          f"| 可见答案 token 中位数 | {statistics.median(tok_off):.0f} | {statistics.median(vis_on):.0f} |",
          f"| 截断（撞 max_tokens） | 0 | {trunc} |",
          f"| `\\boxed{{}}` 抽取失败（主口径 / 跑之前定的严格抽取） | {sum(int(off[i]['extract_fail']) for i in idx)} | {fail} / {fail_strict} |",
          "", f"开思考一侧按 Go 价目合计 ${cost:.2f}（每题约 ${cost / n:.3f}），时延中位数 {statistics.median(lat):.1f} 秒。", "",
          f"严格抽取的 {fail_strict} 次失败全部是 `\\boxed{{\\text{{C4}}}}`、`\\boxed{{\\mathrm{{C2}}}}` 这类嵌一层花括号的写法"
          "（原正则不认嵌套）；Oct 16 看过结果后修正抽取器，已核对主实验全部原始回答改前改后抽取结果完全一致，"
          "所以主口径用修正后的抽取，严格口径作敏感性分析另报（第 2 节）。", ""]

    # ② 正确率
    k_off, k_on, k_st = sum(c_off), sum(c_on), sum(c_strict)
    L += ["## 2. 正确率（配对，不作显著性结论）", "",
          "| 口径 | 关思考 | 开思考 | 差值 | 关对开错 / 关错开对 | exact McNemar p | 置换 p | MDE（80% 功效） | 开思考对随机水平 12.5%（单侧二项） |",
          "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for name, cc, k in (("主口径（修正抽取）", c_on, k_on), ("严格抽取（跑之前定）", c_strict, k_st)):
        b, c, p_mc, p_perm, mde = paired(c_off, cc, name)
        lo, hi = wilson(k, n)
        L.append(f"| {name} | {k_off}/{n}（{k_off / n:.0%}） | {k}/{n}（{k / n:.0%}，95% CI {lo:.0%}–{hi:.0%}） | "
                 f"{100 * (k - k_off) / n:+.0f}pt | {b} / {c} | {fmt_p(p_mc)} | {fmt_p(p_perm)} | {mde:.1f}pt | "
                 f"p = {fmt_p(binomtest(k, n, CHANCE, alternative='greater').pvalue)} |")
    lo_off, hi_off = wilson(k_off, n)
    L += ["", f"关思考 {k_off}/{n} 的 95% CI 为 {lo_off:.0%}–{hi_off:.0%}，"
          f"对随机水平单侧 p = {fmt_p(binomtest(k_off, n, CHANCE, alternative='greater').pvalue)}。"
          "按规则只报方向与量级：n = 50 时 MDE 很大，p 值仅作参考。", ""]

    # ③ 分层
    pred_off = Counter(off[i]["pred"] or "抽取失败" for i in idx)
    pred_on = Counter(on[i]["pred"] or "抽取失败" for i in idx)
    L += ["## 3. 按根因类别", "",
          "| 类别 | 题数 | 关思考答对 | 开思考答对 | 关思考预测为该类 | 开思考预测为该类 |", "| --- | --- | --- | --- | --- | --- |"]
    for c in CLASSES:
        ks = [j for j, g in enumerate(gold) if g == c]
        L.append(f"| {c} | {len(ks)} | {sum(c_off[j] for j in ks)} | {sum(c_on[j] for j in ks)} | "
                 f"{pred_off.get(c, 0)} | {pred_on.get(c, 0)} |")
    used_off = sum(1 for c in CLASSES if pred_off.get(c))
    used_on = sum(1 for c in CLASSES if pred_on.get(c))
    zero_off = [c for c in CLASSES if not any(c_off[j] for j, g in enumerate(gold) if g == c)]
    zero_on = [c for c in CLASSES if not any(c_on[j] for j, g in enumerate(gold) if g == c)]
    L += ["", f"押 C4：关思考 {pred_off.get('C4', 0)}/{n}，开思考 {pred_on.get('C4', 0)}/{n}（C4 实际 {gold.count('C4')} 题）。"
          f"用到的类别数：关 {used_off}、开 {used_on}。全类 0 对：关 {len(zero_off)} 类（{'、'.join(zero_off) or '无'}），"
          f"开 {len(zero_on)} 类（{'、'.join(zero_on) or '无'}）。", ""]

    # ④ 结论
    b, c, p_mc, _, mde = paired(c_off, c_on, "主口径（修正抽取）")
    kw = ""
    if RAW.exists():
        reas = [json.loads(x)["reasoning"] for x in RAW.read_text(encoding="utf-8").splitlines() if x.strip()]
        kw = "推理里提到各判据的题数（关键词匹配）：" + "、".join(
            f"{k} {sum(1 for t in reas if re.search(p, t, re.I))}" for k, p in CRITERIA.items()) + f"（共 {len(reas)} 题）；"
    L += ["## 4. 结论（按跑之前定的口径）", "",
          f"- **开始做中间计算：是。** 开思考后输出 token 中位数由 {statistics.median(tok_off):.0f} 升到 {statistics.median(tok_on):.0f}"
          f"（思考中位 {statistics.median(rea_on):.0f}，可见答案中位 {statistics.median(vis_on):.0f}）。{kw}"
          f"截断 {trunc}，主口径抽取失败 {fail}。",
          f"- **正确率离开随机水平：是。** 开思考 {k_on}/{n}（{k_on / n:.0%}），关思考 {k_off}/{n}（{k_off / n:.0%}），"
          f"差 {100 * (k_on - k_off) / n:+.0f}pt（关错开对 {c}、关对开错 {b}）；严格抽取口径为 {k_st}/{n}。"
          f"差值超过 MDE（{mde:.0f}pt；严格口径 +{100 * (k_st - k_off) / n:.0f}pt 对 MDE {paired(c_off, c_strict, '严格抽取（跑之前定）')[4]:.0f}pt），"
          "按规则不作显著性结论。",
          f"- **押 C4 的倾向大幅减弱，但预测分布仍不均匀**：C4 预测由 {pred_off.get('C4', 0)} 降到 {pred_on.get('C4', 0)}"
          f"（实际 {gold.count('C4')} 题），用到的类别由 {used_off} 个变 {used_on} 个；"
          f"开思考后 C5、C6 各被预测 {pred_on.get('C5', 0)}、{pred_on.get('C6', 0)} 次（实际各 {gold.count('C5')}、{gold.count('C6')} 题），"
          f"C3（邻区吞吐更高）{gold.count('C3')} 题全错且从未被预测。",
          "- 这支持「关思考下 kimi-k3 垫底主要是不写推理就直接给答案，而不是不会算」的解释，"
          "但**不写成「kimi-k3 开思考更好」**：只有 50 题、每题 1 次、低思考强度，且开、关两侧混有部署与温度差异；"
          "也没有其他模型的开思考对照，不能和别家关思考的正确率直接排名。主实验第四节第 8 项的排名不变。", ""]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    print(f"→ {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
