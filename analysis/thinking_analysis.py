"""思考模式对照（上线形态）分析：同一批模型开思考 vs 关思考（Spec「思考模式对照实验」；规则见 STATUS 决定日志
Oct 15 晚「思考对照预注册」，`51055ea`，跑之前提交）。

输入：
- 场景题：开思考回答 results/answers/thinking_on.jsonl，判分 results/judge/thinking_on/（Haiku、Sonnet）；
  关思考取 results/judge/main_off/final_scores.csv 与 Haiku 的 scores.csv（分段）。
- 客观题：results/objective_thinking/answers_on.csv、off_orig.csv（scripts/run_objective_thinking.py 导出）。
- 调用开销：results/answers/raw/<模型>__{on,off}.jsonl（只在本地），汇总后写 results/thinking/scenario_calls.csv 入库。

口径（预注册）：
- 场景题：开思考每题得分 = 3 次最终分的均值；关思考 = main_off 最终主分。最终分同 main_off（要点与扣分取 Haiku，
  一票否决须两档同一高危项都触发）。题级配对符号翻转置换检验（双侧，B = 10000），模型间 Holm；按题 bootstrap 95% CI。
  开思考形态内的分档同 scenario_analysis.py；两种形态的排序比较用 Kendall τ。
- 客观题：两层（天花板 / 其余）分层抽样，主估计量 = Σ 层权重 × 层内「开 − 关」均值（权重 = 层在 731 题中的占比）；
  分层的配对符号翻转置换检验（双侧，B = 10000），模型间 Holm；分层 bootstrap 95% CI。抽不出答案记错。
- 只作描述：3 次之间的题内标准差、按题型与诊断题分段的变化、一票否决、token / 花费 / 时延。

用法：uv run python analysis/thinking_analysis.py
输出：reports/thinking/thinking_main.md（脚本生成，请勿手改）、results/thinking/*.csv
"""
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np
from scipy.stats import kendalltau, norm

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))
from judge_agreement import final_score, load_judge  # noqa: E402

SCENARIOS = ROOT / "data/scenarios/scenarios_draft.json"
SPLIT = ROOT / "data/scenarios/judge_split.csv"
ON_ANSWERS = ROOT / "results/answers/thinking_on.jsonl"
ON_JUDGE = ROOT / "results/judge/thinking_on"
OFF_FINAL = ROOT / "results/judge/main_off/final_scores.csv"
OFF_HAIKU = ROOT / "results/judge/main_off/claude_claude-haiku-5-5_medium.scores.csv"
JUDGES = ["claude_claude-haiku-5-5_medium", "claude_claude-sonnet-5-5_medium"]
OBJ = ROOT / "results/objective_thinking"
RAW = ROOT / "results/answers/raw"
OUT_DIR = ROOT / "results/thinking"
REPORT = ROOT / "reports/thinking/thinking_main.md"
SEED = 20261015
B = 10000
ALPHA = 0.05
Z80 = norm.ppf(0.8)
TYPE_NAME = {"consulting": "方案咨询", "diagnosis": "故障诊断", "kpi": "KPI 解读"}
STRATUM_SIZE = {"ceiling": 440, "other": 291}

# 关思考基线的模型名别名。qwen3.8-flash 的开思考一侧跑在 OpenCode Go 上、模型 ID 记为
# qwen3.8-flash-ocgo，而它的关思考沿用百炼 main_off（STATUS 决定日志 Oct 15 晚），
# 所以按开思考的模型名去关思考的基线表里取数时，要换成百炼那一行的名字。
OFF_ALIAS = {"qwen3.8-flash-ocgo": "qwen3.8-flash"}


def with_aliases(d):
    """给关思考基线字典补上别名键，使 (开思考模型名, …) 也能取到基线。"""
    out = dict(d)
    for alias, base in OFF_ALIAS.items():
        out.update({(alias,) + k[1:]: v for k, v in d.items() if k[0] == base})
    return out


