"""用 LLM 裁决 TeleQnA 近重复候选对。

候选对 = MinHash 字面召回（results/audit/near_dup_pairs.jsonl）∪ embedding 语义召回（cos ≥ COS_THRESHOLD）。
裁决模型不在任何被测名单里，避免用被测模型筛自己要考的题。

输出：
  results/audit/adjudication_raw.jsonl     每对的原始请求与响应（含原文，不入库；断点续跑依赖它）
  data/processed/teleqna_pair_labels.csv   每对的 ID 与标签（不含原文，可入库）

用法：uv run python scripts/adjudicate_pairs.py
"""

import csv
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from audit_teleqna import load_items  # noqa: E402

MODEL = "qwen3.8-2.4t-a95b"   # 只能开启思考；不在被测名单中
COS_THRESHOLD = 0.85
RAW = ROOT / "results/audit/adjudication_raw.jsonl"
LABELS = ROOT / "data/processed/teleqna_pair_labels.csv"
RELATIONS = {"duplicate", "variant", "related"}
ANSWERS = {"consistent", "conflict", "na"}

PROMPT = """You are auditing a telecom multiple-choice benchmark for redundant questions.
Compare the two questions below and classify their relation:

- "duplicate": they test the same fact. Someone who knows the answer to one necessarily knows the answer to the other; wording, phrasing, release tag or option set may differ.
- "variant": same template or topic, but a key entity, parameter, condition, direction or state differs (e.g. Rf vs Ro, PRACH vs NPRACH, CONNECTED vs IDLE, uplink vs downlink), so they test different facts.
- "related": same broad topic, otherwise different questions.

For "duplicate" only, also judge whether the two marked correct answers agree:
- "consistent": the correct answers express the same fact (paraphrase or one is a more complete form of the other).
- "conflict": the correct answers contradict each other.
Use "na" for the other relations.

Question A: {qa}
Options A: {oa}
Correct answer A: {aa}

Question B: {qb}
Options B: {ob}
Correct answer B: {ab}

Reply with a single JSON object only, no other text:
{{"relation": "duplicate|variant|related", "answers": "consistent|conflict|na", "reason": "<one short sentence>"}}"""


def candidate_pairs(items):
    by_id = {it["id"]: it for it in items}
    pairs = {}
    for line in (ROOT / "results/audit/near_dup_pairs.jsonl").open(encoding="utf-8"):
        p = json.loads(line)
        pairs[(p["a"], p["b"])] = {"stem_jaccard": p["stem_jaccard"], "source": "minhash"}
    d = np.load(ROOT / "results/audit/embeddings.npz")
    ids, emb = list(d["ids"]), d["emb"]
    sim = emb @ emb.T
    ii, jj = np.where(np.triu(sim, 1) >= COS_THRESHOLD)
    for i, j in zip(ii, jj):
        a, b = sorted([ids[i], ids[j]], key=lambda q: int(q.split()[-1]))
        entry = pairs.setdefault((a, b), {"stem_jaccard": None, "source": "embedding"})
        if entry["source"] == "minhash":
            entry["source"] = "both"
    for (a, b), entry in pairs.items():
        ia, ib = ids.index(a), ids.index(b)
        entry["cosine"] = round(float(sim[ia, ib]), 4)
    return [{"a": a, "b": b, **v} for (a, b), v in sorted(
        pairs.items(), key=lambda kv: (int(kv[0][0].split()[-1]), int(kv[0][1].split()[-1])))], by_id


def fmt_opts(opts):
    return " | ".join(f"({i + 1}) {o}" for i, o in enumerate(opts))


def parse(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if obj.get("relation") not in RELATIONS or obj.get("answers") not in ANSWERS:
        return None
    return obj


def adjudicate(client, pair, by_id):
    ia, ib = by_id[pair["a"]], by_id[pair["b"]]
    prompt = PROMPT.format(qa=ia["question"], oa=fmt_opts(ia["options"]), aa=ia["answer_text"],
                           qb=ib["question"], ob=fmt_opts(ib["options"]), ab=ib["answer_text"])
    record = {**pair, "model": MODEL}
    for attempt in range(3):  # 解析失败重试，不剔除
        try:
            stream = client.chat.completions.create(
                model=MODEL, messages=[{"role": "user", "content": prompt}], max_tokens=8192,
                stream=True, stream_options={"include_usage": True}, extra_body={"enable_thinking": True})
            content, reasoning, usage = "", "", None
            for chunk in stream:
                if chunk.usage:
                    usage = chunk.usage.model_dump()
                for ch in chunk.choices:
                    content += ch.delta.content or ""
                    reasoning += getattr(ch.delta, "reasoning_content", None) or ""
            obj = parse(content)
            record.update(attempts=attempt + 1, content=content, reasoning=reasoning, usage=usage)
            if obj:
                record.update(ok=True, **obj)
                return record
        except Exception as e:
            record.update(attempts=attempt + 1, error=f"{type(e).__name__}: {e}")
    record["ok"] = False
    return record


def main():
    load_dotenv(ROOT / ".env")
    client = OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"],
                    max_retries=5, timeout=120)  # 单次请求超时，避免个别流卡住
    items = load_items()
    pairs, by_id = candidate_pairs(items)

    done = {}
    if RAW.exists():
        for line in RAW.open(encoding="utf-8"):
            r = json.loads(line)
            if r.get("ok"):
                done[(r["a"], r["b"])] = r
    todo = [p for p in pairs if (p["a"], p["b"]) not in done]
    print(f"候选对 {len(pairs)}，已完成 {len(done)}，待裁决 {len(todo)}", flush=True)

    # 按完成顺序落盘：个别请求慢时不阻塞其他结果写出
    with RAW.open("a", encoding="utf-8") as f, ThreadPoolExecutor(16) as ex:
        futures = [ex.submit(adjudicate, client, p, by_id) for p in todo]
        for k, fut in enumerate(as_completed(futures), 1):
            r = fut.result()
            if k % 100 == 0:
                print(f"  {k}/{len(todo)}", flush=True)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            if r.get("ok"):
                done[(r["a"], r["b"])] = r

    failed = [p for p in pairs if (p["a"], p["b"]) not in done]
    retried = sum(1 for r in done.values() if r["attempts"] > 1)
    with LABELS.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["a", "b", "source", "stem_jaccard", "cosine", "relation", "answers", "model"])
        for p in pairs:
            r = done.get((p["a"], p["b"]))
            w.writerow([p["a"], p["b"], p["source"], p["stem_jaccard"], p["cosine"],
                        r["relation"] if r else "FAILED", r["answers"] if r else "", MODEL])
    print(f"写出 {LABELS.relative_to(ROOT)}；解析需重试 {retried} 对，最终失败 {len(failed)} 对")


if __name__ == "__main__":
    main()
