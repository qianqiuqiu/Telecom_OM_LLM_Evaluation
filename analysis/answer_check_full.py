"""全量答案核验（两阶段）汇总：得出每题最终状态，并生成答案修正 / 剔除决定。

输入：
  data/processed/teleqna_answer_check_full_votes.csv   Haiku 盲答、Haiku 粗筛与强模型复查的判定（无证据文字）
  data/processed/teleqna_relevance.csv                 运维相关度（只对相关度 ≥ 2 的测试子集下结论）
  results/audit/answer_check_full/items.json           标准答案（不入库）
输出：
  data/processed/teleqna_answer_check_full_result.csv  每题最终状态（可入库）
  data/processed/teleqna_answer_decisions.csv          追加全量核验产生的决定（与抽样核验的人工决定合并）
  reports/audit/teleqna_answer_check_full.md

判定规则（沿用 Oct 11 的人工决定口径）：
  - Haiku 盲答与标准答案一致 → pass
  - 不一致，两名 Haiku 核查者都判 correct → pass
  - 其余进入强模型复查：两人都判 correct → pass；
    两人都判 wrong 且给出相同的正确选项 → fix；其余 → drop
  - 复查判定来源：默认模型（Claude）两人。默认模型未复查的题（额度耗尽后剩下的子集内 109 题）：
    MiniMax-M3 与 Haiku 5.5 都未通过校准（kappa 0.29 / 0.21，门槛 0.6），按 Oct 12 用户决定改用投票规则——
    两名 Haiku + 两名 MiniMax 共 4 人中 ≥ 3 人判 correct → pass_vote，否则 → drop_vote；不采用其改答案建议。
    该规则在 108 道校准题上的保留精确率 81%（scripts/ingest_haiku_review.py 报告）
  - 只对测试子集（相关度 ≥ 2）内的题写入决定；子集外的题不再复查，
    缺复查的记为 out_of_scope，已有结论的只做统计、不写入决定
  - 子集内盲答或复查缺失的题记为 incomplete，不做决定，需补跑

用法：uv run python analysis/answer_check_full.py
"""

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from statsmodels.stats.proportion import proportion_confint

ROOT = Path(__file__).resolve().parents[1]
DECISIONS = ROOT / "data/processed/teleqna_answer_decisions.csv"
DATE = "2026-10-12"
VOTE_MODELS = ("haiku-5.5", "MiniMax-M3")
VOTE_MIN = 3