def read_csv(path):
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def holm(ps):
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    adj, run = [0.0] * len(ps), 0.0
    for k, i in enumerate(order):
        run = max(run, min(1.0, (len(ps) - k) * ps[i]))
        adj[i] = run
    return adj


def rng_for(name):
    return np.random.default_rng([SEED, sum(map(ord, name))])


def signflip(d, name, w=None):
    """配对符号翻转置换检验（双侧）。w 为逐题权重（分层估计量），默认等权。"""
    d = np.asarray(d, dtype=float)
    w = np.full(len(d), 1 / len(d)) if w is None else np.asarray(w, dtype=float)
    obs = float(d @ w)
    signs = rng_for(name).choice([-1.0, 1.0], size=(B, len(d)))
    perm = signs @ (d * w)
    return float((np.sum(np.abs(perm) >= abs(obs) - 1e-12) + 1) / (B + 1))


def fmt_p(p):
    return "—" if p is None or (isinstance(p, float) and math.isnan(p)) else (f"{p:.4f}" if p >= 1e-4 else "<0.0001")


def ranks(vals):
    order = sorted(range(len(vals)), key=lambda i: -vals[i])
    r = [0] * len(vals)
    for k, i in enumerate(order):
        r[i] = k + 1
    return r


def short(m):
    return m.replace("-0902", "").replace("-0813", "")


# ---------- 场景题 ----------

def load_on_scores(scns):
    """{model: {scenario_id: [(total, veto, haiku_total, sonnet_total, rec_haiku), ...3 次]}}"""
    answers = [json.loads(x) for x in ON_ANSWERS.read_text(encoding="utf-8").splitlines() if x.strip()]
    _, _, _, M = load_judge(ON_JUDGE / f"{JUDGES[0]}.jsonl", answers, scns)
    _, _, _, S = load_judge(ON_JUDGE / f"{JUDGES[1]}.jsonl", answers, scns)
    out, rows, missing = defaultdict(lambda: defaultdict(list)), [], defaultdict(int)
    for a in answers:
        aid = a["answer_id"]
        if aid not in M or aid not in S:
            missing[a["model"]] += 1
            continue
        m, s = M[aid], S[aid]
        total, veto = final_score(scns[a["scenario_id"]], m, m, s, veto_both=True)
        out[a["model"]][a["scenario_id"]].append((total, veto, m["score"]["total"], s["score"]["total"], m, a["repeat"]))
        rows.append({"answer_id": aid, "scenario_id": a["scenario_id"], "model": a["model"], "repeat": a["repeat"],
                     "total": total, "veto": int(veto), "haiku_total": m["score"]["total"],
                     "sonnet_total": s["score"]["total"], "finish_reason": a.get("finish_reason")})
    if rows:
        write_csv(OUT_DIR / "scenario_on_final_scores.csv", sorted(rows, key=lambda r: r["answer_id"]))
    return out, missing, answers


