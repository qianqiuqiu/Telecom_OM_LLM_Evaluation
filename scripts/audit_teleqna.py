"""TeleQnA 审计第一步：选项结构检查 + 近重复检测。

输入：data/raw/TeleQnA/TeleQnA.json（只取 Standards specifications / Standards overview / Lexicon）
输出：
  data/processed/teleqna_items.csv        每题一行：ID 与审计标记（不含题目原文，可入库）
  results/audit/near_dup_pairs.jsonl      近重复候选对，含原文，供人工 / 辅助复核（不入库）
  reports/audit/teleqna_dedup_options.md  可报告的数字

用法：uv run python scripts/audit_teleqna.py
"""

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from datasketch import MinHash, MinHashLSH

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data/raw/TeleQnA/TeleQnA.json"
KEEP = ["Standards specifications", "Standards overview", "Lexicon"]

NUM_PERM = 256
SHINGLE = 5            # 字符 5-gram：题干中位数只有 13 个词，词级 n-gram 太稀疏
LSH_THRESHOLD = 0.5    # 召回候选对的下限，最终判定在候选对上用精确 Jaccard 再分档
DUP_THRESHOLD = 0.9    # 题干精确 Jaccard 达到此值且正确答案相同 → 判为近重复（阈值依据见报告）

RELEASE_RE = re.compile(r"\s*\[3GPP Release (\d+)\]\s*", re.I)
# 依赖选项位置的选项：打乱时固定在末位
POSITION_REF_RE = re.compile(r"^\s*(all|none) of the above\b", re.I)
# 引用其他选项编号的选项：整题不打乱
INDEX_REF_RE = re.compile(r"^\s*both\s+(options?\s*)?\d+\s+and\s+(options?\s*)?\d+", re.I)
# 题干引用考生看不到的原文（“according to the document”等）：脱离原文无法作答
CONTEXT_REF_RE = re.compile(r"\b(the|this|given)\s+(document|text|paper|article|passage|study|report)\b", re.I)


