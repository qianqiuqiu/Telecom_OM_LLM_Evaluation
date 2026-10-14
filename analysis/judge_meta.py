"""judge 元评测：用构造真值探针检验 judge（Spec「Judge 元评测与提示词迭代」）。

读 build_judge_probes.py 生成的探针（带应得判定 expect）和 judge_scenarios.py 的判定记录，
对一个 run 目录下的每个 judge 分别报：

- 删要点检出：drop:Pk 中 Pk 判为非 covered 的比例（宽松，主指标）；判 missed 的比例（严格，仅参考）。
  人工抽查（spotcheck_drop.csv，Oct 14）：调试集 30 条 drop 探针里 0 条仍完整写到要点，11 条残留部分内容
  （映射漏标 4、要点之间本身重叠 5、只剩零星痕迹 2），这些探针上 judge 判 partial 是合理的，所以严格口径
  的真值约三分之一不成立。另报人工确认删净（human = N）的子集上的严格口径，样本小，只作参考。
  提示词迭代不以严格口径为目标，否则会把 judge 调成无视回答里残留的内容。
- 错误根因：wrong_root 中根因要点判为非 covered 的比例
- 未改动要点保持：应得 covered 的要点判 covered 的比例（严格）/ 判为非 missed 的比例（宽松）。
  full 探针的应得判定来自映射模型，不完全是构造出来的，单列报告
- 拒答：empty 中要点全部 missed 的比例
- 高危：risk_add 中目标高危操作被触发的比例（检出率）；risk_neg 与其他不含高危建议的探针中
  任一高危被触发的比例（误报率，后者检验 judge 是否只认关键词）
- 长度不变性：pad 与 full 的逐要点判定一致率、总分差
- 摘录核对：judge 给的原文摘录在回答里找不到的比例（拼接摘录逐段核对，按当前规则重算）
- 自身稳定性（有重复判定时）：同一回答多次判定的逐要点一致率、总分标准差、一票否决翻转率
比例都附 Wilson 95% 区间。只统计缓存键与当前提示词 / 题目 / 回答一致的记录。

用法：
  uv run python analysis/judge_meta.py --run probes_v1 --split debug
输出：reports/judge/<run>_<split>.md（脚本生成，请勿手改）
"""
import argparse
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from judge_scenarios import (OUT, PROMPTS, SCENARIOS, cache_key, check_evidence, latest_ok,  # noqa: E402
                             load_records, load_split)

PROBES = ROOT / "data/scenarios/judge_probes/probes.jsonl"
SPOTCHECK = ROOT / "data/scenarios/judge_probes/spotcheck_drop.csv"
REPORTS = ROOT / "reports/judge"


def wilson(k, n, z=1.96):
    if n == 0:
        return "—"
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return f"{p:.1%}（{k}/{n}，[{max(0, c - h):.1%}, {min(1, c + h):.1%}]）"


def load_spotcheck():
    """drop 探针人工抽查：answer_id -> human（Y 仍写到 / N 删净 / ? 残留部分）。没填的不返回。"""
    if not SPOTCHECK.exists():
        return {}
    with SPOTCHECK.open(encoding="utf-8") as f:
        return {r["answer_id"]: r["human"].strip() for r in csv.DictReader(f) if r["human"].strip()}


def kind_of(answer_id):
    return answer_id.split("|")[1].split(":")[0]


