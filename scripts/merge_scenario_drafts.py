"""合并 data/scenarios/drafts/*.v{1,2,3}.json 为一份带稳定 ID 的场景题清单。

每批次读 v1 起的最高版本（v2 核验修订版、v3 定稿前修订版；v0 为生成原稿，不读）。
被 SUPERSEDED 标记的跨批重复题不输出，但计数照常推进，从而保持其余题 ID 稳定（留下编号空位）。

用法：uv run python scripts/merge_scenario_drafts.py
输出：data/scenarios/scenarios_draft.json（ID：SC-D/C/K + 两位序号，按批次与 local_idx 排序）
"""
import glob
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREFIX = {"diagnosis": "SC-D", "consulting": "SC-C", "kpi": "SC-K"}
ORDER = ["diag-ran", "diag-core", "diag-transport", "diag-oam", "cons-a", "cons-b", "kpi-a", "kpi-b", "supp-a"]
# 跨批重复题：每对保留更扎实/维度更稀缺的一道，删掉下列 source_draft。
# 计数仍按原始顺序推进，只是不输出这些题，从而保持其余题 ID 不变（会留下编号空位）。
SUPERSEDED = {"diag-ran:3", "diag-ran:6", "diag-core:2", "diag-core:3"}
DRAFTS = ROOT / "data/scenarios/drafts"


def latest(key):
    versions = {int(p.name.split(".v")[1].split(".")[0]): p for p in DRAFTS.glob(f"{key}.v*.json")}
    return versions[max(v for v in versions if v >= 1)]


out, counters, dropped = [], {k: 0 for k in PREFIX}, []
for key in ORDER:
    path = latest(key)
    print(key, "←", path.name)
    for q in sorted(json.loads(path.read_text())["questions"], key=lambda q: q["local_idx"]):
        counters[q["type"]] += 1
        src = f"{key}:{q['local_idx']}"
        qid = f"{PREFIX[q['type']]}{counters[q['type']]:02d}"
        if src in SUPERSEDED:
            dropped.append(f"{qid}<-{src}「{q['title']}」")
            continue
        q["id"] = qid
        q["source_draft"] = src
        out.append(q)
(ROOT / "data/scenarios/scenarios_draft.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
print(counters, "total", len(out))
print("superseded:", *dropped, sep="\n  ")
