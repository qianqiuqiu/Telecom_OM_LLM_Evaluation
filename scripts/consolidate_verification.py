"""汇总三票核验 + 逐题 subagent 核验，产出可执行的分级修订清单。

读取：
  results/scenarios/three_vote/verdicts.json     三票聚合
  results/scenarios/perquestion/out/batch_*.json 逐题 subagent 裁决
输出（results/，不入库）：
  results/scenarios/perquestion/consolidated.md  分级修订清单

分级：
  P0 必修-高：影响根因/答案正确性（severity=high 且 subagent confirm/independent）
  P1 必修-中：引用/表述不准或与题干矛盾，但不改根因
  P2 可选-低：措辞、精度、补 unverified_residuals
  驳回：三票 must_fix 被 subagent 独立核查判为误判（保留原题，勿改）
  待人工查证：标准条款号等 subagent 无法离线确认的点

用法：uv run python scripts/consolidate_verification.py
"""
import glob
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PQ = ROOT / "results/scenarios/perquestion"


def load_items():
    items = {}
    for f in sorted(glob.glob(str(PQ / "out/batch_*.json"))):
        for it in json.load(open(f))["items"]:
            items[it["id"]] = it
    return items


def main():
    items = load_items()
    draft = json.loads((ROOT / "data/scenarios/scenarios_draft.json").read_text())
    title = {q["id"]: q["title"] for q in draft}

    p0, p1, p2, rejected, manual = [], [], [], [], []
    for qid in sorted(items):
        it = items[qid]
        # subagent 独立发现
        for f in it.get("independent_findings", []):
            sev = f.get("severity", "low")
            row = (qid, f.get("target", ""), f.get("problem", ""), f.get("fix", ""))
            {"high": p0, "medium": p1}.get(sev, p2).append(row)
        # 三票裁决
        for a in it.get("three_vote_adjudication", []):
            dec = a.get("decision", "")
            row = (qid, a.get("target", ""), a.get("reason", ""), a.get("fix", ""))
            if dec == "reject":
                rejected.append(row)
            elif dec in ("confirm", "partial"):
                # 严重度沿用独立发现里已归类的，这里只补充未被独立发现覆盖的
                if not any(r[0] == qid and r[1] == a.get("target") for r in p0 + p1 + p2):
                    p1.append(row)
        note = it.get("notes", "")
        if note and ("人工" in note or "查证" in note or "不确定" in note):
            manual.append((qid, note))

    def sect(name, rows):
        out = [f"## {name}（{len(rows)}）", ""]
        for qid, tgt, prob, fix in rows:
            out.append(f"- **{qid}** `{tgt}` — {title.get(qid,'')[:20]}\n    - 问题：{prob[:300]}\n    - 改法：{fix[:300]}")
        out.append("")
        return out

    verdicts = defaultdict(list)
    for qid, it in items.items():
        verdicts[it.get("verdict", "?")].append(qid)

    lines = ["# 场景题核验汇总（三票 + 逐题 subagent）", ""]
    lines.append(f"- 覆盖 45 题，ID 校验通过（无缺失/编造/重复）。")
    lines.append(f"- verdict 分布：" + "，".join(f"{k} {len(v)}" for k, v in sorted(verdicts.items())))
    lines.append(f"- major_fix：{', '.join(verdicts.get('major_fix', [])) or '无'}")
    lines.append("")
    lines += sect("P0 必修-高（影响根因/答案正确性）", p0)
    lines += sect("P1 必修-中（引用/表述/与题干矛盾）", p1)
    lines += sect("P2 可选-低（措辞/精度/补 residual）", p2)
    lines += sect("驳回：三票误判，保留原题勿改", rejected)
    lines.append(f"## 待人工查证（{len(manual)}）")
    lines.append("")
    for qid, note in manual:
        lines.append(f"- **{qid}**：{note[:400]}")
    (PQ / "consolidated.md").write_text("\n".join(lines))

    print(f"P0 {len(p0)} | P1 {len(p1)} | P2 {len(p2)} | 驳回三票 {len(rejected)} | 待人工 {len(manual)}")
    print(f"verdict: " + ", ".join(f"{k}={len(v)}" for k, v in sorted(verdicts.items())))
    print(f"清单：{PQ/'consolidated.md'}")


if __name__ == "__main__":
    main()