def metrics(probes, scns, recs_by_answer, human=None):
    """recs_by_answer: answer_id -> [记录（各重复）]。主指标只用第 0 次判定。human：load_spotcheck() 的结果。"""
    human = human or {}
    c = defaultdict(lambda: [0, 0])  # 指标 -> [命中, 总数]

    def hit(name, ok):
        c[name][0] += int(ok)
        c[name][1] += 1

    first = {aid: rs[0] for aid, rs in recs_by_answer.items() if rs}
    pad_pairs = []
    for p in probes:
        r = first.get(p["answer_id"])
        if r is None:
            continue
        kind = kind_of(p["answer_id"])
        v = {x["id"]: x["verdict"] for x in r["parsed"]["points"]}
        hr = {str(x["index"]): x["triggered"] for x in r["parsed"]["high_risk"]}
        exp = p["expect"]
        if kind == "drop" and human.get(p["answer_id"]) != "Y":  # 人工判仍写到的探针真值不成立，不计
            pid = p["answer_id"].split("drop:")[1]
            hit("drop_lenient", v[pid] != "covered")
            hit("drop_strict", v[pid] == "missed")
            if human.get(p["answer_id"]) == "N":
                hit("drop_strict_clean", v[pid] == "missed")
        if kind == "wrong_root":
            for pid in (q["id"] for q in scns[p["scenario_id"]]["rubric_points"] if q["stage"] == "root_cause"):
                hit("wrong_root_lenient", v[pid] != "covered")
        if kind == "empty":
            hit("empty_all_missed", all(x == "missed" for x in v.values()))
        if kind in ("drop", "wrong_root", "risk_neg", "pad", "full"):
            for pid, e in exp["points"].items():
                if e == "covered":
                    name = "keep_full" if kind == "full" else "keep_constructed"
                    hit(f"{name}_strict", v[pid] == "covered")
                    hit(f"{name}_lenient", v[pid] != "missed")
                elif e == "missed" and kind == "full":
                    hit("full_unmapped_not_covered", v[pid] != "covered")
        if kind == "risk_add":
            j = next(k for k, t in exp["high_risk"].items() if t)
            hit("risk_recall", hr[j])
            hit("risk_add_other_fp", not any(t for k, t in hr.items() if k != j))
        elif kind == "risk_neg":
            hit("risk_neg_fp", any(hr.values()))
        else:
            hit("risk_other_fp", any(hr.values()))
        if kind == "pad":
            base = first.get(f"{p['scenario_id']}|full")
            if base:
                bv = {x["id"]: x["verdict"] for x in base["parsed"]["points"]}
                for pid in v:
                    hit("pad_point_agree", v[pid] == bv[pid])
                pad_pairs.append(r["score"]["total"] - base["score"]["total"])
        ev = check_evidence(r["parsed"], p["text"])  # 按当前核对规则重算
        c["evidence_missing"][0] += len(ev["missing"])
        c["evidence_missing"][1] += ev["checked"]
    return c, pad_pairs


def stability(recs_by_answer):
    agree = [0, 0]
    sds, veto_flip = [], [0, 0]
    for rs in recs_by_answer.values():
        if len(rs) < 2:
            continue
        vs = [{x["id"]: x["verdict"] for x in r["parsed"]["points"]} for r in rs]
        for pid in vs[0]:
            agree[0] += int(len({v[pid] for v in vs}) == 1)
            agree[1] += 1
        sds.append(statistics.pstdev(r["score"]["total"] for r in rs))
        veto_flip[0] += int(len({r["score"]["veto"] for r in rs}) > 1)
        veto_flip[1] += 1
    return agree, sds, veto_flip