def main():
    items = {it["id"]: it for it in json.loads(
        (ROOT / "results/audit/answer_check_full/items.json").read_text(encoding="utf-8"))}
    with (ROOT / "data/processed/teleqna_relevance.csv").open(encoding="utf-8") as f:
        subset = {r["id"] for r in csv.DictReader(f) if int(r["relevance"]) >= 2}
    solves, verdicts = {}, defaultdict(lambda: defaultdict(list))
    with (ROOT / "data/processed/teleqna_answer_check_full_votes.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["kind"] == "solve":
                solves[r["id"]] = int(r["choice"])
            else:
                verdicts[r["id"]][r["kind"]].append(r)

    def pick_review(rv):
        """返回 (复查判定, 来源)：默认模型两人优先；否则 Haiku 与 MiniMax 各两人齐全时返回 4 票（来源 vote）。"""
        by_model = defaultdict(list)
        for v in rv:
            by_model[v.get("model") or "claude-default"].append(v)
        if len(by_model["claude-default"]) >= 2:
            return by_model["claude-default"], "claude-default"
        if all(len(by_model[m]) >= 2 for m in VOTE_MODELS):
            return [v for m in VOTE_MODELS for v in by_model[m]], "vote"
        return [], ""

    rows = []
    for qid, it in items.items():
        gold = it["gold"]
        s = solves.get(qid)
        sc = verdicts[qid]["screen"]
        rv, reviewer = pick_review(verdicts[qid]["review"])
        in_subset = qid in subset
        fix = ""
        if s is None:
            status = "incomplete"
        elif s == gold:
            status = "pass"
        elif len(sc) >= 2 and all(v["verdict"] == "correct" for v in sc):
            status = "pass_screen"
        elif len(rv) < 2:
            status = "incomplete" if in_subset else "out_of_scope"
        elif reviewer == "vote":
            status = "pass_vote" if sum(v["verdict"] == "correct" for v in rv) >= VOTE_MIN else "drop_vote"
        elif all(v["verdict"] == "correct" for v in rv):
            status = "pass_review"
        elif all(v["verdict"] == "wrong" for v in rv) and len({v["correct_option"] for v in rv}) == 1 \
                and rv[0]["correct_option"]:
            status, fix = "fix", rv[0]["correct_option"]
        else:
            status = "drop"
        rows.append({"id": qid, "in_subset": in_subset, "gold": gold, "haiku_choice": s or "", "status": status,
                     "new_gold": fix, "screen": "|".join(v["verdict"] for v in sc),
                     "review": "|".join(v["verdict"] for v in rv), "reviewer": reviewer})
    rows.sort(key=lambda r: int(r["id"].split()[-1]))
    with (ROOT / "data/processed/teleqna_answer_check_full_result.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    # 合并进决定表：保留抽样核验的人工决定，替换此前由全量核验写入的行；只写子集内的题
    with DECISIONS.open(encoding="utf-8") as f:
        old = [r for r in csv.DictReader(f) if not r["reason"].startswith("全量核验")]
    reasons = {"fix": "全量核验：claude-default 复查两人均判错且正确选项一致",
               "drop": "全量核验：claude-default 复查判为错误无正确选项 / 有歧义 / 无法核实 / 意见不一",
               "drop_vote": f"全量核验：Haiku 5.5 ×2 + MiniMax-M3 ×2 复查中判 correct 不足 {VOTE_MIN} 人"}
    new = [{"id": r["id"], "action": "fix" if r["status"] == "fix" else "drop", "new_gold": r["new_gold"],
            "reason": reasons[r["status"]],
            "decided_by": "规则（Qianqiu Oct 12 选定投票规则）" if r["status"] == "drop_vote"
            else "规则（沿用 Oct 11 人工决定口径）", "date": DATE}
           for r in rows if r["in_subset"] and r["status"] in reasons]
    with DECISIONS.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "action", "new_gold", "reason", "decided_by", "date"])
        w.writeheader()
        w.writerows(old + new)

    sub = [r for r in rows if r["in_subset"]]
    n = len(sub)
    st = Counter(r["status"] for r in sub)
    st_all = Counter(r["status"] for r in rows)
    flagged = sum(1 for r in sub if r["screen"])
    by_rev = Counter(r["reviewer"] for r in sub if r["reviewer"])
    bad = st["fix"] + st["drop"] + st["drop_vote"]
    lo, hi = proportion_confint(bad, n, method="wilson") if n else (0, 0)
    lines = [
        "# TeleQnA 全量答案核验（两阶段）",
        "",
        "由 `analysis/answer_check_full.py` 生成，请勿手改。",
        "",
        f"范围：审计后保留、未在抽样中核验过的 {len(rows)} 题；按 Oct 12 决定只对其中运维相关（相关度 ≥ 2）的 "
        f"{n} 题下结论。流程：Haiku 盲答 → 不一致的题由两名 Haiku 核查 → Haiku 未一致判对的题由两名强模型复查定论。",
        "",
        "| 状态 | 子集内题数 | 含义 |",
        "| --- | --- | --- |",
        f"| pass | {st['pass']} | Haiku 盲答与标准答案一致 |",
        f"| pass_screen | {st['pass_screen']} | 不一致，但两名 Haiku 核查者都判标准答案正确 |",
        f"| pass_review | {st['pass_review']} | 强模型复查两人都判正确 |",
        f"| fix | {st['fix']} | 强模型复查两人都判错且正确选项一致 → 改答案 |",
        f"| drop | {st['drop']} | 复查判为错误无正确选项、有歧义、无法核实或意见不一 → 剔除 |",
        f"| pass_vote | {st['pass_vote']} | 默认模型未复查；Haiku ×2 + MiniMax ×2 中 ≥ {VOTE_MIN} 人判正确 → 保留 |",
        f"| drop_vote | {st['drop_vote']} | 默认模型未复查；判正确不足 {VOTE_MIN} 人 → 剔除 |",
        f"| incomplete | {st['incomplete']} | 盲答或复查缺失，需补跑 |",
        "",
        f"- 子集内进入 Haiku 核查 {flagged} 题，进入复查 {sum(by_rev.values())} 题："
        + "、".join(f"{k} {v}" for k, v in by_rev.most_common()),
        f"- 子集内问题题（fix + drop + drop_vote）占比：{bad}/{n} = {bad / max(n, 1):.1%}"
        f"（95% CI {lo:.1%}–{hi:.1%}）；对照：300 题抽样核验的估计为 12.3%",
        f"- 子集外 {len(rows) - n} 题不写入决定；其中 {st_all['out_of_scope']} 题按决定不再复查",
        "- 复查来源：默认模型（Claude）；其未覆盖的题用 Haiku 5.5 ×2 + MiniMax-M3 ×2 投票。两者单独与默认模型的"
        "一致性都未达标（kappa 0.21 / 0.29），见 `teleqna_review_calibration_haiku.md`、"
        "`teleqna_review_calibration_minimax.md`；投票规则在校准题上的保留精确率 81%，即 pass_vote 中约有 1/5 "
        "可能是默认模型会判有问题的题",
        "- 局限：全量筛查只有 Haiku 一路盲答，Haiku 恰好选中错误标准答案的题会漏检",
        "",
    ]
    (ROOT / "reports/audit/teleqna_answer_check_full.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[6:]))


if __name__ == "__main__":
    main()
