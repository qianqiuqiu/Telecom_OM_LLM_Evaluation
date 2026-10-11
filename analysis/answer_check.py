"""TeleQnA 答案核验：汇总盲答筛查与深度核查，估计标准答案错误率。

输入：
  data/processed/teleqna_answer_check_sample.csv   抽样题、标准答案、Qwen 盲答
  data/processed/teleqna_answer_check_votes.csv    Claude 盲答与核查者判定（kind = solve / verdict），不含证据文字
  results/audit/answer_check/verdict_evidence.csv  核查证据与来源（可能引用题目片段，不入库）
  results/audit/answer_check/items.json            题目原文（只用于生成人工复核清单）
输出：
  data/processed/teleqna_answer_check_result.csv   每题最终状态（无原文，可入库）
  reports/audit/teleqna_answer_check.md            可报告的数字（无原文）
  results/audit/answer_check/review.md             人工复核清单（含原文，不入库）

判定规则（事先写定）：
  - 两路盲答都与标准答案一致、且不是矛盾题 → 筛查通过，视为正确
  - 进入核查的题：两名核查者都判 wrong → 疑似错误；都判 correct → 正确；
    其余（ambiguous / unverifiable / 两人意见不一）→ 待人工复核
  - 错误率只在随机抽样的 300 题上估计；矛盾题单独报告

用法：uv run python analysis/answer_check.py
"""

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from statsmodels.stats.proportion import proportion_confint

ROOT = Path(__file__).resolve().parents[1]


def wilson(k, n):
    lo, hi = proportion_confint(k, n, alpha=0.05, method="wilson")
    return f"{k}/{n} = {k / n:.1%}（95% CI {lo:.1%}–{hi:.1%}）"


