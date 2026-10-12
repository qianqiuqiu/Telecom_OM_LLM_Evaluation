"""收回 WorkBuddy（MiniMax-M3）复查结果：校验 ID 覆盖与格式，写入 votes，并在校准题上与默认模型比一致性。

输入：
  results/audit/answer_check_full/workbuddy/manifest.json        各块题目 ID（C1–C3 校准，D1–D3 待复查）
  results/audit/answer_check_full/workbuddy/raw/<块>_<inv>.txt   WorkBuddy 返回的原始文本（含 JSON 数组）
  results/audit/answer_check_full/items.json                     选项数（校验 correct_option 范围）
输出：
  data/processed/teleqna_answer_check_full_votes.csv     追加 kind=review、annotator=mm_inv1/mm_inv2 的行；
                                                         新增 model 列（重复运行会先删掉旧的 mm_ 行）
  results/audit/answer_check_full/minimax_evidence.csv   证据文字（不入库）
  reports/audit/teleqna_review_calibration_minimax.md    校准报告

校准口径：每题“有问题” = 两名复查者不都判 correct（与保留规则一致：两人都判 correct 才保留）。
MiniMax 两人的合并判定与默认模型两人的合并判定比二分类 Cohen kappa；≥ 0.6 才采用 D 块结果。

用法：uv run python scripts/ingest_workbuddy_review.py
"""

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WB = ROOT / "results/audit/answer_check_full/workbuddy"
VOTES = ROOT / "data/processed/teleqna_answer_check_full_votes.csv"
MODEL = "MiniMax-M3"
VERDICTS = {"correct", "wrong", "ambiguous", "unverifiable"}
KAPPA_MIN = 0.6
SIM_MAX = 0.4
num = lambda q: int(q.split()[-1])


def model_of(r):
    if r.get("model"):
        return r["model"]
    return "claude-default" if r["kind"] == "review" else "haiku"


def parse(path, expect, n_opts):
    """返回 (按 id 的判定, 问题列表)。"""
    text = path.read_text(encoding="utf-8")
    m = re.search(r"\[\s*\{.*\}\s*\]", text, re.S)
    if not m:
        return {}, [f"{path.name}: 找不到 JSON 数组"]
    out, errs = {}, []
    try:
        arr = json.loads(m.group(0), strict=False)  # 子模型常在字符串里留原始换行
    except json.JSONDecodeError as e:
        # 兜底：JSON 有小错（如漏引号）时逐条用正则取判定字段，证据尽量取
        arr = []
        for chunk in re.split(r'(?=\{\s*"id"\s*:)', text)[1:]:  # 按每条记录切块，块内各字段分别找
            f = lambda k, pat: (re.search(rf'"{k}"\s*:\s*{pat}', chunk) or [None, None])[1]
            arr.append({"id": f("id", r'"([^"]+)"'), "verdict": f("verdict", r'"(\w+)"') or "",
                        "correct_option": f("correct_option", r'(\d+)'),
                        "evidence": f("evidence", r'"((?:[^"\\]|\\.)*)') or "", "source": ""})
        errs.append(f"{path.name}: JSON 不合法（{e}），已用正则兜底提取 {len(arr)} 条（仅提示，不算缺失）")
    for v in arr:
        qid = re.sub(r"\s+", " ", str(v.get("id", ""))).strip()
        if qid not in expect:
            errs.append(f"{path.name}: 多出或抄错的 ID {qid!r}")
            continue
        if qid in out:
            errs.append(f"{path.name}: 重复 ID {qid}")
            continue
        verdict = str(v.get("verdict", "")).strip().lower()
        if verdict not in VERDICTS:
            errs.append(f"{path.name}: {qid} 判定非法 {verdict!r}")
            continue
        opt = v.get("correct_option")
        if verdict != "wrong":  # 只有 wrong 的 correct_option 参与决定
            opt = None
        elif opt is not None:
            try:
                opt = int(opt)
            except (TypeError, ValueError):
                errs.append(f"{path.name}: {qid} correct_option 非整数 {opt!r}")
                opt = None
            if opt is not None and not 1 <= opt <= n_opts[qid]:
                errs.append(f"{path.name}: {qid} correct_option 越界 {opt}")
                opt = None
        out[qid] = {"verdict": verdict, "correct_option": opt,
                    "evidence": str(v.get("evidence", "")), "source": str(v.get("source", ""))}
    missing = sorted(expect - set(out), key=num)
    if missing:
        errs.append(f"{path.name}: 缺 {len(missing)} 题 {missing}")
    return out, errs


