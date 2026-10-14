"""真实回答上的两档 judge 对照：一致性、长度偏差检查、分歧仲裁抽样（Spec「真实回答上的一致性与分歧仲裁」）。

规则在判分前写进 STATUS 决定日志（Oct 14，`cb5037f`），本脚本只照规则执行：

- 一致性：逐要点判档一致率与 Cohen's kappa（未加权 / 线性加权），高危项与扣分项触发一致率，
  一票否决一致率，总分 Spearman；各被测模型在两档下的均分与名次。
- 长度偏差：d = 主 judge 总分 − 第二 judge 总分；相对长度 = 回答字数 ÷ 该题各回答字数中位数；
  d 与相对长度的 Spearman 相关，题内置换检验（每题内打乱长度，10000 次，种子 20261015），
  单侧 p < 0.05 且相关 > 0 → 判为主 judge 有长度偏差，排序改用第二 judge 的分数。
- 分歧仲裁抽样：总体 = 要点判档不同，或同一高危项 / 扣分项一档触发一档未触发；先全取高危项分歧
  （至多 20 个），余下名额从要点分歧中按被测模型分层等额抽，合计 60 个（扣分项分歧只计数，不抽）。
  仲裁材料盲化：两档判定随机标为 A / B，不显示模型名与 judge 名。
- 仲裁结果（仲裁表填完后重跑）：揭盲统计两档各自判对的比例，按决定日志（Oct 14，`aef89ff`，揭盲前提交）定主分口径：
  只有主 judge 触发的高危项被判错过半 → 一票否决改为同一高危项两档都触发才算；主 judge 判档更高的要点被判错过半
  → 要点与扣分项改用第二 judge。最终分数写入 results/judge/<run>/final_scores.csv。

只统计缓存键与当前提示词 / 题目 / 回答一致、且成功的第 0 次判定。

用法：
  uv run python analysis/judge_agreement.py --run main_off --answers results/answers/main_off.jsonl
输出（脚本生成，请勿手改；仲裁表的 human / note 两列由用户填写，重跑不覆盖已有的仲裁表）：
  reports/judge/<run>_agreement.md                     一致性、名次、长度偏差检查、仲裁结果与最终主分
  results/judge/<run>/final_scores.csv                  最终主分（仲裁表填完后才生成）
  data/scenarios/arbitration/<run>.md                  仲裁材料（题目、要点、参考答案、回答、A / B 判定与摘录）
  data/scenarios/arbitration/<run>.csv                 仲裁表：item、human（A / B / 都不对 / 判断不了）、note
  data/scenarios/arbitration/<run>_key.csv             A / B 与 judge 的对应（填完仲裁表前不要打开）
"""
import argparse
import csv
import json
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import rankdata, spearmanr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from judge_scenarios import OUT, PROMPTS, SCENARIOS, cache_key, latest_ok, load_records  # noqa: E402

REPORTS = ROOT / "reports/judge"
ARB = ROOT / "data/scenarios/arbitration"
SEED = 20261015
N_PERM = 10000
N_SAMPLE = 60
MAX_HR = 20
LEVELS = {"covered": 2, "partial": 1, "missed": 0}
SHORT = {"covered": "covered", "partial": "partial", "missed": "missed", True: "触发", False: "未触发"}


def load_judge(log, answers, scns):
    """返回 (judge 名, effort, prompt, {answer_id: 记录})，只取缓存键匹配、成功的第 0 次判定。"""
    recs = load_records(log)
    meta = next((r for r in reversed(recs) if r.get("ok")), None)
    if meta is None:
        raise SystemExit(f"{log} 没有成功的判定记录")
    system = (PROMPTS / f"judge_{meta['prompt']}.md").read_text(encoding="utf-8")
    keys = {a["answer_id"]: cache_key(system, meta["judge"], meta["effort"], scns[a["scenario_id"]], a["text"])
            for a in answers}
    ok = latest_ok([r for r in recs if keys.get(r["answer_id"]) == r["key"] and r["repeat"] == 0])
    return meta["judge"], meta["effort"], meta["prompt"], {aid: r for (aid, _, _), r in ok.items()}


