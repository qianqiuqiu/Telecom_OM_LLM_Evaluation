"""探测 configs/models.yaml 中的模型能否调用，以及思考开关是否按预期生效。

每个模型按 configs 中的每种 mode 各调用一次，原始请求与响应落盘到
results/probe/<时间戳>.jsonl，终端打印摘要。

用法：uv run python scripts/probe_models.py [--group main] [--group thinking_only]
"""

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
QUESTION = (
    "In LTE, what does PRB stand for?\n"
    "A) Physical Resource Block\nB) Primary Radio Bearer\n"
    "C) Packet Routing Buffer\nD) Physical Random Burst\n"
    "Answer with the letter only."
)


def probe(client, model_id, mode, params):
    request = {
        "model": model_id,
        "messages": [{"role": "user", "content": QUESTION}],
        "max_tokens": 4096,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    extra = dict(params)
    if "temperature" in extra:
        request["temperature"] = extra.pop("temperature")
    record = {"model": model_id, "mode": mode, "request": {**request, "extra_body": extra}}
    t0 = time.time()
    content, reasoning, usage, returned_model = "", "", None, None
    try:
        stream = client.chat.completions.create(**request, extra_body=extra)
        for chunk in stream:
            returned_model = chunk.model or returned_model
            if chunk.usage:
                usage = chunk.usage.model_dump()
            for choice in chunk.choices:
                delta = choice.delta
                content += delta.content or ""
                reasoning += getattr(delta, "reasoning_content", None) or ""
        record.update(ok=True, content=content, reasoning=reasoning, usage=usage,
                      returned_model=returned_model)
    except Exception as e:  # 记录错误而不是中断：探测的目的就是看哪些调不通
        record.update(ok=False, error=f"{type(e).__name__}: {e}")
    record["latency_s"] = round(time.time() - t0, 2)
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", action="append", help="models.yaml 中的分组，默认全部")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    client = OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"])
    cfg = yaml.safe_load((ROOT / "configs/models.yaml").read_text(encoding="utf-8"))
    groups = args.group or [g for g in cfg if g != "modes"]
    jobs = [(m["id"], mode, params)
            for g in groups for m in cfg[g] for mode, params in cfg["modes"].items()]

    with ThreadPoolExecutor(8) as ex:
        records = list(ex.map(lambda job: probe(client, *job), jobs))

    out_dir = ROOT / "results/probe"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    for r in records:
        if r["ok"]:
            u = r["usage"] or {}
            print(f"{r['model']:<22} {r['mode']:<4} ok   answer={r['content'].strip()[:12]!r:<16}"
                  f" reasoning={len(r['reasoning']):>5}c out_tokens={u.get('completion_tokens')}"
                  f" {r['latency_s']}s")
        else:
            print(f"{r['model']:<22} {r['mode']:<4} FAIL {r['error'][:100]}")
    print(f"\n原始记录：{out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