def scenario_section(scns, typ):
    on, missing, answers = load_on_scores(scns)
    off_fin = read_csv(OFF_FINAL)
    off = {(r["model"].split(":")[0], r["scenario_id"]): r for r in off_fin}
    off_pts = {(r["source"].split(":")[0], r["scenario_id"]): r for r in read_csv(OFF_HAIKU) if r["repeat"] == "0"}
    off, off_pts = with_aliases(off), with_aliases(off_pts)
    ids = sorted(scns)
    n = len(ids)
    # 纳入判据（STATUS D9 选 A，与预注册「5 个模型 Holm」和偏离 ②「每题按已有次数取均值」一致）：
    # 每题至少有 1 次开思考即可进检验，按已有次数取均值；只有整题完全没答的模型才落到「未齐」。
    models = [m for m in on if all(len(on[m][q]) >= 1 for q in ids)]
    partial = {m: sum(len(on[m][q]) for q in ids) for m in on if m not in models}
    reps = {m: sum(len(on[m][q]) for q in ids) for m in models}
    L = ["## 1. 场景题（45 题；开思考每题按已有次数取均值，关思考 = main_off 1 次）", ""]
    if partial or missing:
        L += ["未齐的模型（有整题没答，不进检验）：" + "，".join(f"{m} {k}/{3 * n}" for m, k in partial.items()) +
              ("；判分缺失：" + "，".join(f"{m} {k}" for m, k in missing.items()) if missing else ""), ""]
    if any(v < 3 * n for v in reps.values()):
        L += ["每题次数不足 3 的模型（按已有次数取均值，缺的次数见下）：" +
              "，".join(f"{m} {v}/{3 * n}" for m, v in sorted(reps.items()) if v < 3 * n), ""]
    if not models:
        return L + ["开思考判分未完成，待跑。", ""], {}
    X_on = {m: np.array([np.mean([x[0] for x in on[m][q]]) for q in ids]) for m in models}
    X_off = {m: np.array([float(off[(m, q)]["total"]) for q in ids]) for m in models}
    res = {}
    for m in models:
        d = X_on[m] - X_off[m]
        boot = rng_for(f"boot:scn:{m}").integers(0, n, size=(B, n))
        bm = d[boot].mean(axis=1)
        res[m] = {"off": X_off[m].mean(), "on": X_on[m].mean(), "d": d.mean(), "lo": np.percentile(bm, 2.5),
                  "hi": np.percentile(bm, 97.5), "p": signflip(d, f"scn:{m}"), "sd": d.std(ddof=1),
                  "rep_sd": np.mean([np.std([x[0] for x in on[m][q]], ddof=1) for q in ids if len(on[m][q]) >= 2]),
                  "veto_off": sum(int(off[(m, q)]["veto"]) for q in ids),
                  "veto_on": sum(sum(x[1] for x in on[m][q]) / len(on[m][q]) for q in ids),
                  "reps": reps[m],
                  "trunc": sum(1 for a in answers if a["model"] == m and a.get("finish_reason") == "length")}
    for m, a in zip(models, holm([res[m]["p"] for m in models])):
        res[m]["p_holm"] = a
    z_h = norm.ppf(1 - ALPHA / (2 * len(models)))
    order = sorted(models, key=lambda m: -res[m]["on"])
    L += ["主分规则同 main_off（要点与扣分取 Haiku，一票否决须 Haiku、Sonnet 同一高危项都触发）。"
          "差值 = 开 − 关（按题配对）；配对符号翻转置换检验，双侧，B = 10000，"
          f"{len(models)} 个模型 Holm；95% CI 为按题 bootstrap；MDE 为 80% 功效（Holm 最严档）。"
          "题内标准差 = 同一题多次开思考得分的标准差（只计 ≥ 2 次的题，再对题平均），反映采样带来的波动。", "",
          "| 模型 | 关思考 | 开思考 | 差值 | 95% CI | p | Holm p | MDE | 题内标准差 | 一票否决（关 → 开，开按题均摊） | 截断 |",
          "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for m in order:
        r = res[m]
        L.append(f"| {short(m)} | {r['off']:.1f} | **{r['on']:.1f}** | {r['d']:+.1f} | [{r['lo']:+.1f}, {r['hi']:+.1f}] | "
                 f"{fmt_p(r['p'])} | {fmt_p(r['p_holm'])}{' *' if r['p_holm'] < ALPHA else ''} | "
                 f"{(z_h + Z80) * r['sd'] / math.sqrt(n):.1f} | {r['rep_sd']:.1f} | {r['veto_off']} → {r['veto_on']:.1f} | "
                 f"{r['trunc']}/{r['reps']} |")

    # 开思考形态内的分档与排序
    means_on = [res[m]["on"] for m in models]
    pairs = []
    for i, j in combinations(range(len(models)), 2):
        d = X_on[models[i]] - X_on[models[j]]
        pairs.append((i, j, d.mean(), signflip(d, f"pair:{models[i]}:{models[j]}")))
    adj = holm([p[3] for p in pairs])
    sig = {}
    for (i, j, _, _), a in zip(pairs, adj):
        sig[(i, j)] = sig[(j, i)] = a < ALPHA
    left = sorted(range(len(models)), key=lambda i: -means_on[i])
    tier_of, t = {}, 0
    while left:
        t += 1
        top = left[0]
        tier = [k for k in left if k == top or not sig[(top, k)]]
        for k in tier:
            tier_of[k] = t
        left = [k for k in left if k not in tier]
    r_on, r_off = ranks(means_on), ranks([res[m]["off"] for m in models])
    tau = kendalltau(r_on, r_off).statistic if len(models) > 2 else float("nan")
    L += ["", "### 开思考形态内的排序与分档", "",
          "分档规则同 `scenario_analysis.py`：均分最高者与所有和它差异不显著（配对置换，Holm）的为一档，依此类推。", "",
          "| 开思考名次 | 模型 | 开思考均分 | 档 | 关思考名次（同一批模型内） |", "| --- | --- | --- | --- | --- |"]
    for i in sorted(range(len(models)), key=lambda k: r_on[k]):
        L.append(f"| {r_on[i]} | {short(models[i])} | {means_on[i]:.1f} | {tier_of[i]} | {r_off[i]} |")
    sig_pairs = [(models[i], models[j], dd, a) for (i, j, dd, _), a in zip(pairs, adj) if a < ALPHA]
    L += ["", f"两种形态的排序 Kendall τ = {tau:.2f}（{len(models)} 个模型）。开思考形态内 Holm 后显著 "
          f"{len(sig_pairs)}/{len(pairs)} 对" + ("：" + "；".join(
              f"{short(a) if dd > 0 else short(b)} 高于 {short(b) if dd > 0 else short(a)} {abs(dd):.1f} 分（Holm p = {fmt_p(p)}）"
              for a, b, dd, p in sig_pairs) if sig_pairs else "") + "。", ""]

    # 题型、诊断分段、单 judge 口径
    types = sorted({typ[q] for q in ids})
    L += ["### 按题型与诊断题分段（只作描述）", "",
          "| 模型 | " + " | ".join(f"{TYPE_NAME[t]}（{sum(typ[q] == t for q in ids)} 题）关 → 开" for t in types)
          + " | 诊断根因段 关 → 开 | 诊断处置段 关 → 开 |", "| --- | " + " | ".join("---" for _ in types) + " | --- | --- |"]
    diag = [q for q in ids if typ[q] == "diagnosis"]
    for m in order:
        cells = []
        for t in types:
            k = [i for i, q in enumerate(ids) if typ[q] == t]
            cells.append(f"{X_off[m][k].mean():.1f} → {X_on[m][k].mean():.1f}")
        seg = []
        for key in ("root_cause", "action"):
            off_v = [float(off_pts[(m, q)][f"stage_{key}"]) for q in diag if off_pts[(m, q)].get(f"stage_{key}")]
            on_v = [x[4]["score"]["stages"][key] for q in diag for x in on[m][q]
                    if (x[4]["score"].get("stages") or {}).get(key) is not None]
            seg.append(f"{np.mean(off_v):.1f} → {np.mean(on_v):.1f}" if off_v and on_v else "—")
        L.append(f"| {short(m)} | " + " | ".join(cells) + f" | {seg[0]} | {seg[1]} |")
    off_h = {m: np.array([float(off[(m, q)]["main_total"]) for q in ids]) for m in models}
    off_s = {m: np.array([float(off[(m, q)]["second_total"]) for q in ids]) for m in models}
    on_h = {m: np.array([np.mean([x[2] for x in on[m][q]]) for q in ids]) for m in models}
    on_s = {m: np.array([np.mean([x[3] for x in on[m][q]]) for q in ids]) for m in models}
    L += ["", "### 稳健性：单个 judge 口径下的开 − 关（只作描述）", "",
          "| 模型 | 主口径 | Haiku 单独 | Sonnet 单独 |", "| --- | --- | --- | --- |"]
    for m in order:
        L.append(f"| {short(m)} | {res[m]['d']:+.1f} | {(on_h[m] - off_h[m]).mean():+.1f} | {(on_s[m] - off_s[m]).mean():+.1f} |")
    return L + [""], res


# ---------- 客观题 ----------

def objective_section():
    L = ["## 2. 客观题（150 题分层抽样，每题 1 次，orig 提示）", ""]
    if not (OBJ / "answers_on.csv").exists():
        return L + ["开思考客观题未完成，待跑。", ""], {}
    on = read_csv(OBJ / "answers_on.csv")
    off = with_aliases({(r["model"], r["id"]): r for r in read_csv(OBJ / "off_orig.csv")})
    sample = read_csv(ROOT / "data/processed/thinking_mcq_sample.csv")
    n_h = {st: sum(s["stratum"] == st for s in sample) for st in STRATUM_SIZE}
    total = sum(STRATUM_SIZE.values())
    by_model = defaultdict(dict)
    for r in on:
        by_model[r["model"]][r["id"]] = r
    models = [m for m in by_model if len(by_model[m]) == len(sample)]
    partial = {m: len(v) for m, v in by_model.items() if m not in models}
    if partial:
        L += ["未齐的模型（不进检验）：" + "，".join(f"{m} {k}/{len(sample)}" for m, k in partial.items()), ""]
    res = {}
    for m in models:
        d, w, strata = [], [], []
        for s in sample:
            d.append(int(by_model[m][s["id"]]["correct"]) - int(off[(m, s["id"])]["correct"]))
            w.append(STRATUM_SIZE[s["stratum"]] / total / n_h[s["stratum"]])
            strata.append(s["stratum"])
        d, w, strata = np.array(d, float), np.array(w), np.array(strata)
        est = float(d @ w) * 100
        # 分层 bootstrap：层内有放回重抽
        rng = rng_for(f"boot:obj:{m}")
        bs = np.zeros(B)
        for st in STRATUM_SIZE:
            idx = np.where(strata == st)[0]
            draw = idx[rng.integers(0, len(idx), size=(B, len(idx)))]
            bs += d[draw].mean(axis=1) * STRATUM_SIZE[st] / total
        cell = {}
        for st in STRATUM_SIZE:
            k = strata == st
            ids = [s["id"] for s in sample if s["stratum"] == st]
            cell[st] = (100 * np.mean([int(off[(m, q)]["correct"]) for q in ids]),
                        100 * np.mean([int(by_model[m][q]["correct"]) for q in ids]),
                        int((d[k] > 0).sum()), int((d[k] < 0).sum()))
        res[m] = {"est": est, "lo": np.percentile(bs, 2.5) * 100, "hi": np.percentile(bs, 97.5) * 100,
                  "p": signflip(d, f"obj:{m}", w), "cell": cell,
                  "nofmt": sum(1 for s in sample if not by_model[m][s["id"]]["pred"]),
                  "trunc": sum(1 for s in sample if by_model[m][s["id"]]["finish_reason"] == "length")}
    for m, a in zip(models, holm([res[m]["p"] for m in models])):
        res[m]["p_holm"] = a
    L += ["估计量 = 731 题上的正确率变化（开 − 关，百分点）= Σ 层权重 × 层内均值，层权重 = 天花板 440/731、其余 291/731；"
          "分层配对符号翻转置换检验（双侧，B = 10000），模型间 Holm；分层 bootstrap 95% CI。"
          "层内的「错→对 / 对→错」是逐题翻转数。抽不出答案记错。", "",
          "| 模型 | 天花板层 关 → 开（错→对 / 对→错） | 其余层 关 → 开（错→对 / 对→错） | 731 题加权变化（pt） | 95% CI | p | Holm p | 无答案字母 | 截断 |",
          "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for m in sorted(models, key=lambda x: -res[x]["est"]):
        r, c = res[m], res[m]["cell"]
        L.append(f"| {short(m)} | {c['ceiling'][0]:.0f} → {c['ceiling'][1]:.0f}（{c['ceiling'][2]} / {c['ceiling'][3]}） | "
                 f"{c['other'][0]:.0f} → {c['other'][1]:.0f}（{c['other'][2]} / {c['other'][3]}） | **{r['est']:+.1f}** | "
                 f"[{r['lo']:+.1f}, {r['hi']:+.1f}] | {fmt_p(r['p'])} | {fmt_p(r['p_holm'])}{' *' if r['p_holm'] < ALPHA else ''} | "
                 f"{r['nofmt']} | {r['trunc']} |")
    return L + [""], res


# ---------- 开销 ----------

def load_raw(model, mode):
    path = RAW / f"{model}__{mode}.jsonl"
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def usage_tokens(u):
    u = u or {}
    return (u.get("prompt_tokens") or 0, u.get("completion_tokens") or 0,
            (u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)


def cost_section(models_scn, models_obj):
    """每次调用的开销：场景题取 thinking_on / main_off 实际用到的那些调用，客观题取 150 题。"""
    L = ["## 3. 开销（每次调用；按原价，DeepSeek 按白天价）", ""]
    on_ids = {json.loads(x)["answer_id"] for x in ON_ANSWERS.read_text(encoding="utf-8").splitlines() if x.strip()} \
        if ON_ANSWERS.exists() else set()
    rows = []
    models = sorted(set(models_scn) | set(models_obj))
    for m in models:
        for mode in ("off", "on"):
            recs = [r for r in load_raw(m, mode) if r.get("ok")]
            if mode == "on":
                recs = [r for r in recs if f"{m}:on:{r['scenario_id']}:r{r['repeat']}" in on_ids]
            else:
                recs = [r for r in recs if r.get("system") == "v1" and r.get("max_tokens") == 4096 and r["repeat"] == 0]
            seen = {}
            for r in recs:
                seen[(r["scenario_id"], r["repeat"])] = r
            for r in seen.values():
                tin, tout, think = usage_tokens(r["usage"])
                rows.append({"model": m, "mode": mode, "scenario_id": r["scenario_id"], "repeat": r["repeat"],
                             "prompt_tokens": tin, "completion_tokens": tout, "reasoning_tokens": think,
                             "answer_chars": len(r["content"]), "ttfa_s": r.get("ttfa_s"), "latency_s": r.get("latency_s"),
                             "cost_cny": r.get("cost_cny"), "finish_reason": r.get("finish_reason")})
    if rows:
        write_csv(OUT_DIR / "scenario_calls.csv", rows)
    else:
        rows = read_csv(OUT_DIR / "scenario_calls.csv") if (OUT_DIR / "scenario_calls.csv").exists() else []
    med = lambda xs: statistics.median([float(x) for x in xs if x not in (None, "")]) if xs else float("nan")
    avg = lambda xs: statistics.mean([float(x) for x in xs if x not in (None, "")]) if xs else float("nan")
    L += ["场景题：", "", "| 模型 | 输出 token 关 → 开（其中思考） | 回答字数 关 → 开 | 首答案时延中位数（s）关 → 开 | 总时延中位数（s）关 → 开 | 每题花费（元）关 → 开 |",
          "| --- | --- | --- | --- | --- | --- |"]
    for m in models_scn:
        a = [r for r in rows if r["model"] == m and r["mode"] == "off"]
        b = [r for r in rows if r["model"] == m and r["mode"] == "on"]
        if not a or not b:
            continue
        L.append(f"| {short(m)} | {avg([r['completion_tokens'] for r in a]):.0f} → {avg([r['completion_tokens'] for r in b]):.0f}"
                 f"（{avg([r['reasoning_tokens'] for r in b]):.0f}） | {avg([r['answer_chars'] for r in a]):.0f} → "
                 f"{avg([r['answer_chars'] for r in b]):.0f} | {med([r['ttfa_s'] for r in a]):.1f} → {med([r['ttfa_s'] for r in b]):.1f} | "
                 f"{med([r['latency_s'] for r in a]):.1f} → {med([r['latency_s'] for r in b]):.1f} | "
                 f"{avg([r['cost_cny'] for r in a]):.4f} → {avg([r['cost_cny'] for r in b]):.4f} |")
    if (OBJ / "answers_on.csv").exists():
        on = read_csv(OBJ / "answers_on.csv")
        off = read_csv(OBJ / "off_orig.csv")
        sys.path.insert(0, str(ROOT / "scripts"))
        from thinking_pilot import PRICE  # noqa: E402
        L += ["", "客观题（150 题）：", "", "| 模型 | 输出 token 关 → 开（其中思考） | 总时延中位数（s）关 → 开 | 每题花费（元）关 → 开 |",
              "| --- | --- | --- | --- |"]
        for m in models_obj:
            a = [r for r in off if r["model"] == OFF_ALIAS.get(m, m)]  # 关思考取百炼那一行（见 OFF_ALIAS）
            b = [r for r in on if r["model"] == m]
            pi, po = PRICE[m]
            c_off = avg([(float(r["prompt_tokens"] or 0) * pi + float(r["completion_tokens"] or 0) * po) / 1e6 for r in a])
            L.append(f"| {short(m)} | {avg([r['completion_tokens'] for r in a]):.0f} → {avg([r['completion_tokens'] for r in b]):.0f}"
                     f"（{avg([r['reasoning_tokens'] for r in b]):.0f}） | {med([r['latency_s'] for r in a]):.1f} → "
                     f"{med([r['latency_s'] for r in b]):.1f} | {c_off:.5f} → {avg([r['cost_cny'] for r in b]):.4f} |")
    spent = sum(float(r["cost_cny"] or 0) for r in rows if r["mode"] == "on")
    if (OBJ / "answers_on.csv").exists():
        spent += sum(float(r["cost_cny"] or 0) for r in read_csv(OBJ / "answers_on.csv"))
    L += ["", f"本实验开思考一侧（实际用到的调用）按原价合计约 ¥{spent:.1f}（不含重试与冒烟；DeepSeek 夜间半价、代金券抵扣未计）。", ""]
    return L


def main():
    scns = {q["id"]: q for q in json.loads(SCENARIOS.read_text(encoding="utf-8"))}
    typ = {r["scenario_id"]: r["type"] for r in read_csv(SPLIT)}
    s_lines, s_res = scenario_section(scns, typ)
    o_lines, o_res = objective_section()
    c_lines = cost_section(list(s_res), list(o_res))
    L = ["# 思考模式对照（上线形态）", "",
         "由 `analysis/thinking_analysis.py` 生成，请勿手改。规则见 STATUS 决定日志（Oct 15 晚「思考对照预注册」，跑之前提交）。", "",
         "模型：qwen3.8-max-0902、deepseek-v4-pro-0813、glm-5.2、deepseek-v4.1-flash（这四个经百炼）、"
         "qwen3.8-flash（开思考经 OpenCode Go，模型 ID 记为 qwen3.8-flash-ocgo；关思考沿用百炼 `main_off`，"
         "见 STATUS 决定日志 Oct 15 晚：它开 − 关的差值含 Go 与百炼的部署差异，绝对分不与前四个直接比）。"
         "kimi-k3（输出价过高）、glm-5.3（只能开思考，思考过长，用户 Oct 15 去掉）、qwen3.7-plus（只能扣现金，余额不足，未跑）不在内，"
         "上线形态的比较只覆盖这 5 个模型。开思考采样参数取厂商推荐值（Qwen 温度 1.0 / top_p 0.95 / top_k 20，DeepSeek 1.0 / 1.0，"
         "GLM 1.0 / 0.95；来源为第三方部署文档，不是官方模型卡），max_tokens 16384；关思考一侧是横评结果（温度 0）。"
         "judge 只看最终答案，不看推理过程。", ""]
    L += s_lines + o_lines + c_lines
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    print(f"→ {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