ROWS = [
    ("drop_lenient", "删要点检出（判非 covered，主指标）", "高"),
    ("drop_strict", "删要点检出（判 missed，仅参考：约 1/3 探针残留部分内容）", "高"),
    ("drop_strict_clean", "删要点检出（判 missed，人工确认删净的抽查子集）", "高"),
    ("wrong_root_lenient", "错误根因：根因要点判非 covered", "高"),
    ("keep_constructed_strict", "未改动要点保持 covered（构造探针）", "高"),
    ("keep_constructed_lenient", "未改动要点判非 missed（构造探针）", "高"),
    ("keep_full_strict", "参考答案原文：映射到的要点判 covered", "高"),
    ("keep_full_lenient", "参考答案原文：映射到的要点判非 missed", "高"),
    ("full_unmapped_not_covered", "参考答案原文：没写到的要点判非 covered", "高"),
    ("empty_all_missed", "拒答：要点全部 missed", "高"),
    ("risk_recall", "高危建议检出", "高"),
    ("risk_add_other_fp", "高危建议探针：其他高危未误报", "高"),
    ("risk_neg_fp", "「不可取」提醒被误判为高危", "低"),
    ("risk_other_fp", "无高危内容的探针被误判为高危", "低"),
    ("pad_point_agree", "注水加长：逐要点判定与原文一致", "高"),
    ("evidence_missing", "摘录在回答里找不到", "低"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--split", choices=["debug", "holdout", "all"], default="all")
    ap.add_argument("--probes", type=Path, default=PROBES)
    ap.add_argument("--scenarios", type=Path, default=SCENARIOS)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    scns = {q["id"]: q for q in json.loads(args.scenarios.read_text(encoding="utf-8"))}
    probes = [json.loads(line) for line in args.probes.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.split != "all":
        split = load_split()
        probes = [p for p in probes if split.get(p["scenario_id"]) == args.split]
    probes = [p for p in probes if p["scenario_id"] in scns]

    human = load_spotcheck()
    logs = sorted((args.out / args.run).glob("*.jsonl"))
    if not logs:
        raise SystemExit(f"{args.out / args.run} 下没有判定记录")
    L = [f"# judge 元评测：构造真值探针（{args.run}，{args.split}）", "",
         "由 `analysis/judge_meta.py` 生成，请勿手改。比例附 Wilson 95% 区间；主指标只用每个回答的第 1 次判定。", "",
         f"探针 {len(probes)} 个，来自 {len({p['scenario_id'] for p in probes})} 道题。"
         "「方向」为高表示越高越好，为低表示越低越好。", ""]
    if human:
        hc = {k: sum(1 for v in human.values() if v == k) for k in ("N", "?", "Y")}
        L += [f"删要点检出以「判非 covered」为主指标。人工抽查 {len(human)} 条 drop 探针：删净 {hc['N']}、"
              f"残留部分内容 {hc['?']}、仍完整写到 {hc['Y']}（`spotcheck_drop.csv`），"
              "残留部分内容的探针上判 partial 也合理，所以「判 missed」只作参考。", ""]
    for log in logs:
        recs = load_records(log)
        meta = next((r for r in reversed(recs) if r.get("ok")), None)
        if meta is None:
            L += [f"## {log.stem}", "", "没有成功的判定记录。", ""]
            continue
        system = (PROMPTS / f"judge_{meta['prompt']}.md").read_text(encoding="utf-8")
        keys = {p["answer_id"]: cache_key(system, meta["judge"], meta["effort"], scns[p["scenario_id"]], p["text"])
                for p in probes}
        ok = latest_ok([r for r in recs if keys.get(r["answer_id"]) == r["key"]])
        by_answer = defaultdict(list)
        for (aid, k, _), r in sorted(ok.items(), key=lambda kv: (kv[0][0], kv[0][1])):
            by_answer[aid].append(r)
        n_fail = sum(1 for r in recs if keys.get(r["answer_id"]) == r.get("key") and not r.get("ok"))
        c, pad = metrics(probes, scns, by_answer, human)
        agree, sds, flips = stability(by_answer)
        L += [f"## {meta['judge']}（effort {meta['effort']}，提示词 {meta['prompt']} / {meta['prompt_sha']}）", "",
              f"已判 {len(by_answer)}/{len(probes)} 个探针，失败记录 {n_fail} 条。", "",
              "| 指标 | 方向 | 结果 |", "| --- | --- | --- |"]
        L += [f"| {label} | {d} | {wilson(*c[name])} |" for name, label, d in ROWS if c[name][1]]
        if pad:
            L.append(f"| 注水加长：总分差（pad − full）均值 | 接近 0 | {statistics.mean(pad):+.1f}（n={len(pad)}） |")
        if agree[1]:
            L += ["", "**自身稳定性**（同一回答重复判定）", "",
                  f"- 逐要点判定完全一致：{wilson(*agree)}",
                  f"- 总分标准差：均值 {statistics.mean(sds):.1f}，最大 {max(sds):.1f}（{len(sds)} 个回答）",
                  f"- 一票否决翻转：{wilson(*flips)}"]
        L.append("")
    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"{args.run}_{args.split}.md"
    out.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    print(f"→ {out}")


if __name__ == "__main__":
    main()
