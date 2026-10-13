"""天花板试跑分析（STATUS 第二节第 3 步）：便宜模型的场景题得分是否已经触顶。

判定规则在试跑前定下（Oct 13，见 STATUS 第五节），看完数据不再改：
  - 某题所有参与模型的得分都 >= 85，记为「触顶」（试跑为 qwen3.8-flash、deepseek-v4.1-flash，关思考）；
  - 触顶题超过 15 道（45 题的三分之一）→ 定稿前给触顶题加难度；不超过 → 照常定稿。
judge 是未经验证的 Haiku + 提示词 v1，结果只用来发现明显触顶，不作其他结论；
这批判定也不拿来改 judge 提示词（留出集的题也在其中）。

输入：results/judge/<run>/<judge 标签>.scores.csv（judge_scenarios.py 生成）、场景题文件
输出：终端摘要与 reports/scenarios/<run>.md（脚本生成，请勿手改）

用法：uv run python analysis/ceiling_pilot.py [--run ceiling_pilot] [--judge-tag claude_claude-haiku-5-5_medium]
"""
import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "data/scenarios/scenarios_draft.json"
REPORTS = ROOT / "reports/scenarios"

CEILING = 85      # 单题得分 >= 此值算高分
MAX_SATURATED = 15  # 触顶题超过此数 → 定稿前加难度
TYPE_NAME = {"diagnosis": "故障诊断", "consulting": "方案咨询", "kpi": "KPI 解读"}
BINS = [(0, 40, "0–39"), (40, 60, "40–59"), (60, 85, "60–84"), (85, 101, "85–100")]


def load_scores(path):
    """(source, scenario_id) -> 各次重复的行；judge 重复判定时取均值。"""
    by = defaultdict(list)
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            by[(r["source"], r["scenario_id"])].append(r)
    return by


def mean_of(rows, col):
    xs = [float(r[col]) for r in rows if r.get(col) not in (None, "")]
    return statistics.mean(xs) if xs else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="ceiling_pilot")
    ap.add_argument("--judge-tag", default="claude_claude-haiku-5-5_medium")
    ap.add_argument("--scenarios", type=Path, default=SCENARIOS)
    args = ap.parse_args()

    path = ROOT / "results/judge" / args.run / f"{args.judge_tag}.scores.csv"
    if not path.exists():
        raise SystemExit(f"找不到 {path.relative_to(ROOT)}，先用 judge_scenarios.py 判分")
    scns = {q["id"]: q for q in json.loads(args.scenarios.read_text(encoding="utf-8"))}
    rows = load_scores(path)
    sources = sorted({s for s, _ in rows})
    score = {k: mean_of(v, "total") for k, v in rows.items()}
    veto = {k: mean_of(v, "veto") for k, v in rows.items()}

    complete = [sid for sid in scns if all((s, sid) in score for s in sources)]
    missing = {s: [sid for sid in scns if (s, sid) not in score] for s in sources}
    saturated = [sid for sid in complete if min(score[(s, sid)] for s in sources) >= CEILING]

    L = [f"# 场景题天花板试跑（{args.run}）", "",
         "> 由 `analysis/ceiling_pilot.py` 生成，请勿手改。", "",
         f"judge：`{args.judge_tag}`（未经验证，只用来发现明显触顶）；被测：{', '.join(f'`{s}`' for s in sources)}。", "",
         (f"**事先定的规则（Oct 13）**：某题所有被测模型得分都 ≥ {CEILING} 记为触顶；"
          f"触顶题超过 {MAX_SATURATED} 道（三分之一）则定稿前给触顶题加难度，否则照常定稿。"), ""]

    n_missing = sum(len(v) for v in missing.values())
    if n_missing:
        L += [(f"**判分不全**：{n_missing} 个（模型, 题）没有分数，下面只按 {len(complete)} 道判全的题计算，"
               "结论暂不成立，补判后重跑本脚本。"), ""]
        for s, ids in missing.items():
            if ids:
                L.append(f"- `{s}` 缺 {len(ids)} 题：{', '.join(ids)}")
        L.append("")
    decision = "定稿前给触顶题加难度" if len(saturated) > MAX_SATURATED else "照常定稿"
    L += ["## 结论", "",
          f"触顶 **{len(saturated)}/{len(complete)}** 题 → **{decision}**" + ("（判分不全，暂不成立）" if n_missing else "") + "。", ""]
    if saturated:
        L.append("触顶题：" + "、".join(f"{sid}（{scns[sid]['title']}）" for sid in saturated))
        L.append("")

    head = ["被测", "题数", "均值", "中位数", "最低", "最高", *(f"{name} 分" for _, _, name in BINS), "一票否决",
            *(f"{TYPE_NAME[t]}均值" for t in TYPE_NAME), "诊断题根因 / 处置"]
    L += ["## 各模型得分分布", "", "| " + " | ".join(head) + " |", "|" + " --- |" * len(head)]
    for s in sources:
        xs = [score[(s, sid)] for sid in complete]
        if not xs:
            continue
        bins = [sum(a <= x < b for x in xs) for a, b, _ in BINS]
        by_type = [[score[(s, sid)] for sid in complete if scns[sid]["type"] == t] for t in TYPE_NAME]
        diag = [rows[(s, sid)] for sid in complete if scns[sid]["type"] == "diagnosis"]
        rc = [mean_of(r, "stage_root_cause") for r in diag]
        act = [mean_of(r, "stage_action") for r in diag]
        rc, act = [x for x in rc if x is not None], [x for x in act if x is not None]
        stage = f"{statistics.mean(rc):.1f} / {statistics.mean(act):.1f}" if rc and act else "—"
        L.append(f"| `{s}` | {len(xs)} | {statistics.mean(xs):.1f} | {statistics.median(xs):.1f} | {min(xs):.0f} | {max(xs):.0f} | "
                 + " | ".join(str(b) for b in bins)
                 + f" | {sum(1 for sid in complete if veto[(s, sid)])} | "
                 + " | ".join(f"{statistics.mean(v):.1f}" if v else "—" for v in by_type) + f" | {stage} |")
    L += ["", "分档列为落在该分数段的题数；根因 / 处置为诊断题两段的得分率（扣分前）。", ""]

    L += ["## 逐题得分（按最低分从高到低）", "",
          "| 题 | 题型 | 难度 | 标题 | " + " | ".join(f"`{s}`" for s in sources) + " | 触顶 |",
          "|" + " --- |" * (5 + len(sources))]
    for sid in sorted(complete, key=lambda i: -min(score[(s, i)] for s in sources)):
        q = scns[sid]
        cells = [f"{score[(s, sid)]:.0f}" + ("（否决）" if veto[(s, sid)] else "") for s in sources]
        L.append(f"| {sid} | {TYPE_NAME.get(q['type'], q['type'])} | {q['difficulty']} | {q['title']} | "
                 + " | ".join(cells) + f" | {'是' if sid in saturated else ''} |")

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"{args.run}.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"触顶 {len(saturated)}/{len(complete)} 题 → {decision}" + ("（判分不全，暂不成立）" if n_missing else ""))
    for s in sources:
        xs = [score[(s, sid)] for sid in complete]
        if xs:
            print(f"  {s:<28} 均值 {statistics.mean(xs):.1f}，中位数 {statistics.median(xs):.1f}，"
                  f">= {CEILING} 的 {sum(x >= CEILING for x in xs)} 题")
    print(f"报告：{out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
