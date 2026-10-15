"""干扰项质量抽查（Spec「TeleQnA 审计」第 3 项）：抽查明显错得离谱或与正确答案重叠的选项。

三部分：
1. 机械线索（全部 731 题，规则计算）：「最长选项就是正确答案」「正确答案与题干词重合最多」的比例，
   与随机水平 1/k 比较；按天花板题（35 次判定全对）与其余题分开报。
2. 选项复用（审计时发现的 72 对「选项集合完全相同、但并非重复」的题对）：多少对落在测试集里、
   两题正确答案是否相同、复用题在横评里的全对比例。
3. 人工式标注抽样（Claude 子 agent，两名独立标注者，盲于分层与横评结果）：
   天花板题 50 + 其余题 50（种子 20261015），另加测试集里属于选项复用对的题。
   每个错误选项标 plausible / eliminable / overlaps_correct；每题标「不靠领域知识能否排除到只剩正确答案」
   与「正确答案是否有问题」。两人一致才计入，分歧单列。

用法：
  uv run python analysis/distractor_audit.py prepare --out <目录>   # 生成抽样与标注批次（含原文，放 scratchpad，不入库）
  uv run python analysis/distractor_audit.py report                  # 读标注 → reports/audit/teleqna_distractors.md

标注结果：data/processed/teleqna_distractor_labels.csv（只有 ID 与标签）；
标注者的简短理由在 results/audit/distractors/labels_raw.jsonl。
"""
import argparse
import csv
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))
sys.path.insert(0, str(ROOT / "scripts"))
from objective_analysis import SUBSETS, load_predictions  # noqa: E402
from audit_teleqna import INDEX_REF_RE, POSITION_REF_RE, jaccard, load_items, load_labels, norm, shingles  # noqa: E402

DATA = ROOT / "results/evalscope_data/teleqna_ops/orig_val.jsonl"
SUBSET_CSV = ROOT / "data/processed/teleqna_test_subset.csv"
MODELS = ROOT / "configs/models.yaml"
LABELS = ROOT / "data/processed/teleqna_distractor_labels.csv"
RAW = ROOT / "results/audit/distractors/labels_raw.jsonl"
SAMPLE = ROOT / "data/processed/teleqna_distractor_sample.csv"
OUT = ROOT / "reports/audit/teleqna_distractors.md"
SEED = 20261015
N_PER_STRATUM = 50
BATCH = 10
LETTERS = "ABCDE"
STOP = set("the a an of to in on for and or is are be by with as at from that which this what when how does do "
           "can it its into than not no".split())


def load_mcq():
    return {d["id"]: d for d in (json.loads(l) for l in DATA.open(encoding="utf-8"))}


def all_correct():
    """每题 7 模型 × 5 子集共 35 次判定的正确次数。"""
    import yaml
    models = [m["id"] for m in yaml.safe_load(MODELS.read_text(encoding="utf-8"))["main"]]
    n = Counter()
    for m in models:
        p = load_predictions(m)
        for s in SUBSETS:
            for q, r in p[s].items():
                n[q] += r["correct"]
    return n, 7 * len(SUBSETS)


def reused_pairs():
    """审计报告里的「选项集合完全相同、但并非重复」的题对（与 scripts/audit_teleqna.py 同一口径）。"""
    items = load_items()
    by_id = {it["id"]: it for it in items}
    sh = {it["id"]: shingles(it["stem"]) for it in items}
    labels = load_labels(by_id, sh)
    out = []
    for l in labels:
        if l["options_jaccard"] == 1.0 and l["relation"] != "duplicate":
            a, b = by_id[l["a"]], by_id[l["b"]]
            out.append({"a": l["a"], "b": l["b"], "relation": l["relation"],
                        "same_gold": norm(a["answer_text"]) == norm(b["answer_text"])})
    return out


def words(s):
    return [w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOP]


def options(d):
    return [(k, d[k]) for k in LETTERS if d.get(k)]


def cues(d):
    """机械线索：正确答案是否为唯一最长选项；是否为与题干词重合最多的唯一选项。"""
    opts = [(k, v) for k, v in options(d) if not (POSITION_REF_RE.match(v) or INDEX_REF_RE.match(v))]
    if len(opts) < 2 or d["answer"] not in dict(opts):
        return None
    ln = {k: len(v) for k, v in opts}
    stem = set(words(d["question"]))
    ov = {k: len(stem & set(words(v))) for k, v in opts}
    top_len = max(ln.values())
    top_ov = max(ov.values())
    return {"k": len(opts),
            "longest": ln[d["answer"]] == top_len and list(ln.values()).count(top_len) == 1,
            "overlap": ov[d["answer"]] == top_ov and top_ov > 0 and list(ov.values()).count(top_ov) == 1}


# ---------- prepare ----------