def main():
    with (ROOT / "data/processed/teleqna_answer_check_sample.csv").open(encoding="utf-8") as f:
        sample = {r["id"]: r for r in csv.DictReader(f)}
    solves, verdicts = {}, defaultdict(list)
    with (ROOT / "data/processed/teleqna_answer_check_votes.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["kind"] == "solve":
                solves[r["id"]] = r
            else:
                verdicts[r["id"]].append(r)
    # 核查证据含题目片段，存于不入库的 results/ 下，只用于生成人工复核清单
    evidence = {}
    epath = ROOT / "results/audit/answer_check/verdict_evidence.csv"
    if epath.exists():
        with epath.open(encoding="utf-8") as f:
            evidence = {(r["id"], r["annotator"]): r for r in csv.DictReader(f)}
    for vs in verdicts.values():
        for v in vs:
            e = evidence.get((v["id"], v["annotator"]), {})
            v["evidence"], v["source"] = e.get("evidence", ""), e.get("source", "")
    items = {it["id"]: it for it in json.loads(
        (ROOT / "results/audit/answer_check/items.json").read_text(encoding="utf-8"))}

    rows = []
    for qid, s in sample.items():
        gold = int(s["gold"])
        qwen = int(s["qwen_choice"]) if s["qwen_choice"] else None
        claude = int(solves[qid]["choice"]) if qid in solves else None
        flagged = (claude is not None and claude != gold) or (qwen is not None and qwen != gold) \
            or s["source"] == "conflict"
        vs = verdicts.get(qid, [])
        labels = [v["verdict"] for v in vs]
        if not flagged:
            status = "screen_pass"
        elif len(labels) < 2:
            status = "missing_verdict"
        elif all(l == "wrong" for l in labels):
            status = "suspect_wrong"
        elif all(l == "correct" for l in labels):
            status = "correct"
        else:
            status = "needs_review"
        fixes = {v["correct_option"] for v in vs if v["verdict"] == "wrong" and v["correct_option"]}
        rows.append({"id": qid, "category": s["category"], "source": s["source"], "gold": gold,
                     "qwen_choice": qwen or "", "claude_choice": claude or "",
                     "flagged": flagged, "verdicts": "|".join(labels), "status": status,
                     "proposed_fix": "|".join(sorted(fixes))})

    with (ROOT / "data/processed/teleqna_answer_check_result.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: int(r["id"].split()[-1])))

    rnd = [r for r in rows if r["source"] == "random"]
    n = len(rnd)
    st = Counter(r["status"] for r in rnd)
    qwen_ans = [r for r in rnd if r["qwen_choice"] != ""]
    claude_ans = [r for r in rnd if r["claude_choice"] != ""]
    both = [r for r in rnd if r["qwen_choice"] != "" and r["claude_choice"] != ""]
    cat_rows = []
    for c in sorted({r["category"] for r in rnd}):
        cr = [r for r in rnd if r["category"] == c]
        cat_rows.append(f"| {c} | {len(cr)} | {sum(r['status'] == 'suspect_wrong' for r in cr)} | "
                        f"{sum(r['status'] == 'needs_review' for r in cr)} |")
    conflict = [r for r in rows if r["source"] == "conflict"]

    lines = [
        "# TeleQnA 答案核验",
        "",
        "由 `analysis/answer_check.py` 生成，请勿手改。",
        "",
        "## 方法",
        "",
        f"- 抽样：审计后保留的题中按类别分层随机抽 {n} 题；另加近重复审计中答案互相矛盾的题 {len(conflict)} 道（单独报告，不计入错误率）。",
        "- 盲答筛查：两个来自不同厂商的模型只看题干与选项作答——`qwen3.8-2.4t-a95b`（因成本只跑了部分题）与 Claude 子 agent。任一与标准答案不一致即进入核查。",
        "- 深度核查：两名 Claude 子 agent 独立核查，可查阅 3GPP / IEEE / ETSI 原文，判为 correct / wrong / ambiguous / unverifiable。",
        "- 局限：两路盲答都与一个错误的标准答案一致时会漏检，错误率是下界；核查者不是人工，“疑似错误”需人工确认。",
        "",
        "## 盲答筛查",
        "",
        f"- Qwen 盲答覆盖 {len(qwen_ans)}/{n} 题，与标准答案一致 {sum(r['qwen_choice'] == r['gold'] for r in qwen_ans)} 题",
        f"- Claude 盲答覆盖 {len(claude_ans)}/{n} 题，与标准答案一致 {sum(r['claude_choice'] == r['gold'] for r in claude_ans)} 题",
        f"- 两路都覆盖的 {len(both)} 题中，两路答案相同 {sum(r['qwen_choice'] == r['claude_choice'] for r in both)} 题",
        f"- 进入核查：{sum(r['flagged'] for r in rnd)}/{n} 题",
        "",
        "## 错误率（随机抽样部分）",
        "",
        "| 状态 | 题数 |",
        "| --- | --- |",
        *[f"| {k} | {st.get(k, 0)} |" for k in
          ["screen_pass", "correct", "suspect_wrong", "needs_review", "missing_verdict"]],
        "",
        f"- 疑似错误率（两名核查者都判错）：{wilson(st.get('suspect_wrong', 0), n)}",
        f"- 含待复核的上界：{wilson(st.get('suspect_wrong', 0) + st.get('needs_review', 0), n)}",
        "",
        "| 类别 | 抽样题数 | 疑似错误 | 待复核 |",
        "| --- | --- | --- | --- |",
        *cat_rows,
        "",
        "## 答案矛盾题",
        "",
        "| 题目 | 标准答案 | 核查结果 | 建议改为 |",
        "| --- | --- | --- | --- |",
        *[f"| {r['id']} | {r['gold']} | {r['verdicts'] or '—'} | {r['proposed_fix'] or '—'} |" for r in conflict],
        "",
    ]
    (ROOT / "reports/audit/teleqna_answer_check.md").write_text("\n".join(lines), encoding="utf-8")

    review = [r for r in rows if r["status"] in ("suspect_wrong", "needs_review", "missing_verdict")]
    out = ["# 人工复核清单（含原文，不入库）", "",
           "逐题看核查证据，在“你的结论”处填 correct / wrong / ambiguous。", ""]
    for r in sorted(review, key=lambda r: (r["status"], int(r["id"].split()[-1]))):
        it = items[r["id"]]
        out += [f"## {r['id']} · {r['status']} · {r['category']}", "", it["question"], ""]
        out += [f"{i + 1}. {o}{'  ← 标准答案' if i + 1 == r['gold'] else ''}" for i, o in enumerate(it["options"])]
        out += ["", f"盲答：Qwen {r['qwen_choice'] or '未跑'}，Claude {r['claude_choice'] or '—'}", ""]
        for v in verdicts.get(r["id"], []):
            out += [f"- {v['annotator']}：**{v['verdict']}**"
                    f"{'（应为 ' + v['correct_option'] + '）' if v['correct_option'] else ''} — {v['evidence']}"
                    f"（来源：{v['source']}）"]
        out += ["", "你的结论：", ""]
    (ROOT / "results/audit/answer_check/review.md").write_text("\n".join(out), encoding="utf-8")
    print(f"随机 {n} 题：{dict(st)}；复核清单 {len(review)} 题 → results/audit/answer_check/review.md")


if __name__ == "__main__":
    main()
