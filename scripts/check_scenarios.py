"""场景题清单机检：结构、配比、rubric 权重、依据来源、重复根因扫描。

用法：uv run python scripts/check_scenarios.py [--file data/scenarios/scenarios_draft.json]
只读，不改数据。退出码非 0 表示有硬性错误（权重不足/字段缺失/ID 重复）。
"""
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIF = {"standard", "constructed", "common_sense"}
# 诊断题两阶段打分（Spec「Rubric 设计」）；咨询/KPI 题用 overall 单阶段。
STAGES_BY_TYPE = {"diagnosis": {"root_cause", "action"}, "consulting": {"overall"}, "kpi": {"overall"}}
REQ_FIELDS = ["local_idx", "type", "dimension", "difficulty", "title", "prompt",
              "reference_answer", "root_cause", "rubric_points", "deductions",
              "high_risk_actions", "discriminating_trap", "excluded_hypotheses",
              "unverified_residuals", "id", "source_draft"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="data/scenarios/scenarios_draft.json")
    args = ap.parse_args()
    qs = json.loads((ROOT / args.file).read_text())

    errors, warnings = [], []
    ids = Counter()
    for q in qs:
        qid = q.get("id", "?")
        ids[qid] += 1
        for f in REQ_FIELDS:
            if f not in q:
                errors.append(f"{qid} 缺字段 {f}")
        w = sum(p.get("weight", 0) for p in q.get("rubric_points", []))
        if w != 100:
            errors.append(f"{qid} rubric 权重和={w}（应为 100）")
        allowed_stages = STAGES_BY_TYPE.get(q.get("type"), set())
        stages = set()
        for p in q.get("rubric_points", []):
            if p.get("verifiability") not in VERIF:
                errors.append(f"{qid}/{p.get('id')} verifiability 非法: {p.get('verifiability')}")
            if not p.get("source_note"):
                errors.append(f"{qid}/{p.get('id')} 缺 source_note")
            if p.get("stage") not in allowed_stages:
                errors.append(f"{qid}/{p.get('id')} stage 非法: {p.get('stage')}（{q.get('type')} 应为 {allowed_stages}）")
            stages.add(p.get("stage"))
        if q.get("type") == "diagnosis" and stages != {"root_cause", "action"}:
            warnings.append(f"{qid} 诊断题 rubric 未同时覆盖 root_cause 与 action: {stages}")
        if not q.get("unverified_residuals"):
            pass  # 允许为空
    for qid, n in ids.items():
        if n > 1:
            errors.append(f"ID 重复: {qid} x{n}")

    print(f"总题数: {len(qs)}   唯一 ID: {len(ids)}")
    print("题型:", dict(Counter(q["type"] for q in qs)))
    print("维度:", dict(Counter(q["dimension"] for q in qs)))
    print("难度:", dict(Counter(q["difficulty"] for q in qs)))
    verif_all = Counter(p["verifiability"] for q in qs for p in q["rubric_points"])
    print("要点可核验类型:", dict(verif_all))
    n_ur = sum(1 for q in qs if q.get("unverified_residuals"))
    print(f"带 unverified_residuals 的题: {n_ur}/{len(qs)}")
    print("ID 列表:", ", ".join(sorted(ids)))

    # 重复根因粗筛：按 root_cause 归一化后的关键词交集，供人工复核
    print("\n根因相似度粗筛（供人工复核，非判定）:")
    norm = []
    for q in qs:
        rc = (q.get("root_cause") or "").replace(" ", "")
        norm.append((q["id"], rc))
    kw = defaultdict(list)
    KEYS = ["PMTUD", "MTU", "地址池", "干扰", "路径", "绕行", "N6", "5QI", "QCI", "切片", "S6a",
            "单通", "RTP", "拥塞", "配置", "变更"]
    for qid, rc in norm:
        for k in KEYS:
            if k in rc:
                kw[k].append(qid)
    for k, lst in sorted(kw.items(), key=lambda x: -len(x[1])):
        if len(lst) > 1:
            print(f"  '{k}': {lst}")

    print(f"\n错误 {len(errors)} 条:")
    for e in errors:
        print("  ✗", e)
    print(f"警告 {len(warnings)} 条:")
    for w in warnings:
        print("  !", w)
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()