def norm(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def shingles(text):
    t = norm(text)
    if len(t) < SHINGLE:
        return {t}
    return {t[i:i + SHINGLE] for i in range(len(t) - SHINGLE + 1)}


def jaccard(a, b):
    return len(a & b) / len(a | b) if a | b else 1.0


def load_items():
    raw = json.loads(SRC.read_text(encoding="utf-8"))
    items = []
    for qid, v in raw.items():
        if v["category"] not in KEEP:
            continue
        options = [v[k] for k in sorted((k for k in v if k.startswith("option ")),
                                        key=lambda k: int(k.split()[1]))]
        m = re.match(r"option (\d+)", v["answer"])
        ans_idx = int(m.group(1)) - 1
        rel = RELEASE_RE.search(v["question"])
        items.append({
            "id": qid,
            "num": int(qid.split()[-1]),
            "category": v["category"],
            "question": v["question"],
            "stem": RELEASE_RE.sub(" ", v["question"]).strip(),
            "release": int(rel.group(1)) if rel else None,
            "options": options,
            "answer_idx": ans_idx,
            "answer_text": options[ans_idx],
        })
    return items


def option_flags(item):
    opts = item["options"]
    position_ref = [i for i, o in enumerate(opts) if POSITION_REF_RE.match(o)]
    index_ref = [i for i, o in enumerate(opts) if INDEX_REF_RE.match(o)]
    if index_ref:
        shuffle_policy = "no_shuffle"
    elif position_ref:
        shuffle_policy = "pin_last"
    else:
        shuffle_policy = "free"
    return {
        "n_options": len(opts),
        "has_position_ref": bool(position_ref),
        "has_index_ref": bool(index_ref),
        "answer_is_ref": item["answer_idx"] in position_ref + index_ref,
        "pinned_not_last": any(i != len(opts) - 1 for i in position_ref),
        "shuffle_policy": shuffle_policy,
        "context_ref": bool(CONTEXT_REF_RE.search(item["stem"])),
    }


def load_labels(by_id, sh):
    """读取 LLM 裁决标签，并补算每对的字面相似度与选项重合度。没有标签文件时返回空列表。"""
    path = ROOT / "data/processed/teleqna_pair_labels.csv"
    if not path.exists():
        return []
    # 校验抽样中的对：以独立标注者多数票覆盖 LLM 裁决（见 analysis/pair_adjudicator_agreement.py）
    overrides = {}
    vpath = ROOT / "data/processed/teleqna_pair_validation.csv"
    if vpath.exists():
        votes = defaultdict(list)
        with vpath.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                votes[(r["a"], r["b"])].append(r)
        for key, vs in votes.items():
            c = Counter(v["relation"] for v in vs).most_common()
            top = [lab for lab, cnt in c if cnt == c[0][1]]
            rel = top[0] if len(top) == 1 else next(l for l in ["variant", "related", "duplicate"] if l in top)
            ans = (Counter(v["answers"] for v in vs if v["relation"] == "duplicate").most_common(1)[0][0]
                   if rel == "duplicate" else "na")
            overrides[key] = (rel, ans)
    labels = []
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["llm_relation"] = row["relation"]
            row["validated"] = (row["a"], row["b"]) in overrides
            if row["validated"]:
                row["relation"], row["answers"] = overrides[(row["a"], row["b"])]
            ia, ib = by_id[row["a"]], by_id[row["b"]]
            row["stem_jaccard"] = jaccard(sh[row["a"]], sh[row["b"]])
            row["cosine"] = float(row["cosine"])
            row["options_jaccard"] = jaccard({norm(o) for o in ia["options"]}, {norm(o) for o in ib["options"]})
            labels.append(row)
    return labels


class UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # 保留编号最小的题作为代表，保证结果确定
            keep, drop = sorted([ra, rb], key=lambda q: int(q.split()[-1]))
            self.parent[drop] = keep


def main():
    items = load_items()
    by_id = {it["id"]: it for it in items}

    # 1. 选项结构
    for it in items:
        it.update(option_flags(it))

    # 2. 精确重复：规范化后的题干 + 选项集合完全相同
    exact_key = defaultdict(list)
    for it in items:
        exact_key[(norm(it["question"]), tuple(sorted(norm(o) for o in it["options"])))].append(it["id"])

    # 3. 近重复候选：题干（去掉版本标签）MinHash LSH
    sh = {it["id"]: shingles(it["stem"]) for it in items}
    lsh = MinHashLSH(threshold=LSH_THRESHOLD, num_perm=NUM_PERM)
    mh = {}
    for it in items:
        m = MinHash(num_perm=NUM_PERM, seed=1)
        for s in sh[it["id"]]:
            m.update(s.encode())
        mh[it["id"]] = m
        lsh.insert(it["id"], m)

    pairs = {}
    for it in items:
        for other in lsh.query(mh[it["id"]]):
            if other == it["id"]:
                continue
            a, b = sorted([it["id"], other], key=lambda q: int(q.split()[-1]))
            if (a, b) in pairs:
                continue
            ia, ib = by_id[a], by_id[b]
            stem_j = jaccard(sh[a], sh[b])
            if stem_j < LSH_THRESHOLD:
                continue
            pairs[(a, b)] = {
                "a": a, "b": b,
                "stem_jaccard": round(stem_j, 4),
                "options_jaccard": round(jaccard({norm(o) for o in ia["options"]},
                                                 {norm(o) for o in ib["options"]}), 4),
                "same_answer": norm(ia["answer_text"]) == norm(ib["answer_text"]),
                "same_release": ia["release"] == ib["release"],
                "cross_category": ia["category"] != ib["category"],
            }

    # 4. 字面规则：题干高度相似且正确答案文本相同 → 重复。只作基线，用来和 LLM 裁决对照
    for p in pairs.values():
        p["rule_duplicate"] = p["stem_jaccard"] >= DUP_THRESHOLD and p["same_answer"]

    # 5. LLM 裁决（scripts/adjudicate_pairs.py 产出）存在时，以裁决为准；否则退回字面规则
    labels = load_labels(by_id, sh)
    uf = UnionFind()
    if labels:
        for l in labels:
            p = pairs.get((l["a"], l["b"]))
            l["rule_duplicate"] = bool(p and p["rule_duplicate"])
            if l["relation"] == "duplicate":
                uf.union(l["a"], l["b"])
        conflict_ids = {x for l in labels if l["answers"] == "conflict" for x in (l["a"], l["b"])}
    else:
        for p in pairs.values():
            if p["rule_duplicate"]:
                uf.union(p["a"], p["b"])
        # 题干高度相似但答案文本不同：可能是变体，也可能是答案冲突
        conflict_ids = {x for p in pairs.values()
                        if p["stem_jaccard"] >= DUP_THRESHOLD and not p["same_answer"] for x in (p["a"], p["b"])}
    for ids in exact_key.values():
        for other in ids[1:]:
            uf.union(ids[0], other)

    for it in items:
        rep = uf.find(it["id"])
        it["dup_of"] = "" if rep == it["id"] else rep
        it["near_dup_conflict"] = it["id"] in conflict_ids
        it["drop_reason"] = ("dup" if it["dup_of"] else
                             "too_few_options" if it["n_options"] < 4 else
                             "context_ref" if it["context_ref"] else "")

    # 输出：每题标记（无原文）
    out_csv = ROOT / "data/processed/teleqna_items.csv"
    cols = ["id", "category", "release", "n_options", "answer_idx", "shuffle_policy",
            "has_position_ref", "has_index_ref", "answer_is_ref", "pinned_not_last",
            "context_ref", "dup_of", "near_dup_conflict", "drop_reason"]
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for it in sorted(items, key=lambda x: x["num"]):
            w.writerow({c: it.get(c) for c in cols})

    # 输出：候选对（含原文，供复核）
    out_pairs = ROOT / "results/audit/near_dup_pairs.jsonl"
    out_pairs.parent.mkdir(parents=True, exist_ok=True)
    with out_pairs.open("w", encoding="utf-8") as f:
        for p in sorted(pairs.values(), key=lambda p: -p["stem_jaccard"]):
            ia, ib = by_id[p["a"]], by_id[p["b"]]
            row = dict(p)
            for tag, it in (("a", ia), ("b", ib)):
                row[f"{tag}_question"] = it["question"]
                row[f"{tag}_options"] = it["options"]
                row[f"{tag}_answer"] = it["answer_text"]
                row[f"{tag}_category"] = it["category"]
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    write_report(items, pairs, exact_key, labels)
    print(f"写出 {out_csv.relative_to(ROOT)}、{out_pairs.relative_to(ROOT)}、reports/audit/teleqna_dedup_options.md")


def write_report(items, pairs, exact_key, labels):
    n = len(items)
    pct = lambda k, base=n: f"{k}（{k / base:.1%}）" if base else f"{k}"
    cat = Counter(it["category"] for it in items)
    nopt = Counter(it["n_options"] for it in items)
    policy = Counter(it["shuffle_policy"] for it in items)
    exact_extra = sum(len(v) - 1 for v in exact_key.values() if len(v) > 1)
    dropped_dup = sum(1 for it in items if it["dup_of"])
    clusters = Counter(it["dup_of"] for it in items if it["dup_of"])
    too_few = sum(1 for it in items if it["n_options"] < 4 and not it["dup_of"])
    kept = sum(1 for it in items if not it["drop_reason"])
    flagged = sum(1 for it in items if it["near_dup_conflict"])

    lines = [
        "# TeleQnA 审计：选项结构与近重复",
        "",
        "由 `scripts/audit_teleqna.py` 生成，请勿手改。",
        "",
        f"范围：{' / '.join(f'{c} {cat[c]}' for c in KEEP)}，共 {n} 题。",
        "",
        "## 选项结构",
        "",
        "| 项目 | 题数 |",
        "| --- | --- |",
        *[f"| {k} 个选项 | {pct(v)} |" for k, v in sorted(nopt.items())],
        f"| 含 All / None of the above | {pct(sum(it['has_position_ref'] for it in items))} |",
        f"| 其中该选项不在末位 | {pct(sum(it['pinned_not_last'] for it in items))} |",
        f"| 含“Both option i and j”类编号引用 | {pct(sum(it['has_index_ref'] for it in items))} |",
        f"| 正确答案就是上述引用类选项 | {pct(sum(it['answer_is_ref'] for it in items))} |",
        f"| 题干引用不可见原文（according to the document 等） | {pct(sum(it['context_ref'] for it in items))} |",
        "",
        "打乱策略：" + "，".join(f"`{k}` {v}" for k, v in sorted(policy.items()))
        + "（`pin_last`：引用类选项固定末位，其余打乱；`no_shuffle`：整题不打乱）。",
        "",
        "## 重复与近重复",
        "",
        "**召回**：题干去掉 `[3GPP Release N]` 标签后，两路召回候选对。",
        "",
        f"- 字面：字符 {SHINGLE}-gram，MinHash（{NUM_PERM} perm）+ LSH，题干 Jaccard ≥ {LSH_THRESHOLD}。",
        "- 语义：`qwen3.7-text-embedding` 余弦相似度 ≥ 0.85（见 `scripts/adjudicate_pairs.py`）。",
        "",
    ]

    if labels:
        rel = Counter(l["relation"] for l in labels)
        src = Counter(l["source"] for l in labels)
        dup = [l for l in labels if l["relation"] == "duplicate"]
        dup_src = Counter(l["source"] for l in dup)
        rule_tp = sum(1 for l in dup if l["rule_duplicate"])
        rule_fp = sum(1 for l in labels if l["rule_duplicate"] and l["relation"] != "duplicate")
        conflicts = sum(1 for l in dup if l["answers"] == "conflict")
        reused = [l for l in labels if l["options_jaccard"] == 1.0 and l["relation"] != "duplicate"]
        failed = rel.get("FAILED", 0)
        bands = [(0.0, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 1.0001)]
        band_rows = []
        for lo, hi in bands:
            ls = [l for l in labels if lo <= l["stem_jaccard"] < hi]
            d = sum(l["relation"] == "duplicate" for l in ls)
            band_rows.append(f"| [{lo:.1f}, {min(hi, 1):.1f}{']' if hi > 1 else ')'} | {len(ls)} | {d} | "
                             f"{sum(l['relation'] == 'variant' for l in ls)} | {d / len(ls):.0%} |" if ls else
                             f"| [{lo:.1f}, {min(hi, 1):.1f}) | 0 | 0 | 0 | — |")
        lines += [
            f"**裁决**：候选对交给 `{labels[0]['model']}`（只能开思考，不在被测名单中）判为"
            "重复 / 变体 / 相关；重复对再判两题标准答案是否一致。判为重复的题按连通分量聚类，每簇保留编号最小的一题。",
            "",
            f"- 候选对 {len(labels)} 对：仅字面召回 {src['minhash']}，仅语义召回 {src['embedding']}，两路都召回 {src['both']}",
            f"- 最终标签（裁决经校验覆盖后）：重复 {rel['duplicate']}，变体 {rel['variant']}，相关 {rel['related']}"
            + (f"，裁决失败 {failed}" if failed else ""),
            f"- 重复对的召回来源：仅字面 {dup_src['minhash']}，仅语义 {dup_src['embedding']}，两路 {dup_src['both']}",
            f"- 校验覆盖：{sum(l['validated'] for l in labels)} 对经独立标注者盲标（见 "
            "`teleqna_adjudicator_validation.md`），以多数票覆盖裁决；"
            f"由此改判 {sum(l['validated'] and l['relation'] != l['llm_relation'] for l in labels)} 对，"
            f"其中重复改为非重复 {sum(l['llm_relation'] == 'duplicate' and l['relation'] != 'duplicate' for l in labels)} 对",
            f"- 完全重复（题干与选项集合规范化后相同）：多出 {exact_extra} 题",
            f"- 判为重复而删除：{pct(dropped_dup)}，涉及 {len(clusters)} 个重复簇",
            f"- 重复对中标准答案互相矛盾：{conflicts} 对，涉及题目标记 `near_dup_conflict`，共 {flagged} 题，交答案核验",
            f"- 选项集合完全相同、但并非重复的题对：{len(reused)} 对（疑似生成时复用选项，交干扰项质量审计）",
            "",
            "**字面规则基线**（题干 Jaccard ≥ 0.9 且答案文本完全相同）与裁决对照：",
            "",
            f"- 规则判为重复 {rule_tp + rule_fp} 对，其中裁决也判为重复 {rule_tp} 对",
            f"- 裁决判为重复的 {len(dup)} 对中，规则只找到 {rule_tp} 对（召回 {rule_tp / len(dup):.0%}）" if dup else "",
            "",
            "| 题干 Jaccard 区间 | 候选对 | 判为重复 | 判为变体 | 重复占比 |",
            "| --- | --- | --- | --- | --- |",
            *band_rows,
            "",
        ]
    else:
        lines += [
            f"**判定**（尚无 LLM 裁决，退回字面规则）：题干 Jaccard ≥ {DUP_THRESHOLD} 且正确答案文本相同 → 近重复。",
            "",
            f"- 完全重复：多出 {exact_extra} 题",
            f"- 近重复候选对：{len(pairs)} 对",
            f"- 判为重复而删除：{pct(dropped_dup)}，涉及 {len(clusters)} 个重复簇",
            "",
        ]

    lines += [
        "## 汇总",
        "",
        f"- 重复剔除：{pct(dropped_dup)}",
        f"- 选项少于 4 个而剔除（不含已因重复剔除的）：{pct(too_few)}",
        f"- 题干引用不可见原文而剔除（不含前两项已剔除的）：{pct(sum(it['drop_reason'] == 'context_ref' for it in items))}",
        f"- 保留：{pct(kept)}",
        "",
    ]
    out = ROOT / "reports/audit/teleqna_dedup_options.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
