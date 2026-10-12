"""收回 Haiku 复查结果（Oct 12 应用户要求，代替未通过校准的 MiniMax-M3）：校验 ID 覆盖，写入 votes，
在 108 道校准题上与默认模型比一致性，并列出 Haiku 对 109 道待复查题会给出的决定。

输入：
  results/audit/answer_check_full/haiku_review/workflow_output.json   workflow 返回值（含证据，不入库）
  results/audit/answer_check_full/haiku_review/chunks.json            各块题目 ID（chunk_calib_* 为校准题）
  results/audit/answer_check_full/items.json                          选项数
输出：
  data/processed/teleqna_answer_check_full_votes.csv   追加 kind=review、annotator=hk_inv1/hk_inv2、model=haiku-5.5
  results/audit/answer_check_full/haiku_evidence.csv   证据文字（不入库）
  reports/audit/teleqna_review_calibration_haiku.md    校准报告与待复查题决定分布

口径同 scripts/ingest_workbuddy_review.py：每题“有问题” = 两名复查者不都判 correct；二分类 Cohen kappa。
本脚本不自动采用 Haiku 结论（是否采用、保留多少由用户看结果后决定）。

用法：uv run python scripts/ingest_haiku_review.py
"""

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from ingest_workbuddy_review import kappa, problem

ROOT = Path(__file__).resolve().parents[1]
HR = ROOT / "results/audit/answer_check_full/haiku_review"
VOTES = ROOT / "data/processed/teleqna_answer_check_full_votes.csv"
MODEL = "haiku-5.5"
num = lambda q: int(q.split()[-1])


def fix_of(votes):
    """两人都判 wrong 且给出相同的正确选项 → 该选项，否则 None。"""
    opts = {str(v["correct_option"] or "") for v in votes}
    if all(v["verdict"] == "wrong" for v in votes) and len(opts) == 1 and "" not in opts:
        return opts.pop()
    return None


def decide(votes):
    if not problem([v["verdict"] for v in votes]):
        return "keep"
    return "fix" if fix_of(votes) else "drop"


