"""全量答案核验（两阶段）汇总：得出每题最终状态，并生成答案修正 / 剔除决定。

输入：
  data/processed/teleqna_answer_check_full_votes.csv   Haiku 盲答、Haiku 粗筛与默认模型复查的判定（无证据文字）
  results/audit/answer_check_full/items.json           标准答案（不入库）
输出：
  data/processed/teleqna_answer_check_full_result.csv  每题最终状态（可入库）
  data/processed/teleqna_answer_decisions.csv          追加全量核验产生的决定（与抽样核验的人工决定合并）
  reports/audit/teleqna_answer_check_full.md

判定规则（沿用 Oct 11 的人工决定口径）：
  - Haiku 盲答与标准答案一致 → pass
  - 不一致，两名 Haiku 核查者都判 correct → pass
  - 其余进入默认模型复查：两人都判 correct → pass；
    两人都判 wrong 且给出相同的正确选项 → fix；其余 → drop
  - 盲答或核查缺失的题记为 incomplete，不做决定，需补跑

用法：uv run python analysis/answer_check_full.py
"""

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from statsmodels.stats.proportion import proportion_confint

ROOT = Path(__file__).resolve().parents[1]
DECISIONS = ROOT / "data/processed/teleqna_answer_decisions.csv"
DATE = "2026-10-11"


def main():
    items = {it["id"]: it for it in json.loads(
        (ROOT / "results/audit/answer_check_full/items.json").read_text(encoding="utf-8"))}
    solves, verdicts = {}, defaultdict(lambda: defaultdict(list))
    with (ROOT / "data/processed/teleqna_answer_check_full_votes.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["kind"] == "solve":
                solves[r["id"]] = int(r["choice"])
            else:
                verdicts[r["id"]][r["kind"]].append(r)

    rows = []
    for qid, it in items.items():
        gold = it["gold"]
        s = solves.get(qid)
        sc = verdicts[qid]["screen"]
        rv = verdicts[qid]["review"]
        fix = ""
        if s is None:
            status = "incomplete"
        elif s == gold:
            status = "pass"
        elif len(sc) >= 2 and all(v["verdict"] == "correct" for v in sc):
            status = "pass_screen"
        elif len(rv) < 2:
            status = "incomplete"
        elif all(v["verdict"] == "correct" for v in rv):
            status = "pass_review"
        elif all(v["verdict"] == "wrong" for v in rv) and len({v["correct_option"] for v in rv}) == 1 \
                and rv[0]["correct_option"]:
            status, fix = "fix", rv[0]["correct_option"]
        else:
            status = "drop"
        rows.append({"id": qid, "gold": gold, "haiku_choice": s or "", "status": status, "new_gold": fix,
                     "screen": "|".join(v["verdict"] for v in sc), "review": "|".join(v["verdict"] for v in rv)})
    rows.sort(key=lambda r: int(r["id"].split()[-1]))
    with (ROOT / "data/processed/teleqna_answer_check_full_result.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    # 合并进决定表：保留抽样核验的人工决定，替换此前由全量核验写入的行
    with DECISIONS.open(encoding="utf-8") as f:
        old = [r for r in csv.DictReader(f) if not r["reason"].startswith("全量核验")]
    new = [{"id": r["id"], "action": "fix" if r["status"] == "fix" else "drop", "new_gold": r["new_gold"],
            "reason": "全量核验：默认模型复查两人均判错且正确选项一致" if r["status"] == "fix"
            else "全量核验：默认模型复查判为错误无正确选项 / 有歧义 / 无法核实 / 意见不一",
            "decided_by": "规则（沿用 Oct 11 人工决定口径）", "date": DATE}
           for r in rows if r["status"] in ("fix", "drop")]
    with DECISIONS.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "action", "new_gold", "reason", "decided_by", "date"])
        w.writeheader()
        w.writerows(old + new)

    n = len(rows)
    st = Counter(r["status"] for r in rows)
    flagged = sum(1 for r in rows if r["status"] not in ("pass", "incomplete") or
                  (r["status"] == "incomplete" and r["haiku_choice"] != ""))
    reviewed = sum(1 for r in rows if r["review"])
    lo, hi = proportion_confint(st["fix"] + st["drop"], n, method="wilson")
    lines = [
        "# TeleQnA 全量答案核验（两阶段）",
        "",
        "由 `analysis/answer_check_full.py` 生成，请勿手改。",
        "",
        f"范围：审计后保留、未在抽样中核验过的 {n} 题。流程：Haiku 盲答 → 不一致的题由两名 Haiku 核查 → "
        "Haiku 未一致判对的题由两名默认模型复查定论。",
        "",
        "| 状态 | 题数 | 含义 |",
        "| --- | --- | --- |",
        f"| pass | {st['pass']} | Haiku 盲答与标准答案一致 |",
        f"| pass_screen | {st['pass_screen']} | 不一致，但两名 Haiku 核查者都判标准答案正确 |",
        f"| pass_review | {st['pass_review']} | 默认模型复查两人都判正确 |",
        f"| fix | {st['fix']} | 默认模型复查两人都判错且正确选项一致 → 改答案 |",
        f"| drop | {st['drop']} | 复查判为错误无正确选项、有歧义、无法核实或意见不一 → 剔除 |",
        f"| incomplete | {st['incomplete']} | 盲答或核查缺失，需补跑 |",
        "",
        f"- 进入 Haiku 核查：{flagged}，进入默认模型复查：{reviewed}",
        f"- 问题题（fix + drop）占比：{st['fix'] + st['drop']}/{n} = {(st['fix'] + st['drop']) / n:.1%}"
        f"（95% CI {lo:.1%}–{hi:.1%}）；对照：300 题抽样核验（两路盲答 + 默认模型核查）的估计为 12.3%",
        "- 局限：全量筛查只有 Haiku 一路盲答，Haiku 恰好选中错误标准答案的题会漏检",
        "",
    ]
    (ROOT / "reports/audit/teleqna_answer_check_full.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[6:]))


if __name__ == "__main__":
    main()