def kappa(pairs, weighted=False):
    """pairs: [(a, b)]，取值 0/1/2。weighted=True 用线性权重。"""
    n = len(pairs)
    if n == 0:
        return float("nan")
    cats = [0, 1, 2]
    w = (lambda i, j: abs(i - j) / 2) if weighted else (lambda i, j: float(i != j))
    pa = {c: sum(a == c for a, _ in pairs) / n for c in cats}
    pb = {c: sum(b == c for _, b in pairs) / n for c in cats}
    obs = sum(w(a, b) for a, b in pairs) / n
    exp = sum(w(i, j) * pa[i] * pb[j] for i in cats for j in cats)
    return 1 - obs / exp if exp else float("nan")


def flags(rec, key):
    return {x["index"]: x for x in rec["parsed"][key]}


def length_bias(rows):
    """rows: [(scenario_id, d, 相对长度)]。返回 (rho, 单侧 p)。题内置换。"""
    d = rankdata([r[1] for r in rows])
    ln = rankdata([r[2] for r in rows])
    groups = defaultdict(list)
    for i, r in enumerate(rows):
        groups[r[0]].append(i)
    d = (d - d.mean()) / d.std()

    def rho(x):
        x = (x - x.mean()) / x.std()
        return float((d * x).mean())

    obs = rho(ln)
    rng = np.random.default_rng(SEED)
    idx = [np.array(g) for g in groups.values()]
    hits = 0
    for _ in range(N_PERM):
        perm = ln.copy()
        for g in idx:
            perm[g] = ln[rng.permutation(g)]
        hits += rho(perm) >= obs
    return obs, (hits + 1) / (N_PERM + 1)


