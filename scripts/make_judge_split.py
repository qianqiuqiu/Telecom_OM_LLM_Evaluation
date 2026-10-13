"""judge 调试集 / 留出集划分：按题划分（不按回答），题型内分层，固定随机种子。

按题划分是为了不让同一道题的 rubric 同时出现在两边：judge 提示词只在调试集上改，
留出集只在提示词锁定后用一次，报最终数字。题目 ID 稳定，划分一经提交不再重抽；
场景题收尾时删掉的题直接从两边消失，不重新划分。

输出：data/scenarios/judge_split.csv（scenario_id, type, split）
用法：uv run python scripts/make_judge_split.py
"""
import csv
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "data/scenarios/scenarios_draft.json"
OUT = ROOT / "data/scenarios/judge_split.csv"
SEED = 20261013


def main():
    if OUT.exists():
        raise SystemExit(f"{OUT} 已存在：划分一经提交不再重抽")
    qs = json.loads(SCENARIOS.read_text(encoding="utf-8"))
    rng = random.Random(SEED)
    rows = []
    for t in sorted({q["type"] for q in qs}):
        ids = sorted(q["id"] for q in qs if q["type"] == t)
        rng.shuffle(ids)
        half = len(ids) // 2  # 奇数题时留出集多一题
        rows += [(i, t, "debug" if n < half else "holdout") for n, i in enumerate(ids)]
    rows.sort()
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scenario_id", "type", "split"])
        w.writerows(rows)
    for t in sorted({r[1] for r in rows}):
        n_dbg = sum(1 for r in rows if r[1] == t and r[2] == "debug")
        n_all = sum(1 for r in rows if r[1] == t)
        print(f"{t}: 调试 {n_dbg} / 留出 {n_all - n_dbg}")
    print(f"→ {OUT}")


if __name__ == "__main__":
    main()