def prepare(out_dir):
    mcq = load_mcq()
    n, total = all_correct()
    ids = list(mcq)
    ceiling = sorted(q for q in ids if n[q] == total)
    rest = sorted(q for q in ids if n[q] < total)
    rng = random.Random(SEED)
    pick = {q: "ceiling" for q in rng.sample(ceiling, N_PER_STRATUM)}
    pick.update({q: "rest" for q in rng.sample(rest, N_PER_STRATUM)})
    pairs = reused_pairs()
    for p in pairs:
        for q in (p["a"], p["b"]):
            if q in mcq and q not in pick:
                pick[q] = "reused"
    order = sorted(pick)
    rng.shuffle(order)  # 打乱后分批，批次里混着各层，标注者看不出分层
    with SAMPLE.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "stratum", "correct_of_35"])
        for q in sorted(pick, key=lambda q: int(q.split()[-1])):
            w.writerow([q, pick[q], int(n[q])])
    out_dir.mkdir(parents=True, exist_ok=True)
    batches = [order[i:i + BATCH] for i in range(0, len(order), BATCH)]
    for i, b in enumerate(batches):
        items = [{"id": q, "question": mcq[q]["question"], "options": dict(options(mcq[q])),
                  "gold": mcq[q]["answer"]} for q in b]
        (out_dir / f"batch_{i:02d}.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"抽样 {len(pick)} 题（{Counter(pick.values())}），{len(batches)} 批 → {out_dir}；分层表 {SAMPLE.relative_to(ROOT)}")


# ---------- report ----------

def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (c - h, c + h)


def pct(k, n):
    lo, hi = wilson(k, n)
    return f"{k}/{n}（{100 * k / n:.1f}%，[{100 * lo:.0f}%, {100 * hi:.0f}%]）" if n else "—"


def kappa(a, b):
    labs = sorted(set(a) | set(b))
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[l] * cb[l] for l in labs) / (n * n)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def report():
    mcq = load_mcq()
    n, total = all_correct()
    lines = ["# TeleQnA 审计：干扰项质量抽查", "",
             "由 `analysis/distractor_audit.py` 生成，请勿手改。范围：客观题测试集 731 题。"
             "天花板题 = 7 模型 × 5 子集共 35 次判定全对（440 题）。", ""]

    # 1. 机械线索
    lines += ["## 1. 机械线索（全部 731 题，规则计算）", "",
              "去掉「以上都 / 都不」与编号引用类选项后计算；随机水平按每题剩余选项数 k 取 1/k 的均值。"
              "「唯一最长」与「唯一词重合最多」出现并列时记为否。", "",
              "| 分组 | 题数 | 正确答案是唯一最长选项 | 随机水平 | 正确答案与题干词重合唯一最多 | 随机水平 |",
              "| --- | --- | --- | --- | --- | --- |"]
    groups = {"全部": list(mcq), "天花板题": [q for q in mcq if n[q] == total],
              "其余题": [q for q in mcq if n[q] < total]}
    for g, qs in groups.items():
        cs = [c for c in (cues(mcq[q]) for q in qs) if c]
        chance = sum(1 / c["k"] for c in cs) / len(cs)
        lines.append(f"| {g} | {len(cs)} | {pct(sum(c['longest'] for c in cs), len(cs))} | {100 * chance:.1f}% "
                     f"| {pct(sum(c['overlap'] for c in cs), len(cs))} | {100 * chance:.1f}% |")
    lines += ["", "随机水平是上限的粗略参照：唯一最长 / 唯一重合最多本身要求无并列，真实随机水平略低于 1/k。", ""]

    # 2. 选项复用
    pairs = reused_pairs()
    in_test = [p for p in pairs if p["a"] in mcq or p["b"] in mcq]
    both = [p for p in pairs if p["a"] in mcq and p["b"] in mcq]
    reused_ids = sorted({q for p in pairs for q in (p["a"], p["b"]) if q in mcq}, key=lambda q: int(q.split()[-1]))
    lines += ["## 2. 选项复用（审计中「选项集合完全相同、但并非重复」的题对）", "",
              f"- 题对共 {len(pairs)} 对（裁决关系：{dict(Counter(p['relation'] for p in pairs))}）；"
              f"两题正确答案相同 {sum(p['same_gold'] for p in pairs)} 对、不同 {sum(not p['same_gold'] for p in pairs)} 对。",
              f"- 至少一题在测试集里的 {len(in_test)} 对，两题都在的 {len(both)} 对；涉及测试集题目 {len(reused_ids)} 道。",
              f"- 这些题在横评里的天花板比例：{pct(sum(n[q] == total for q in reused_ids), len(reused_ids))}；"
              f"测试集整体为 {pct(len(groups['天花板题']), len(mcq))}。", ""]

    # 3. 标注
    if not LABELS.exists():
        lines += ["## 3. 标注抽样", "", "（尚无标注结果）"]
        OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return
    sample = {r["id"]: r for r in csv.DictReader(SAMPLE.open(encoding="utf-8"))}
    lab = defaultdict(dict)
    for r in csv.DictReader(LABELS.open(encoding="utf-8")):
        lab[r["id"]][r["annotator"]] = r
    annot = sorted({a for v in lab.values() for a in v})
    missing = [q for q in sample if len(lab.get(q, {})) < 2]
    if missing:
        raise SystemExit(f"标注不全（每题需两名标注者）：{missing[:10]} 等 {len(missing)} 题")
    a1, a2 = annot[:2]

    def opt_labels(r):
        return json.loads(r["option_labels"])

    # 逐选项一致性
    xa, xb = [], []
    for q in sample:
        la, lb = opt_labels(lab[q][a1]), opt_labels(lab[q][a2])
        for k in sorted(set(la) & set(lb)):
            xa.append(la[k])
            xb.append(lb[k])
    ea = [lab[q][a1]["eliminable_to_gold"] for q in sample]
    eb = [lab[q][a2]["eliminable_to_gold"] for q in sample]
    ga = [lab[q][a1]["gold_issue"] for q in sample]
    gb = [lab[q][a2]["gold_issue"] for q in sample]
    lines += ["## 3. 标注抽样", "",
              f"抽样 {len(sample)} 题：天花板题 {N_PER_STRATUM}、其余题 {N_PER_STRATUM}（种子 {SEED}），"
              f"另加测试集里属于选项复用对的题 {sum(r['stratum'] == 'reused' for r in sample.values())} 道。"
              "两名标注者（Claude 子 agent，默认模型，彼此独立）看到题干、选项与标准答案，看不到分层与横评结果。", "",
              "标签定义：", "",
              "- 选项级：`plausible` 需要领域知识才能排除；`eliminable` 不靠通信知识、只读题干就能排除"
              "（答非所问、实体类型不对、自相矛盾、明显荒谬）；`overlaps_correct` 与正确答案意思重叠或也可算对。",
              "- 题级：`eliminable_to_gold` 不靠领域知识，凭题干措辞与选项线索就能排除到只剩正确答案；"
              "`gold_issue` 标准答案不是明显的最佳答案（有歧义、另有选项同样对或更对、答案有误）。", "",
              "### 标注者一致性", "",
              f"- 选项级标签（{len(xa)} 个错误选项）：一致 {sum(x == y for x, y in zip(xa, xb))}/{len(xa)}"
              f"（{100 * sum(x == y for x, y in zip(xa, xb)) / len(xa):.1f}%），Cohen kappa {kappa(xa, xb):.2f}",
              f"- `eliminable_to_gold`：一致 {sum(x == y for x, y in zip(ea, eb))}/{len(ea)}，kappa {kappa(ea, eb):.2f}",
              f"- `gold_issue`：一致 {sum(x == y for x, y in zip(ga, gb))}/{len(ga)}，kappa {kappa(ga, gb):.2f}", "",
              "下表只计两人一致的判定；分歧数单列。", "",
              "| 分层 | 题数 | 可排除到只剩正确答案 | 分歧 | 标准答案有问题 | 分歧 | 至少一个 eliminable 选项 | 至少一个 overlaps_correct 选项 |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for st, name in (("ceiling", "天花板题"), ("rest", "其余题"), ("reused", "选项复用题（额外）")):
        qs = [q for q, r in sample.items() if r["stratum"] == st]
        if not qs:
            continue
        agree_e = [q for q in qs if lab[q][a1]["eliminable_to_gold"] == lab[q][a2]["eliminable_to_gold"]]
        agree_g = [q for q in qs if lab[q][a1]["gold_issue"] == lab[q][a2]["gold_issue"]]
        both_lab = lambda q, v: any(opt_labels(lab[q][a1]).get(k) == v == opt_labels(lab[q][a2]).get(k)
                                    for k in opt_labels(lab[q][a1]))
        lines.append(
            f"| {name} | {len(qs)} | {pct(sum(lab[q][a1]['eliminable_to_gold'] == 'yes' for q in agree_e), len(qs))} "
            f"| {len(qs) - len(agree_e)} | {pct(sum(lab[q][a1]['gold_issue'] == 'yes' for q in agree_g), len(qs))} "
            f"| {len(qs) - len(agree_g)} | {pct(sum(both_lab(q, 'eliminable') for q in qs), len(qs))} "
            f"| {pct(sum(both_lab(q, 'overlaps_correct') for q in qs), len(qs))} |")
    lines += ["", "比例的分母是该层全部题数（分歧题不计入分子），所以是两人都认定的下限。", ""]

    flagged = [q for q in sample if lab[q][a1]["gold_issue"] == "yes" == lab[q][a2]["gold_issue"]]
    lines += ["### 两人都认为标准答案有问题的题", ""]
    lines += [f"- {q}（{sample[q]['stratum']}，横评 35 次判定对 {sample[q]['correct_of_35']} 次）" for q in flagged] or ["（无）"]
    lines += ["", "这些题只列出、不剔除：测试集已冻结，剔除会改变横评口径；如要处理，另出勘误版并重算。"]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"→ {OUT.relative_to(ROOT)}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--out", type=Path, required=True)
    sub.add_parser("report")
    args = ap.parse_args()
    if args.cmd == "prepare":
        prepare(args.out)
    else:
        report()


if __name__ == "__main__":
    main()
