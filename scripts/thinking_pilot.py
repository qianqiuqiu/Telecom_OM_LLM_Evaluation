"""思考模式试跑：实测开启思考时每题的输出 token，用于收窄 analysis/cost_estimate.py 的思考对照费用区间。

从客观题测试子集按能力维度分层抽 10 题（固定种子），每个模型开思考各答 1 次（Oct 12 用户决定不含 kimi-k3）。
原始请求与响应落盘到 results/pilot/thinking_<时间戳>.jsonl，终端打印每模型平均输入 / 输出 / 思考 token、
正确数、截断数与按原价折算的实际花费。

用法：uv run python scripts/thinking_pilot.py [--n 10] [--exclude kimi-k3]
"""

import argparse
import csv
import json
import os
import random
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
SEED = 20261012
MAX_TOKENS = 16384
PROMPT = ("Answer the following multiple-choice question about telecommunications. "
          "Reply with the option number only.\n\n{question}\n{options}")
# 元 / 百万 token（与 analysis/cost_estimate.py 一致）
PRICE = {"qwen3.8-max-0902": (12, 36), "qwen3.7-plus": (2, 8), "qwen3.8-flash": (0.8, 2.7),
         "deepseek-v4-pro-0813": (9, 27), "deepseek-v4.1-flash": (2, 8), "glm-5.2": (8, 28),
         "kimi-k3": (20, 100), "glm-5.3": (8, 28)}


def sample(n):
    with (ROOT / "data/processed/teleqna_test_subset.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    by_dim = defaultdict(list)
    for r in rows:
        by_dim[r["dimension"]].append(r)
    rng = random.Random(SEED)
    dims = sorted(by_dim, key=lambda d: -len(by_dim[d]))
    picked = []
    while len(picked) < n:  # 按维度轮流抽，保证覆盖
        for d in dims:
            pool = [r for r in by_dim[d] if r not in picked]
            if pool and len(picked) < n:
                picked.append(rng.choice(pool))
    return picked


def ask(client, model, item, raw):
    v = raw[item["id"]]
    opts = [v[k] for k in sorted((k for k in v if k.startswith("option ")), key=lambda k: int(k.split()[1]))]
    content = PROMPT.format(question=v["question"], options="\n".join(f"{i + 1}) {o}" for i, o in enumerate(opts)))
    request = {"model": model, "messages": [{"role": "user", "content": content}], "max_tokens": MAX_TOKENS,
               "stream": True, "stream_options": {"include_usage": True}}
    rec = {"model": model, "id": item["id"], "gold": int(item["gold"]), "request": request}
    t0 = time.time()
    text, reasoning, usage, finish = "", "", None, None
    try:
        for chunk in client.chat.completions.create(**request, extra_body={"enable_thinking": True}):
            if chunk.usage:
                usage = chunk.usage.model_dump()
            for ch in chunk.choices:
                text += ch.delta.content or ""
                reasoning += getattr(ch.delta, "reasoning_content", None) or ""
                finish = ch.finish_reason or finish
        m = re.search(r"\d+", text)
        rec.update(ok=True, content=text, reasoning=reasoning, usage=usage, finish_reason=finish,
                   choice=int(m.group()) if m else None)
    except Exception as e:
        rec.update(ok=False, error=f"{type(e).__name__}: {e}")
    rec["latency_s"] = round(time.time() - t0, 1)
    return rec


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=10)
    parser.add_argument("--exclude", action="append", default=["kimi-k3"])
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    client = OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"])
    cfg = yaml.safe_load((ROOT / "configs/models.yaml").read_text(encoding="utf-8"))
    models = [m["id"] for g in ("main", "thinking_only") for m in cfg[g] if m["id"] not in args.exclude]
    raw = json.loads((ROOT / "data/raw/TeleQnA/TeleQnA.json").read_text(encoding="utf-8"))
    items = sample(args.n)
    jobs = [(m, it) for m in models for it in items]
    print(f"{len(models)} 个模型 × {len(items)} 题 = {len(jobs)} 次调用：{', '.join(models)}")

    with ThreadPoolExecutor(8) as ex:
        records = list(ex.map(lambda j: ask(client, j[0], j[1], raw), jobs))

    out_dir = ROOT / "results/pilot"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"thinking_{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    total = 0.0
    print(f"\n{'模型':<22} 成功 正确 截断  平均输入  平均输出  平均思考  最大输出  实际花费(元)")
    for m in models:
        rs = [r for r in records if r["model"] == m]
        ok = [r for r in rs if r["ok"] and r["usage"]]
        if not ok:
            print(f"{m:<22} 全部失败：{rs[0].get('error', '')[:80]}")
            continue
        tin = [r["usage"]["prompt_tokens"] for r in ok]
        tout = [r["usage"]["completion_tokens"] for r in ok]
        think = [((r["usage"].get("completion_tokens_details") or {}).get("reasoning_tokens") or 0) for r in ok]
        pi, po = PRICE[m]
        spent = (sum(tin) * pi + sum(tout) * po) / 1e6
        total += spent
        print(f"{m:<22} {len(ok):>4} {sum(r['choice'] == r['gold'] for r in ok):>4}"
              f" {sum(r['finish_reason'] == 'length' for r in ok):>4} {sum(tin) / len(ok):>9.0f} {sum(tout) / len(ok):>9.0f}"
              f" {sum(think) / len(ok):>9.0f} {max(tout):>9} {spent:>12.3f}")
    print(f"\n合计实际花费约 {total:.2f} 元（原价；DeepSeek 按白天价计）。原始记录：{out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
