"""答案核验：分层抽样，并调用一个不在被测名单中的模型盲答。

抽样：从审计后保留的题中按类别比例分层随机抽 N_SAMPLE 题（固定种子），
另加近重复审计中标准答案互相矛盾的题（near_dup_conflict，含已因重复剔除的一方；不计入错误率估计）。

盲答：qwen3.8-2.4t-a95b（只能开思考）只看题干与选项、不看标准答案，选出一个选项。
与标准答案不一致的题进入深度核查。

输出：
  data/processed/teleqna_answer_check_sample.csv   抽样题 ID、来源、盲答选项（无原文，可入库）
  results/audit/answer_check/blind_qwen.jsonl      盲答原始请求与响应（不入库；断点续跑依赖它）
  results/audit/answer_check/items.json            抽样题原文与标准答案（不入库，供核查 workflow 使用）

用法：uv run python scripts/answer_check_sample.py [--no-solve] [--redraw]
  抽样一经生成即冻结：已有 teleqna_answer_check_sample.csv 时沿用其中的题目，
  因为审计表的剔除标记会随核验结论变化，重抽会得到不同样本。--redraw 才重新抽样。
  --no-solve：不再调用接口，只用已落盘的盲答结果生成输出（2.4t 成本高，Oct 11 停在 267/309 题）
"""

import argparse
import csv
import json
import os
import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from audit_teleqna import load_items  # noqa: E402

SEED = 20261012
N_SAMPLE = 300
MODEL = "qwen3.8-2.4t-a95b"
OUT_DIR = ROOT / "results/audit/answer_check"
RAW = OUT_DIR / "blind_qwen.jsonl"
SAMPLE_CSV = ROOT / "data/processed/teleqna_answer_check_sample.csv"

PROMPT = """Answer the following multiple-choice question about telecommunications standards.
Think it through, then end your reply with a final line of the form "Answer: <option number>".

Question: {q}
{opts}"""


def draw_sample(items, flags):
    rng = random.Random(SEED)
    kept = [it for it in items if not flags[it["id"]]["drop_reason"]]
    by_cat = {}
    for it in kept:
        by_cat.setdefault(it["category"], []).append(it)
    # 按类别比例分配名额（最大余数法），保证总数恰为 N_SAMPLE
    quotas = {c: N_SAMPLE * len(v) / len(kept) for c, v in by_cat.items()}
    alloc = {c: int(q) for c, q in quotas.items()}
    for c in sorted(quotas, key=lambda c: quotas[c] - alloc[c], reverse=True)[:N_SAMPLE - sum(alloc.values())]:
        alloc[c] += 1
    sample = []
    for c in sorted(by_cat):
        for it in rng.sample(sorted(by_cat[c], key=lambda x: x["num"]), alloc[c]):
            sample.append((it, "random"))
    picked = {it["id"] for it, _ in sample}
    # 答案矛盾的题对两边都核验，包括去重时被删的一方：保留下来的那道可能恰好是错的
    for it in items:
        if flags[it["id"]]["near_dup_conflict"] == "True" and it["id"] not in picked:
            sample.append((it, "conflict"))
    return sample


def parse_choice(text, n_opts):
    m = re.findall(r"Answer:\s*\(?(?:option\s*)?(\d)\)?", text, re.I)
    if m and 1 <= int(m[-1]) <= n_opts:
        return int(m[-1])
    return None


def solve(client, it):
    opts = "\n".join(f"Option {i + 1}: {o}" for i, o in enumerate(it["options"]))
    prompt = PROMPT.format(q=it["question"], opts=opts)
    record = {"id": it["id"], "model": MODEL}
    for attempt in range(3):
        try:
            r = client.chat.completions.create(
                model=MODEL, messages=[{"role": "user", "content": prompt}], max_tokens=8192,
                stream=True, stream_options={"include_usage": True}, extra_body={"enable_thinking": True})
            content, usage = "", None
            for chunk in r:
                if chunk.usage:
                    usage = chunk.usage.model_dump()
                for ch in chunk.choices:
                    content += ch.delta.content or ""
            choice = parse_choice(content, len(it["options"]))
            record.update(attempts=attempt + 1, content=content, usage=usage, choice=choice)
            if choice:
                record["ok"] = True
                return record
        except Exception as e:
            record.update(attempts=attempt + 1, error=f"{type(e).__name__}: {e}")
    record["ok"] = False
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-solve", action="store_true")
    parser.add_argument("--redraw", action="store_true")
    args = parser.parse_args()
    items = load_items()
    with (ROOT / "data/processed/teleqna_items.csv").open(encoding="utf-8") as f:
        flags = {r["id"]: r for r in csv.DictReader(f)}
    if SAMPLE_CSV.exists() and not args.redraw:
        by_id = {it["id"]: it for it in items}
        with SAMPLE_CSV.open(encoding="utf-8") as f:
            sample = [(by_id[r["id"]], r["source"]) for r in csv.DictReader(f)]
    else:
        sample = draw_sample(items, flags)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    load_dotenv(ROOT / ".env")
    client = OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"],
                    max_retries=5, timeout=180)
    done = {}
    if RAW.exists():
        for line in RAW.open(encoding="utf-8"):
            r = json.loads(line)
            if r.get("ok"):
                done[r["id"]] = r
    todo = [] if args.no_solve else [it for it, _ in sample if it["id"] not in done]
    print(f"抽样 {len(sample)} 题，已盲答 {len(done)}，待盲答 {len(todo)}", flush=True)
    with RAW.open("a", encoding="utf-8") as f, ThreadPoolExecutor(16) as ex:
        for fut in as_completed([ex.submit(solve, client, it) for it in todo]):
            r = fut.result()
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            if r.get("ok"):
                done[r["id"]] = r

    with SAMPLE_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "category", "source", "gold", "qwen_choice"])
        for it, src in sample:
            r = done.get(it["id"])
            w.writerow([it["id"], it["category"], src, it["answer_idx"] + 1, r["choice"] if r else ""])
    (OUT_DIR / "items.json").write_text(json.dumps(
        [{"id": it["id"], "category": it["category"], "source": src, "question": it["question"],
          "options": it["options"], "gold": it["answer_idx"] + 1} for it, src in sample],
        ensure_ascii=False, indent=1), encoding="utf-8")

    answered = [done[it["id"]] for it, _ in sample if it["id"] in done]
    agree = sum(1 for it, _ in sample if it["id"] in done and done[it["id"]]["choice"] == it["answer_idx"] + 1)
    print(f"盲答完成 {len(answered)}/{len(sample)}，与标准答案一致 {agree}，不一致 {len(answered) - agree}")


if __name__ == "__main__":
    main()