def main():
    chunks = json.loads((HR / "chunks.json").read_text(encoding="utf-8"))
    n_opts = {it["id"]: len(it["options"]) for it in json.loads(
        (ROOT / "results/audit/answer_check_full/items.json").read_text(encoding="utf-8"))}
    out = json.loads((HR / "workflow_output.json").read_text(encoding="utf-8"))
    hk, errs = defaultdict(dict), []
    for r in out["results"]:
        if not r:
            continue
        if not r.get("ok"):
            errs.append(f"{r['file']}:{r['inv']} 缺 {r.get('missing')} 多 {r.get('extra')}")
        for v in r["verdicts"]:
            opt = v.get("correct_option")
            if v["verdict"] != "wrong" or opt is None or not 1 <= int(opt) <= n_opts[v["id"]]:
                opt = None
            hk[v["id"]][f"hk_{r['inv']}"] = {**v, "correct_option": opt}
    calib = [q for c in chunks if c["file"].startswith("chunk_calib") for q in c["ids"]]
    pend = [q for c in chunks if c["file"].startswith("chunk_pend") for q in c["ids"]]
    incomplete = [q for q in calib + pend if len(hk.get(q, {})) < 2]
    print(f"Haiku 判定：{sum(len(v) for v in hk.values())} 条；两名复查者不齐的题 {len(incomplete)}")
    for e in errs:
        print("  问题：", e)

    with VOTES.open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if not r["annotator"].startswith("hk_")]
    claude = defaultdict(list)
    for r in rows:
        if r["kind"] == "review" and r.get("model", "claude-default") == "claude-default":
            claude[r["id"]].append(r)
    new = [{"id": q, "kind": "review", "annotator": a, "choice": "", "confidence": "", "verdict": v["verdict"],
            "correct_option": v["correct_option"] or "", "model": MODEL}
           for q in sorted(hk, key=num) for a, v in sorted(hk[q].items())]
    with VOTES.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows + new)
    with (ROOT / "results/audit/answer_check_full/haiku_evidence.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "annotator", "verdict", "correct_option", "evidence", "source"])
        for q in sorted(hk, key=num):
            for a, v in sorted(hk[q].items()):
                w.writerow([q, a, v["verdict"], v["correct_option"] or "", v["evidence"], v["source"]])

    both = [q for q in calib if len(hk.get(q, {})) == 2 and len(claude[q]) == 2]
    hv = {q: list(hk[q].values()) for q in both}
    c = [problem([r["verdict"] for r in claude[q]]) for q in both]
    m = [problem([v["verdict"] for v in hv[q]]) for q in both]
    k = kappa(c, m)
    k_inv = {a: kappa(c, [hk[q][a]["verdict"] != "correct" for q in both]) for a in ("hk_inv1", "hk_inv2")}
    k_self = kappa([hk[q]["hk_inv1"]["verdict"] != "correct" for q in both],
                   [hk[q]["hk_inv2"]["verdict"] != "correct" for q in both])
    tab = Counter(zip(c, m))
    c_dec = {q: decide(claude[q]) for q in both}
    h_dec = {q: decide(hv[q]) for q in both}
    agree3 = sum(c_dec[q] == h_dec[q] and (c_dec[q] != "fix" or fix_of(claude[q]) == fix_of(hv[q])) for q in both)
    conf = Counter((c_dec[q], h_dec[q]) for q in both)
    # Haiku 判“无问题”的题里，默认模型也判无问题的比例（若只保留 Haiku 判无问题的题，误留率多少）
    h_keep = [q for q in both if h_dec[q] == "keep"]
    keep_ok = sum(c_dec[q] == "keep" for q in h_keep)
    pend_ok = [q for q in pend if len(hk.get(q, {})) == 2]
    p_dec = Counter(decide(list(hk[q].values())) for q in pend_ok)
    dist = Counter(v["verdict"] for q in both for v in hv[q])
    lines = [
        "# 复查模型校准：Haiku 5.5 vs 默认模型",
        "",
        "由 `scripts/ingest_haiku_review.py` 生成，请勿手改。复查提示词与默认模型复查相同（每块 5 题、两名复查者、可联网）。",
        "",
        f"校准题：默认模型已有两名复查者判定的 108 题，两边结果都齐全 {len(both)} 题。",
        "每题“有问题” = 两名复查者不都判 correct（与保留规则一致）。",
        "",
        "| | Haiku 无问题 | Haiku 有问题 |",
        "| --- | --- | --- |",
        f"| 默认模型无问题 | {tab[(False, False)]} | {tab[(False, True)]} |",
        f"| 默认模型有问题 | {tab[(True, False)]} | {tab[(True, True)]} |",
        "",
        f"- 合并判定二分类 kappa：**{k:.2f}**（MiniMax-M3 为 0.29；门槛 0.6）",
        f"- 一致率 {sum(x == y for x, y in zip(c, m)) / len(both):.1%}；单名 Haiku 复查者 vs 默认模型合并判定 kappa："
        f"inv1 {k_inv['hk_inv1']:.2f}、inv2 {k_inv['hk_inv2']:.2f}；Haiku 两名复查者之间 kappa {k_self:.2f}",
        f"- 最终决定（保留 / 改答案且选项一致 / 剔除）一致：{agree3}/{len(both)} = {agree3 / len(both):.1%}",
        f"- Haiku 判“保留”的 {len(h_keep)} 题中，默认模型也判保留 {keep_ok} 题"
        f"（精确率 {keep_ok / max(len(h_keep), 1):.0%}）；默认模型判保留共 {sum(v == 'keep' for v in c_dec.values())} 题",
        "- 决定交叉表（默认模型 → Haiku）：" + "、".join(f"{a}→{b} {n}" for (a, b), n in sorted(conf.items())),
        "- Haiku 判定分布（校准题）：" + "、".join(f"{a} {b}" for a, b in dist.most_common()),
        "",
        f"## 待复查 {len(pend)} 题按 Haiku 结论的决定（未采用，供用户决定）",
        "",
        f"两名复查者齐全 {len(pend_ok)} 题：" + "、".join(f"{a} {b}" for a, b in p_dec.most_common()),
        "",
    ]
    (ROOT / "reports/audit/teleqna_review_calibration_haiku.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[6:]))


if __name__ == "__main__":
    main()
