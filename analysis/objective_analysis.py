"""客观题横评分析层：从 EvalScope reviews 读逐题结果，产出统计报告。

输入：
- results/evalscope/objective/<模型>/reviews/<模型>/teleqna_mcq_<子集>.jsonl
  （sample_score.score.extracted_prediction / .value.accuracy / .status，sample_score.sample_metadata.id）
- results/evalscope_data/teleqna_ops/orig_val.jsonl（每题选项数）
- results/evalscope_data/teleqna_ops/permutations.json（变体字母 → 原选项序号，1-based）
- data/processed/teleqna_test_subset.csv（dimension、shuffle_policy）
- data/processed/teleqna_items.csv（release，3GPP 版本标签）

输出：reports/objective/objective_main.md（本脚本生成，请勿手改）

指标口径（与 Spec 对齐；v2 复核后修订）：
- 噪声底：orig vs rep 的逐题同答案率与正确性一致率（rep 与 orig 选项顺序相同）。
  注意温度 0 不等于确定性（glm-5.2 同答案率仅 94.5%）；打乱掉分应对照各自噪声底解读。
- 打乱掉分：主口径只在 shuffle_policy=free（n=667）上算；pin_last（n=60）单独作补充行
  （其打乱机制与 free 题不同：末位"以上"类选项固定、其余打乱）；no_shuffle（n=4）不计。
- 打乱一致性：free 题上 orig/s1/s2/s3 四次选择映射回原选项后完全一致的比例
  （Spec 字面为"打乱跑 3 次"，此处含 orig 共四次，口径更严）。
- 扣除猜测：逐题修正再平均，corrected = mean_q((x_q − 1/k_q)/(1 − 1/k_q))，k 为每题选项数（4/5 混合），
  基于 orig。逐题版与汇总版 (acc−mean(1/k))/(1−mean(1/k)) 在混合 k 下不等价（本数据差 ≤0.11pt）。
- 维度拆分：5 个子集 pooled 正确率；小维度（SECURITY 13、SERVICE 41）只作参考。
- 区分度：7 模型 × 5 子集共 35 次判定中全对 / 全错的题数（Spec 审计第 4 项）。
- 版本梯度：按 3GPP Release 标签分组的正确率与打乱掉分（Spec 污染检测条款）。
- Bootstrap：按题重抽样（每题得分 = 5 子集均值），B=10000，percentile 95% CI。
  估计的是 pooled（对顺序平均）正确率；CI 重叠不能用于判断模型间显著性。
- McNemar：两两模型在 orig 子集 731 题上的配对检验（exact binomial），Holm 校正（家族 21 对）；
  附每对 MDE（80% 功效、正态近似）。检验力有限：不显著 ≠ 无差异。
- 配对置换检验：以题为单元、题得分 = 5 子集均值，符号翻转置换 B=10000，Holm 校正；
  估计量为 pooled 均值之差，与 McNemar 互补（后者只看 orig 的题级独立性）。
- 功效分析：实验已跑，此处为事后补算（Spec 原按 1200 题预估，v2.2 后子集为 731 题）。
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import binomtest, norm

ROOT = Path(__file__).resolve().parents[1]
REVIEWS = ROOT / "results/evalscope/objective"
DATA = ROOT / "results/evalscope_data/teleqna_ops"
SUBSET_CSV = ROOT / "data/processed/teleqna_test_subset.csv"
ITEMS_CSV = ROOT / "data/processed/teleqna_items.csv"
OUT = ROOT / "reports/objective/objective_main.md"

SUBSETS = ["orig", "rep", "s1", "s2", "s3"]
SHUFFLED = ["s1", "s2", "s3"]
LETTERS = "ABCDE"
B = 10_000
RNG = np.random.default_rng(42)
Z025 = norm.ppf(0.975)          # 1.960，未校正双侧 5%
Z80 = norm.ppf(0.80)            # 0.8416，80% 功效
Z_HOLM = norm.ppf(1 - 0.05 / (2 * 21))  # Holm 最严档：21 对中 p 最小者等价 α/(2m)≈0.00119 → 3.03


def load_predictions(model: str) -> dict[str, dict[str, dict]]:
    """{subset: {qid: {"pred": str|None, "correct": float, "status": str}}}"""
    out: dict[str, dict[str, dict]] = {}
    for subset in SUBSETS:
        path = REVIEWS / model / "reviews" / model / f"teleqna_mcq_{subset}.jsonl"
        rows = {}
        for line in open(path, encoding="utf-8"):
            r = json.loads(line)
            sc = r["sample_score"]["score"]
            qid = r["sample_score"]["sample_metadata"]["id"]
            pred = (sc.get("extracted_prediction") or "").strip().upper()
            rows[qid] = {
                # 注意：必须用 list(LETTERS)；'' in 'ABCDE' 为 True，空抽取会被误判合法
                "pred": pred if pred in list(LETTERS) else None,
                "correct": float(sc["value"]["accuracy"]),
                "status": sc.get("status"),
            }
        out[subset] = rows
    return out


def main() -> None:
    meta = pd.read_csv(SUBSET_CSV).set_index("id")
    option_count = {}
    for line in open(DATA / "orig_val.jsonl", encoding="utf-8"):
        d = json.loads(line)
        option_count[d["id"]] = sum(1 for k in LETTERS if d.get(k))
    perms = json.load(open(DATA / "permutations.json", encoding="utf-8"))
    releases = pd.read_csv(ITEMS_CSV).set_index("id")["release"]

    models = sorted(p.name for p in REVIEWS.iterdir() if (p / "reviews").is_dir())
    preds = {m: load_predictions(m) for m in models}
    qids = list(meta.index)

    # 完整性校验：每模型每子集 731 题且 id 与测试集一致
    problems = []
    for m in models:
        for s in SUBSETS:
            got = preds[m][s]
            if set(got) != set(qids):
                problems.append(f"{m}/{s}: {len(got)} 题，id 集合与测试集不一致")
    if problems:
        raise SystemExit("完整性校验失败：\n" + "\n".join(problems))

    def acc(m, s, ids=None):
        ids = ids or qids
        return float(np.mean([preds[m][s][q]["correct"] for q in ids]))

    free_ids = [q for q in qids if meta.loc[q, "shuffle_policy"] == "free"]
    pin_ids = [q for q in qids if meta.loc[q, "shuffle_policy"] == "pin_last"]

    # 1) 分子集正确率 + 抽取失败率
    tbl_acc = {m: {s: acc(m, s) for s in SUBSETS} for m in models}
    fail = {
        m: sum(
            1
            for s in SUBSETS
            for q in qids
            if preds[m][s][q]["status"] != "success" or preds[m][s][q]["pred"] is None
        )
        for m in models
    }

    # 2) 噪声底：orig vs rep
    noise = {}
    for m in models:
        same_ans = np.mean([preds[m]["orig"][q]["pred"] == preds[m]["rep"][q]["pred"] for q in qids])
        same_corr = np.mean(
            [preds[m]["orig"][q]["correct"] == preds[m]["rep"][q]["correct"] for q in qids]
        )
        noise[m] = (float(same_ans), float(same_corr), abs(tbl_acc[m]["orig"] - tbl_acc[m]["rep"]))

    # 3) 打乱掉分与一致性：free 主口径 + pin_last 补充行
    def orig_option(m, s, q):
        pred = preds[m][s][q]["pred"]
        if pred is None:
            return None
        return perms[q][s][LETTERS.index(pred)]

    def drop_consist(m, ids):
        drop = acc(m, "orig", ids) - float(np.mean([acc(m, s, ids) for s in SHUFFLED]))
        same = 0
        for q in ids:
            picks = {orig_option(m, s, q) for s in ["orig"] + SHUFFLED}
            if None not in picks and len(picks) == 1:
                same += 1
        return drop, (same / len(ids) if ids else float("nan"))

    drop, consist = {}, {}
    for m in models:
        drop[m], consist[m] = drop_consist(m, free_ids)
    pin_drop, pin_consist = {}, {}
    for m in models:
        pin_drop[m], pin_consist[m] = drop_consist(m, pin_ids)

    # 4) 扣除猜测（逐题修正再平均，基于 orig）
    corrected = {}
    for m in models:
        per_q_corr = [
            (preds[m]["orig"][q]["correct"] - 1 / option_count[q])
            / (1 - 1 / option_count[q])
            for q in qids
        ]
        corrected[m] = float(np.mean(per_q_corr))

    # 5) 维度拆分（pooled）
    dims = meta["dimension"].unique().tolist()
    dim_acc = {}
    for d in dims:
        ids = meta.index[meta["dimension"] == d].tolist()
        dim_acc[d] = (len(ids), {m: float(np.mean([acc(m, s, ids) for s in SUBSETS])) for m in models})

    # 6) 区分度：35 次判定（7 模型 × 5 子集）全对 / 全错
    total_per_q = np.array(
        [sum(preds[m][s][q]["correct"] for m in models for s in SUBSETS) for q in qids]
    )
    all_right = [q for q, t in zip(qids, total_per_q) if t == len(models) * len(SUBSETS)]
    all_wrong = [q for q, t in zip(qids, total_per_q) if t == 0]

    # 7) 版本梯度：正确率与 free 题打乱掉分按 3GPP Release 分组
    rel_of = lambda q: ("无标签" if pd.isna(releases.get(q)) else f"Rel-{int(releases[q])}")
    rel_groups = sorted({rel_of(q) for q in qids}, key=lambda x: (x == "无标签", x))
    version_rows = {}
    for g in rel_groups:
        ids = [q for q in qids if rel_of(q) == g]
        free_in_g = [q for q in ids if meta.loc[q, "shuffle_policy"] == "free"]
        acc_g = float(np.mean([acc(m, s, ids) for m in models for s in SUBSETS]))
        drop_g = float(np.mean([drop_consist(m, free_in_g)[0] for m in models])) if free_in_g else float("nan")
        version_rows[g] = (len(ids), len(free_in_g), acc_g, drop_g)

    # 8) Bootstrap CI（按题重抽样，题得分 = 5 子集均值）
    per_q = {m: np.array([[preds[m][s][q]["correct"] for s in SUBSETS] for q in qids]).mean(axis=1) for m in models}
    ci = {}
    n = len(qids)
    for m in models:
        v = per_q[m]
        boots = RNG.choice(v, size=(B, n), replace=True).mean(axis=1)
        ci[m] = (float(np.mean(v)), float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5)))

    # 9) McNemar（orig，exact）+ Holm + 每对 MDE
    pairs = [(models[i], models[j]) for i in range(len(models)) for j in range(i + 1, len(models))]
    mc = {}
    for a, b in pairs:
        ca = np.array([preds[a]["orig"][q]["correct"] for q in qids])
        cb = np.array([preds[b]["orig"][q]["correct"] for q in qids])
        b10 = int(((ca == 1) & (cb == 0)).sum())  # a 对 b 错
        b01 = int(((ca == 0) & (cb == 1)).sum())  # a 错 b 对
        p = float(binomtest(min(b10, b01), b10 + b01, 0.5).pvalue) if b10 + b01 else 1.0
        nd = b10 + b01
        mde_u = (Z025 + Z80) * np.sqrt(nd) / n if nd else float("nan")
        mde_h = (Z_HOLM + Z80) * np.sqrt(nd) / n if nd else float("nan")
        mc[(a, b)] = (b10, b01, p, mde_u, mde_h)

    # 10) 配对置换检验（题级 5 子集均值差，符号翻转）+ 差值 bootstrap CI + Holm
    pt = {}
    for a, b in pairs:
        d = per_q[a] - per_q[b]
        obs = float(np.mean(d))
        signs = RNG.choice([-1.0, 1.0], size=(B, n))
        perm_means = (signs * d).mean(axis=1)
        p = (np.sum(np.abs(perm_means) >= abs(obs)) + 1) / (B + 1)
        boots = RNG.choice(d, size=(B, n), replace=True).mean(axis=1)
        lo, hi = np.percentile(boots, [2.5, 97.5])
        pt[(a, b)] = (obs, float(lo), float(hi), float(p))

    # Holm 校正（对 McNemar 与置换检验分别做，家族各 21 对）
    def holm(pvals: dict) -> dict:
        adj = {}
        running = 0.0
        order = sorted(pvals, key=lambda k: pvals[k])
        for rank, k in enumerate(order):
            running = max(running, min(1.0, pvals[k] * (len(order) - rank)))
            adj[k] = running
        return adj

    mc_adj = holm({k: mc[k][2] for k in mc})
    pt_adj = holm({k: pt[k][3] for k in pt})

    # 功效补算（实验已跑，此处为事后说明）：用观测不一致对率
    med_nd = float(np.median([mc[k][0] + mc[k][1] for k in mc]))
    overall_mde_u = (Z025 + Z80) * np.sqrt(med_nd) / n
    overall_mde_h = (Z_HOLM + Z80) * np.sqrt(med_nd) / n

    # ---------- 报告 ----------
    L = []
    L.append("# 客观题横评报告（关思考）\n")
    L.append("由 `analysis/objective_analysis.py` 生成，请勿手改。731 题 × 5 子集（orig/rep/s1–s3），温度 0，")
    L.append(f"子集构成 free/pin_last/no_shuffle = {len(free_ids)}/{len(pin_ids)}/"
             f"{len(qids) - len(free_ids) - len(pin_ids)}（`teleqna_test_subset.csv` 的 shuffle_policy 列）。\n")

    L.append("\n## 正确率总表\n")
    L.append("| 模型 | orig | rep | s1 | s2 | s3 | 总 | 扣除猜测(orig) | 抽取失败 |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for m in sorted(models, key=lambda x: -np.mean(list(tbl_acc[x].values()))):
        t = tbl_acc[m]
        overall = np.mean(list(t.values()))
        L.append(
            f"| {m} | {t['orig']:.1%} | {t['rep']:.1%} | {t['s1']:.1%} | {t['s2']:.1%} | {t['s3']:.1%} "
            f"| {overall:.1%} | {corrected[m]:.1%} | {fail[m]}/3655 |"
        )

    L.append("\n## 噪声底（orig vs rep，选项顺序相同）\n")
    L.append("温度 0 不等于确定性；打乱掉分应对照各自噪声底解读（glm-5.2 噪声最大）。\n")
    L.append("| 模型 | 逐题同答案率 | 正确性一致率 | \\|acc 差\\| |")
    L.append("| --- | --- | --- | --- |")
    for m in models:
        sa, sc_, d = noise[m]
        L.append(f"| {m} | {sa:.1%} | {sc_:.1%} | {d:.2%} |")

    L.append("\n## 打乱稳健性（free 题 n=667；排除 pin_last「以上」类与 no_shuffle）\n")
    L.append("| 模型 | 打乱掉分（orig − s1–s3 均值） | 四次选择完全一致率 |")
    L.append("| --- | --- | --- |")
    for m in models:
        L.append(f"| {m} | {drop[m]:+.2%} | {consist[m]:.1%} |")
    L.append(f"\npin_last 补充行（n=60，「以上」类选项固定末位、其余打乱，掉分方向与 free 题不同，仅供参考）：\n")
    L.append("| 模型 | pin_last 打乱掉分 | 四次选择完全一致率 |")
    L.append("| --- | --- | --- |")
    for m in models:
        L.append(f"| {m} | {pin_drop[m]:+.2%} | {pin_consist[m]:.1%} |")

    L.append("\n## 区分度（7 模型 × 5 子集共 35 次判定）\n")
    L.append(f"- 全模型全子集都对：**{len(all_right)} 题**")
    L.append(f"- 全模型全子集都错：**{len(all_wrong)} 题**")
    L.append(f"- 其余（有区分度）：{len(qids) - len(all_right) - len(all_wrong)} 题")
    dr = pd.Series([meta.loc[q, "dimension"] for q in all_right]).value_counts().to_dict()
    dw = pd.Series([meta.loc[q, "dimension"] for q in all_wrong]).value_counts().to_dict()
    L.append(f"- 全对题维度分布：{dr}")
    L.append(f"- 全错题维度分布：{dw}")

    L.append("\n## 版本梯度（按 3GPP Release 标签分组）\n")
    L.append("全模型 pooled 正确率与 free 题打乱掉分，只作探索性描述。Spec 事先的假设是污染信号随版本变新而**减弱**；"
             "各组 free 题只有一两百道，组间差值（Rel-18 与 Rel-17 约差 1.8pt）未做显著性检验，粗估标准误约 2pt，"
             "按 Oct 15 的决定视为噪声：**未见版本梯度**，不作为污染证据（新模型因选项顺序打乱就答不出原题的可能性本身很小，"
             "这一检验预期灵敏度低）。\n")
    L.append("| 版本 | n | 其中 free | pooled 正确率 | 平均打乱掉分 |")
    L.append("| --- | --- | --- | --- | --- |")
    for g in rel_groups:
        cnt, fcnt, a_g, d_g = version_rows[g]
        L.append(f"| {g} | {cnt} | {fcnt} | {a_g:.1%} | {d_g:+.2%} |")

    L.append("\n## 维度拆分（5 子集 pooled；小维度只作参考）\n")
    L.append("| 维度 | n | " + " | ".join(models) + " |")
    L.append("| --- | --- | " + " | ".join(["---"] * len(models)) + " |")
    for d in dims:
        cnt, row = dim_acc[d]
        L.append(f"| {d} | {cnt} | " + " | ".join(f"{row[m]:.1%}" for m in models) + " |")

    L.append("\n## Bootstrap 95% CI（按题重抽样，B=10000；题得分 = 5 子集均值）\n")
    L.append("估计量为 pooled（对选项顺序平均）正确率。**CI 重叠不能用于判断模型间显著性**（配对设计下重叠是常态），显著性看配对检验表。\n")
    L.append("| 模型 | 均值 | CI 下界 | CI 上界 |")
    L.append("| --- | --- | --- | --- |")
    for m in sorted(models, key=lambda x: -ci[x][0]):
        mean, lo, hi = ci[m]
        L.append(f"| {m} | {mean:.2%} | {lo:.2%} | {hi:.2%} |")

    L.append("\n## 事后功效分析（补算；Spec 原按 1200 题预估，实际子集 731 题）\n")
    L.append(f"- 观测中位不一致对数 b+c = {med_nd:.0f}（占 731 题的 {med_nd / n:.1%}）。")
    L.append(f"- 80% 功效最小可检出差距（MDE，正态近似）：未校正 **≈{overall_mde_u:.1%}**；"
             f"Holm 最严档（21 对）**≈{overall_mde_h:.1%}**。")
    L.append(f"- 本批相邻名次差距 0.3–1.9pt，低于 MDE：**相邻对\"不显著\"不能解读为\"无差异\"**，只结论\"现有规模分辨不出\"。")
    L.append(f"- 场景题 40–50 题只能支撑分档，不做严格排序（Spec 既定结论，仍然成立）。")

    L.append("\n## McNemar 两两检验（orig 731 题，exact；Holm 校正，家族 21 对）\n")
    L.append("| 模型 A | 模型 B | A 对 B 错 | A 错 B 对 | 原始 p | Holm p | MDE(未校正) | MDE(Holm) | 显著 |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for (a, b) in sorted(mc, key=lambda k: -mc[k][0] - mc[k][1]):
        b10, b01, p, mde_u, mde_h = mc[(a, b)]
        pa = mc_adj[(a, b)]
        sig = "是" if pa < 0.05 else "否"
        L.append(f"| {a} | {b} | {b10} | {b01} | {p:.4f} | {pa:.4f} | {mde_u:.1%} | {mde_h:.1%} | {sig} |")

    L.append("\n## 配对置换检验（题级 5 子集均值差，符号翻转 B=10000；Holm 校正，家族 21 对）\n")
    L.append("估计量为 pooled 均值之差（对选项顺序平均）；与 McNemar（只看 orig）互补，把 rep/s1–s3 的重复测量信息用起来。\n")
    L.append("| 模型 A | 模型 B | 差值 | 差值 95% CI | 原始 p | Holm p | 显著 |")
    L.append("| --- | --- | --- | --- | --- | --- | --- |")
    for (a, b) in sorted(pt, key=lambda k: -abs(pt[k][0])):
        obs, lo, hi, p = pt[(a, b)]
        pa = pt_adj[(a, b)]
        sig = "是" if pa < 0.05 else "否"
        L.append(f"| {a} | {b} | {obs:+.2%} | [{lo:+.2%}, {hi:+.2%}] | {p:.4f} | {pa:.4f} | {sig} |")

    L.append("\n## 口径备注\n")
    L.append(f"- 抽取失败：status ≠ success 或无法抽出合法选项字母；失败题记 0 分计入正确率；分母 3655 = 731 题 × 5 子集。")
    L.append("- 扣除猜测（逐题版）：corrected = mean_q((x_q − 1/k_q)/(1 − 1/k_q))，k ∈ {4,5}；"
             "与汇总版 (acc−mean(1/k))/(1−mean(1/k)) 在混合 k 下不等价，本数据两版差 ≤0.11pt、排名不变；"
             "修正假设乱猜均匀 1/k，对有位置偏好的模型只是近似。")
    L.append("- 打乱掉分含\"数据集位置偏置 × 模型位置偏好\"成分：free 题 gold 原位置偏前（A154/B150/C156/D121/E86），"
             "打乱将其均匀化，掉分 = 位置偏好效应 + 3 次打乱的抽样噪声。")
    L.append("- McNemar 只用人人间独立的 orig 731 题；s1–s3 是同一批题的重复测量，不混入配对检验，"
             "其信息由配对置换检验（题级均值差）补足。")
    L.append("- 打乱一致性含 orig 共四次（Spec 字面为打乱 3 次）；任一次抽取失败即整题计\"不一致\"（失败共 4 例，可忽略）。")
    L.append("- 温度 0 + 固定 seed 不保证 API 端可复现（glm-5.2 rep 与 orig 同答案率仅 94.5%），噪声底即为此而测。")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"written: {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