def problem(verdicts):
    return not all(v == "correct" for v in verdicts)


def kappa(a, b):
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def main():
    manifest = json.loads((WB / "manifest.json").read_text(encoding="utf-8"))
    n_opts = {it["id"]: len(it["options"]) for it in json.loads(
        (ROOT / "results/audit/answer_check_full/items.json").read_text(encoding="utf-8"))}
    mm, errs, missing_files = defaultdict(dict), [], []
    for block, ids in manifest.items():
        for inv in ("inv1", "inv2"):
            p = WB / "raw" / f"{block}_{inv}.txt"
            if not p.exists():
                missing_files.append(p.stem)
                continue
            got, e = parse(p, set(ids), n_opts)
            errs += e
            for qid, v in got.items():
                mm[qid][f"mm_{inv}"] = v
        # 独立性检查：WorkBuddy 同一 worker 会沿用上一个任务的上下文，出现过 inv2 照抄或改写 inv1 的情况。
        # 独立运行的两份证据文字平均相似度约 0.27（C1/C2/D2）；超过 0.4 视为不独立，丢弃该块 inv2
        both_ev = [q for q in ids if len(mm.get(q, {})) == 2]
        sim = (sum(SequenceMatcher(None, mm[q]["mm_inv1"]["evidence"], mm[q]["mm_inv2"]["evidence"]).ratio()
                   for q in both_ev) / len(both_ev)) if both_ev else 0
        if sim > SIM_MAX:
            errs.append(f"{block}: inv1 与 inv2 证据平均相似度 {sim:.2f} > {SIM_MAX}，判为不独立，丢弃 inv2")
            missing_files.append(f"{block}_inv2")
            for q in ids:
                mm[q].pop("mm_inv2", None)
    print(f"已收回：{2 * len(manifest) - len(missing_files)}/{2 * len(manifest)}"
          + (f"；未收回 {missing_files}" if missing_files else ""))
    for e in errs:
        print("  问题：", e)

    with VOTES.open(encoding="utf-8") as f:
        old = [r for r in csv.DictReader(f) if not r["annotator"].startswith("mm_")]
    claude = defaultdict(dict)
    for r in old:
        r["model"] = model_of(r)
        if r["kind"] == "review" and r["model"] == "claude-default":
            claude[r["id"]][r["annotator"]] = r
    new = [{"id": q, "kind": "review", "annotator": ann, "choice": "", "confidence": "",
            "verdict": v["verdict"], "correct_option": v["correct_option"] or "", "model": MODEL}
           for q in sorted(mm, key=num) for ann, v in sorted(mm[q].items())]
    with VOTES.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "kind", "annotator", "choice", "confidence", "verdict",
                                          "correct_option", "model"])
        w.writeheader()
        w.writerows(old + new)
    with (ROOT / "results/audit/answer_check_full/minimax_evidence.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "annotator", "verdict", "correct_option", "evidence", "source"])
        for q in sorted(mm, key=num):
            for ann, v in sorted(mm[q].items()):
                w.writerow([q, ann, v["verdict"], v["correct_option"] or "", v["evidence"], v["source"]])
    print(f"写入 votes：MiniMax 判定 {len(new)} 条")

    # 校准：C 块中两名 MiniMax 与两名默认模型都齐全的题
    calib = [q for b, ids in manifest.items() if b.startswith("C") for q in ids]
    both = [q for q in calib if len(mm.get(q, {})) == 2 and len(claude[q]) == 2]
    if not both:
        print("校准题尚无完整结果")
        return
    cv = {q: [r["verdict"] for r in claude[q].values()] for q in both}
    mv = {q: [v["verdict"] for v in mm[q].values()] for q in both}
    c = [problem(cv[q]) for q in both]
    m = [problem(mv[q]) for q in both]
    k = kappa(c, m)
    per_inv = {inv: kappa(c, [mm[q][inv]["verdict"] != "correct" for q in both]) for inv in ("mm_inv1", "mm_inv2")}
    k_mm = kappa([mm[q]["mm_inv1"]["verdict"] != "correct" for q in both],
                 [mm[q]["mm_inv2"]["verdict"] != "correct" for q in both])
    tab = Counter(zip(c, m))

    def fix_of(votes):  # 两人都判 wrong 且选项一致 → 该选项，否则 None
        opts = {str(v["correct_option"] or "") for v in votes}
        return opts.pop() if all(v["verdict"] == "wrong" for v in votes) and len(opts) == 1 and "" not in opts else None

    c_fix = {q: fix_of(list(claude[q].values())) for q in both}
    m_fix = {q: fix_of(list(mm[q].values())) for q in both}
    n_cfix = sum(1 for q in both if c_fix[q])
    n_same = sum(1 for q in both if c_fix[q] and m_fix[q] == c_fix[q])
    # 最终决定（保留 / 改答案 / 剔除）三分类一致率
    decide = lambda verdicts, fix: "keep" if not problem(verdicts) else ("fix" if fix else "drop")
    agree3 = sum(decide(cv[q], c_fix[q]) == decide(mv[q], m_fix[q]) and c_fix[q] == m_fix[q] for q in both)
    dist = Counter(v for q in both for v in mv[q])
    adopt = k >= KAPPA_MIN
    lines = [
        "# 复查模型校准：MiniMax-M3 vs 默认模型",
        "",
        "由 `scripts/ingest_workbuddy_review.py` 生成，请勿手改。",
        "",
        f"校准题：默认模型已有两名复查者判定的 {len(calib)} 题，两边结果都齐全 {len(both)} 题。"
        "每题“有问题” = 两名复查者不都判 correct（与保留规则一致）。",
        "",
        "| | MiniMax 无问题 | MiniMax 有问题 |",
        "| --- | --- | --- |",
        f"| 默认模型无问题 | {tab[(False, False)]} | {tab[(False, True)]} |",
        f"| 默认模型有问题 | {tab[(True, False)]} | {tab[(True, True)]} |",
        "",
        f"- 合并判定二分类 kappa：**{k:.2f}**（门槛 {KAPPA_MIN}，{'达到 → 采用' if adopt else '未达到 → 不采用'}"
        " MiniMax 对待复查题的结果）",
        f"- 一致率 {sum(x == y for x, y in zip(c, m)) / len(both):.1%}；单名 MiniMax 复查者 vs 默认模型合并判定"
        f" kappa：inv1 {per_inv['mm_inv1']:.2f}、inv2 {per_inv['mm_inv2']:.2f}",
        f"- MiniMax 两次运行之间 kappa {k_mm:.2f}（同一模型两次运行，不是独立标注者）",
        f"- 最终决定（保留 / 改答案并选项一致 / 剔除）一致：{agree3}/{len(both)} = {agree3 / len(both):.1%}",
        f"- 默认模型判为改答案的 {n_cfix} 题中，MiniMax 给出相同改法：{n_same} 题",
        "- MiniMax 判定分布：" + "、".join(f"{a} {b}" for a, b in dist.most_common()),
        "",
    ]
    out = ROOT / "reports/audit/teleqna_review_calibration_minimax.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[6:]))
    if not adopt:
        sys.exit(f"kappa {k:.2f} < {KAPPA_MIN}：不采用 MiniMax 复查结果")


if __name__ == "__main__":
    main()