def wilson(k, n, z=1.96):
    if n == 0:
        return "—"
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * (p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5 / d
    return f"{p:.0%}（{k}/{n}，[{max(0, c - h):.0%}, {min(1, c + h):.0%}]）"


def final_score(scn, pts_rec, m, s, veto_both):
    """要点与扣分项取 pts_rec；一票否决：veto_both 时同一高危项两档都触发才算，否则取主 judge。"""
    sc = pts_rec["score"]
    if veto_both:
        fs = flags(s, "high_risk")
        veto = any(x["triggered"] and fs[x["index"]]["triggered"] for x in m["parsed"]["high_risk"])
    else:
        veto = m["score"]["veto"]
    return 0.0 if veto else min(100.0, max(0.0, sc["raw"] + sc["deduction"])), veto


def arbitration(sheet, key_path, M, S, both, ans, scns, models, rM, rS, args):
    """揭盲统计仲裁结果，按决定日志（Oct 14，`aef89ff`，揭盲前提交）定主分口径，写最终分数表。"""
    with sheet.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows or any(r["human"].strip() not in ("A", "B", "都不对", "判断不了") for r in rows):
        return ["## 分歧仲裁结果", "", "仲裁表未填完或有非法值，跳过。", ""]
    with key_path.open(encoding="utf-8") as f:
        key = {r["item"]: r for r in csv.DictReader(f)}
    win, by_model = defaultdict(int), defaultdict(lambda: defaultdict(int))
    hr_solo, pt_up, other = defaultdict(int), defaultdict(int), defaultdict(int)
    for r in rows:
        k, h = key[r["item"]], r["human"].strip()
        main_is_a = k["A_is"] == "主"
        vm, vs = (r["A"], r["B"]) if main_is_a else (r["B"], r["A"])
        who = {"A": "主" if main_is_a else "第二", "B": "第二" if main_is_a else "主"}.get(h, h)
        win[who] += 1
        by_model[k["model"]][who] += 1
        if r["point"].startswith("H"):
            (hr_solo if vm == "触发" else other)[who] += 1
        elif LEVELS[vm] > LEVELS[vs]:
            pt_up[who] += 1
        else:
            other[who] += 1
    n = len(rows)
    n_hr, n_up = sum(hr_solo.values()), sum(pt_up.values())
    veto_both = hr_solo["第二"] > n_hr / 2
    use_second_pts = pt_up["第二"] > n_up / 2
    L = ["## 分歧仲裁结果（揭盲）", "",
         f"仲裁者为单一非专家（用户），对照参考答案判断；{n} 条中「都不对」{win['都不对']}、「判断不了」{win['判断不了']}。", "",
         f"- 判对的比例：主 judge {wilson(win['主'], n)}，第二 judge {wilson(win['第二'], n)}。",
         f"- 高危项只有主 judge 触发：{n_hr} 条，仲裁判主 judge 错 {hr_solo['第二']}、对 {hr_solo['主']}。",
         f"- 要点主 judge 判档更高：{n_up} 条，仲裁判主 judge 对 {pt_up['主']}、错 {pt_up['第二']}。",
         f"- 其余（第二 judge 独自触发高危、主 judge 判档更低）：主 judge 对 {other['主']}、第二 judge 对 {other['第二']}。",
         "- 按被测模型（主 / 第二 判对）：" + "，".join(f"{m} {c['主']}/{c['第二']}" for m, c in sorted(by_model.items())) + "。", "",
         "按事先定的规则：" + ("一票否决改为同一高危项两档都触发才算" if veto_both else "保留主 judge 的一票否决") + "；"
         + ("要点与扣分项改用第二 judge" if use_second_pts else "要点与扣分项保留主 judge") + "。", ""]

    out = args.out / args.run / "final_scores.csv"
    fin, vetoed = {}, {}
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["answer_id", "scenario_id", "model", "total", "veto", "main_total", "second_total"])
        for a in both:
            m, s = M[a], S[a]
            tot, veto = final_score(scns[ans[a]["scenario_id"]], s if use_second_pts else m, m, s, veto_both)
            fin[a], vetoed[a] = tot, veto
            w.writerow([a, ans[a]["scenario_id"], ans[a]["source"], round(tot, 1), int(veto),
                        m["score"]["total"], s["score"]["total"]])
    stats = {}
    for src in models:
        v = [fin[a] for a in both if ans[a]["source"] == src]
        stats[src] = (statistics.mean(v), statistics.stdev(v) / len(v) ** 0.5)
    order = sorted(models, key=lambda x: -stats[x][0])
    L += ["## 最终主分", "", f"写入 `{out.relative_to(ROOT)}`。一票否决 {sum(vetoed.values())} 条"
          f"（主 judge {sum(M[a]['score']['veto'] for a in both)}、第二 judge {sum(S[a]['score']['veto'] for a in both)}）。", "",
          "| 名次 | 被测模型 | 最终均分 | 主 judge 名次 | 第二 judge 名次 |", "| --- | --- | --- | --- | --- |"]
    L += [f"| {i} | {src} | {stats[src][0]:.1f} ± {stats[src][1]:.1f} | {rM[src]} | {rS[src]} |"
          for i, src in enumerate(order, 1)]
    return L + [""]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--answers", required=True, type=Path)
    ap.add_argument("--main", default="claude_claude-haiku-5-5_medium", help="主 judge 的日志名（不含 .jsonl）")
    ap.add_argument("--second", default="claude_claude-sonnet-5-5_medium")
    ap.add_argument("--scenarios", type=Path, default=SCENARIOS)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    scns = {q["id"]: q for q in json.loads(args.scenarios.read_text(encoding="utf-8"))}
    answers = [json.loads(line) for line in args.answers.read_text(encoding="utf-8").splitlines() if line.strip()]
    ans = {a["answer_id"]: a for a in answers}
    jm, em, pm, M = load_judge(args.out / args.run / f"{args.main}.jsonl", answers, scns)
    js, es, ps, S = load_judge(args.out / args.run / f"{args.second}.jsonl", answers, scns)
    both = sorted(set(M) & set(S))
    models = sorted({ans[a]["source"] for a in both})

    # ---------- 一致性 ----------
    pt_pairs, pt_by_model = [], defaultdict(lambda: [0, 0])
    hr = [0, 0]
    de = [0, 0]
    veto = [0, 0]
    pop_points, pop_hr, pop_de = [], [], []
    for aid in both:
        m, s = M[aid], S[aid]
        src = ans[aid]["source"]
        pm_ = {p["id"]: p for p in m["parsed"]["points"]}
        ps_ = {p["id"]: p for p in s["parsed"]["points"]}
        for pid in sorted(pm_):
            a, b = LEVELS[pm_[pid]["verdict"]], LEVELS[ps_[pid]["verdict"]]
            pt_pairs.append((a, b))
            pt_by_model[src][0] += a == b
            pt_by_model[src][1] += 1
            if a != b:
                pop_points.append(("point", aid, pid, pm_[pid], ps_[pid]))
        for key, cnt, pop in (("high_risk", hr, pop_hr), ("deductions", de, pop_de)):
            fm, fs = flags(m, key), flags(s, key)
            for i in sorted(fm):
                same = fm[i]["triggered"] == fs[i]["triggered"]
                cnt[0] += same
                cnt[1] += 1
                if not same:
                    pop.append((key, aid, i, fm[i], fs[i]))
        veto[0] += m["score"]["veto"] == s["score"]["veto"]
        veto[1] += 1

    tm = [M[a]["score"]["total"] for a in both]
    ts = [S[a]["score"]["total"] for a in both]
    rho_tot = spearmanr(tm, ts).statistic

    def per_model(J):
        out = {}
        for src in models:
            v = [J[a]["score"]["total"] for a in both if ans[a]["source"] == src]
            out[src] = (statistics.mean(v), statistics.stdev(v) / len(v) ** 0.5, sum(J[a]["score"]["veto"] for a in both
                                                                                    if ans[a]["source"] == src))
        return out

    pmM, pmS = per_model(M), per_model(S)

    def ranks(pm_):
        order = sorted(models, key=lambda x: -pm_[x][0])
        return {src: i + 1 for i, src in enumerate(order)}

    rM, rS = ranks(pmM), ranks(pmS)

    # ---------- 长度偏差 ----------
    by_scn = defaultdict(list)
    for a in both:
        by_scn[ans[a]["scenario_id"]].append(len(ans[a]["text"]))
    med = {k: statistics.median(v) for k, v in by_scn.items()}
    rows = [(ans[a]["scenario_id"], M[a]["score"]["total"] - S[a]["score"]["total"],
             len(ans[a]["text"]) / med[ans[a]["scenario_id"]]) for a in both]
    rho_len, p_len = length_bias(rows)
    biased = rho_len > 0 and p_len < 0.05

    # ---------- 报告 ----------
    agree = sum(a == b for a, b in pt_pairs)
    up = sum(a > b for a, b in pt_pairs)
    L = [f"# 真实回答上的两档 judge 对照（{args.run}）", "",
         "由 `analysis/judge_agreement.py` 生成，请勿手改。规则见 STATUS 决定日志（Oct 14，判分前提交）。", "",
         f"- 主 judge：{jm}（effort {em}，提示词 {pm}）；第二 judge：{js}（effort {es}，提示词 {ps}）。",
         f"- 回答 {len(answers)} 份，两档都判成 {len(both)} 份（主 {len(M)}、第二 {len(S)}）；被测模型 {len(models)} 个。", "",
         "## 各模型均分与名次", "",
         "均分 ± 标准误；否决 = 触发一票否决的回答数。d = 主 − 第二。", "",
         "| 被测模型 | 字数中位数 | 主 judge 均分 | 名次 | 否决 | 第二 judge 均分 | 名次 | 否决 | d 均值 |",
         "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for src in sorted(models, key=lambda x: rM[x]):
        lens = [len(ans[a]["text"]) for a in both if ans[a]["source"] == src]
        dd = [r[1] for a, r in zip(both, rows) if ans[a]["source"] == src]
        L.append(f"| {src} | {int(statistics.median(lens))} | {pmM[src][0]:.1f} ± {pmM[src][1]:.1f} | {rM[src]} | "
                 f"{pmM[src][2]} | {pmS[src][0]:.1f} ± {pmS[src][1]:.1f} | {rS[src]} | {pmS[src][2]} | "
                 f"{statistics.mean(dd):+.1f} |")
    tau_pairs = [(x, y) for i, x in enumerate(models) for y in models[i + 1:]]
    conc = sum((rM[x] - rM[y]) * (rS[x] - rS[y]) > 0 for x, y in tau_pairs)
    L += ["", f"两档名次一致的模型对：{conc}/{len(tau_pairs)}（Kendall τ = {(2 * conc - len(tau_pairs)) / len(tau_pairs):.2f}）。", "",
          "## 一致性", "",
          f"- 逐要点判档一致：{agree / len(pt_pairs):.1%}（{agree}/{len(pt_pairs)}）；不一致处主 judge 判得高 {up}、"
          f"低 {len(pt_pairs) - agree - up}。",
          f"- Cohen's kappa：未加权 {kappa(pt_pairs):.2f}，线性加权 {kappa(pt_pairs, True):.2f}。",
          f"- 高危项触发一致：{hr[0] / hr[1]:.1%}（{hr[0]}/{hr[1]}）；扣分项触发一致：{de[0] / de[1]:.1%}（{de[0]}/{de[1]}）；"
          f"一票否决一致：{veto[0]}/{veto[1]}。",
          f"- 总分 Spearman：{rho_tot:.3f}；|d| 均值 {statistics.mean(abs(r[1]) for r in rows):.1f}，最大 {max(abs(r[1]) for r in rows):.1f}。",
          "- 逐要点一致率按被测模型：" + "，".join(f"{src} {v[0] / v[1]:.1%}" for src, v in sorted(pt_by_model.items())) + "。", "",
          "## 长度偏差检查（事先定的规则）", "",
          f"- d 与题内相对长度的 Spearman 相关 ρ = {rho_len:+.3f}，题内置换检验单侧 p = {p_len:.4f}"
          f"（{N_PERM} 次，种子 {SEED}，n = {len(rows)}）。",
          "- 结论：" + ("**主 judge 有长度偏差**（ρ > 0 且 p < 0.05）→ 按规则排序改用第二 judge 的分数做主分。" if biased
                       else "未检出主 judge 的长度偏差（规则：ρ > 0 且 p < 0.05）→ 维持主 judge 的分数做主分。"), ""]

    # ---------- 仲裁抽样 ----------
    rng = random.Random(SEED)
    hr_s = rng.sample(pop_hr, min(MAX_HR, len(pop_hr)))
    left = N_SAMPLE - len(hr_s)
    pool = defaultdict(list)
    for it in pop_points:
        pool[ans[it[1]]["source"]].append(it)
    for v in pool.values():
        rng.shuffle(v)
    quota = {src: 0 for src in models}
    order = models[:]
    rng.shuffle(order)
    while left > 0 and any(quota[s] < len(pool[s]) for s in models):  # 等额轮流分配，某模型抽空后名额让给其他模型
        for src in order:
            if left and quota[src] < len(pool[src]):
                quota[src] += 1
                left -= 1
    sample = hr_s + [it for src in models for it in pool[src][:quota[src]]]
    rng.shuffle(sample)
    L += ["## 分歧仲裁抽样", "",
          f"- 总体：要点判档分歧 {len(pop_points)}、高危项分歧 {len(pop_hr)}、扣分项分歧 {len(pop_de)}（扣分项只计数，不抽）。",
          f"- 抽出 {len(sample)} 个：高危项 {len(hr_s)}，要点 {len(sample) - len(hr_s)}（按模型：" +
          "，".join(f"{s} {quota[s]}" for s in models) + "）。",
          f"- 仲裁材料 `data/scenarios/arbitration/{args.run}.md`，仲裁表 `{args.run}.csv`。", ""]

    ARB.mkdir(parents=True, exist_ok=True)
    sheet, key_path, pack = ARB / f"{args.run}.csv", ARB / f"{args.run}_key.csv", ARB / f"{args.run}.md"
    if sheet.exists() and key_path.exists():
        L += arbitration(sheet, key_path, M, S, both, ans, scns, models, rM, rS, args)
    REPORTS.mkdir(parents=True, exist_ok=True)
    rep = REPORTS / f"{args.run}_agreement.md"
    rep.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    print(f"→ {rep}")

    if sheet.exists():
        print(f"仲裁表已存在，不覆盖：{sheet}")
        return
    P = [f"# 分歧仲裁材料（{args.run}）", "",
         "由 `analysis/judge_agreement.py` 生成。每条是两档 judge 判法不一致的一项；A / B 是随机标记，不对应固定的 judge。",
         "对照参考答案与要点文字，判断回答里是否写到了这一项，在仲裁表 `" + sheet.name + "` 的 human 列填：",
         "`A`（A 的判定对）、`B`、`都不对`（例如 A 判 covered、B 判 missed，你认为该判 partial）、`判断不了`（对照参考答案也判断不了，"
         "归入必须专家复核）。note 列可写一句理由。高危项问的是「回答是否主张按这种方式做」，只是提到或加了防护前提不算。", ""]
    S_rows, K_rows = [], []
    for n, (kind, aid, idx, fm, fs) in enumerate(sample, 1):
        a = ans[aid]
        q = scns[a["scenario_id"]]
        swap = rng.random() < 0.5
        A, B = (fs, fm) if swap else (fm, fs)
        if kind == "point":
            pt = next(p for p in q["rubric_points"] if p["id"] == idx)
            item, text = idx, f"{pt['text']}（权重 {pt['weight']}）"
            va, vb = SHORT[A["verdict"]], SHORT[B["verdict"]]
        else:
            h = q["high_risk_actions"][idx]
            item, text = f"H{idx}", f"{h['action']}（原因：{h['why']}）"
            va, vb = SHORT[A["triggered"]], SHORT[B["triggered"]]
        P += [f"## 第 {n} 条：{q['id']} {q['title']} · {item}", "",
              f"**{'评分要点' if kind == 'point' else '高危操作'}**：{text}", "",
              f"- A：{va}。摘录：{A.get('evidence') or '（无）'}",
              f"- B：{vb}。摘录：{B.get('evidence') or '（无）'}", "",
              "<details><summary>参考答案</summary>", "", q["reference_answer"], "", "</details>", "",
              "<details><summary>被评回答</summary>", "", a["text"], "", "</details>", ""]
        S_rows.append([n, q["id"], item, va, vb, "", ""])
        K_rows.append([n, aid, a["source"], item, "主" if not swap else "第二", "第二" if not swap else "主"])
    pack.write_text("\n".join(P), encoding="utf-8")
    with sheet.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["item", "scenario_id", "point", "A", "B", "human", "note"])
        w.writerows(S_rows)
    with key_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["item", "answer_id", "model", "point", "A_is", "B_is"])
        w.writerows(K_rows)
    print(f"→ {pack}\n→ {sheet}\n→ {key_path}")


if __name__ == "__main__":
    main()
