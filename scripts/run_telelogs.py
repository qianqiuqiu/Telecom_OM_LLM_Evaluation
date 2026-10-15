"""TeleLogs 子集（Spec「故障诊断的客观参照」）：5G 路测数据根因分析，8 类根因，规则判分，不依赖 judge。

- 题目：data/raw/TeleLogs/troubleshooting/test.json（864 题，8 类各 108 题）中按类分层抽 200 题
  （每类 25 题，种子 20261015），题号 = 测试集中的下标，清单写入 data/processed/telelogs_sample.csv（只有题号与类别）。
- 调用：7 个主实验模型，关思考、温度 0；只发原题文本（题面自带「把编号写进 \\boxed{}」的要求），不加系统提示。
- 判分：取回答里最后一个 \\boxed{...}，从中抽 C1–C8（也接受只写数字）；抽不到记错，抽取失败在汇总里单列。
  被截断（finish_reason = length）的回答照常判分并计数。
- 缓存：results/telelogs/raw/<模型>.jsonl（含原文，不入库）；逐题结果 results/telelogs/predictions.csv（入库）。

用法：
  uv run python scripts/run_telelogs.py --dry-run
  uv run python scripts/run_telelogs.py --limit 2                 # 试跑：每个模型 2 题，看输出长度
  uv run python scripts/run_telelogs.py                           # 全量
  uv run python scripts/run_telelogs.py --export-only
"""
import argparse
import csv
import hashlib
import json
import os
import random
import re
import statistics
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml
from thinking_pilot import PRICE
from verify_three_vote import load_env

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data/raw/TeleLogs/troubleshooting/test.json"
SAMPLE = ROOT / "data/processed/telelogs_sample.csv"
MODELS = ROOT / "configs/models.yaml"
OUT = ROOT / "results/telelogs"
SEED = 20261015
PER_CLASS = 25
MAX_TOKENS = 4096

_BOXED = re.compile(r"\\boxed\{+\s*([^{}]*?)\s*\}+")


def sample():
    items = json.loads(SRC.read_text(encoding="utf-8"))
    if SAMPLE.exists():
        rows = list(csv.DictReader(SAMPLE.open(encoding="utf-8")))
        return items, [(int(r["idx"]), r["gold"]) for r in rows]
    by = defaultdict(list)
    for i, it in enumerate(items):
        by[gold_of(it)].append(i)
    rng = random.Random(SEED)
    picked = sorted((i, c) for c in sorted(by) for i in rng.sample(by[c], PER_CLASS))
    with SAMPLE.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["idx", "gold"])
        w.writerows(picked)
    return items, picked


def gold_of(it):
    m = re.search(r"C\s*([1-8])", str(it["answer"]))
    return f"C{m.group(1)}"


def extract(text):
    hits = _BOXED.findall(text or "")
    if not hits:
        return None
    m = re.search(r"C?\s*([1-8])\b", hits[-1], re.I)
    return f"C{m.group(1)}" if m else None


def key_of(model, prompt):
    return hashlib.sha256(json.dumps([model, prompt, MAX_TOKENS, "off", 0], ensure_ascii=False).encode()).hexdigest()[:16]


def load(path):
    out = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def call(client, model, prompt, attempts=3):
    err = None
    for a in range(1, attempts + 1):
        try:
            t0 = time.monotonic()
            r = client.chat.completions.create(
                model=model, temperature=0, max_tokens=MAX_TOKENS, extra_body={"enable_thinking": False},
                messages=[{"role": "user", "content": prompt}])
            u = r.usage
            content = r.choices[0].message.content or ""
            if not content.strip():
                err = f"答案为空（finish_reason={r.choices[0].finish_reason}）"
                continue
            return {"ok": True, "content": content, "served_model": r.model,
                    "finish_reason": r.choices[0].finish_reason, "latency_s": round(time.monotonic() - t0, 1),
                    "usage": {"input": u.prompt_tokens, "output": u.completion_tokens,
                              "reasoning": (getattr(u, "completion_tokens_details", None) and
                                            getattr(u.completion_tokens_details, "reasoning_tokens", 0)) or 0}
                    if u else None}
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"[:300]
            time.sleep(2 ** a)
    return {"ok": False, "error": err}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", action="append")
    ap.add_argument("--limit", type=int, help="只取抽样里前 N 题（试跑）")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--export-only", action="store_true")
    args = ap.parse_args()

    cfg = yaml.safe_load(MODELS.read_text(encoding="utf-8"))
    models = args.model or [m["id"] for m in cfg["main"]]
    items, picked = sample()
    picked = picked[:args.limit] if args.limit else picked
    jobs = [(m, i, g, items[i]["question"]) for m in models for i, g in picked]
    raw = OUT / "raw"
    recs = {m: load(raw / f"{m}.jsonl") for m in models}
    done = {r["key"]: r for rs in recs.values() for r in rs if r.get("ok")}
    todo = [j for j in jobs if key_of(j[0], j[3]) not in done]
    print(f"{len(models)} 模型 × {len(picked)} 题 = {len(jobs)} 次；已缓存 {len(jobs) - len(todo)}，待调用 {len(todo)}")

    if args.dry_run:
        total = 0.0
        for m in models:
            ok = [r for r in recs[m] if r.get("ok") and r.get("usage")]
            tin = statistics.mean(r["usage"]["input"] for r in ok) if ok else 2000
            tout = statistics.mean(r["usage"]["output"] for r in ok) if ok else 800
            n = sum(1 for j in todo if j[0] == m)
            pi, po = PRICE[m]
            c = n * (tin * pi + tout * po) / 1e6
            total += c
            print(f"  {m:<24} {n:>4} 次，按输入 {tin:.0f} / 输出 {tout:.0f} token（{'实测' if ok else '假设'}）粗估 {c:.2f} 元")
        print(f"  合计粗估 {total:.2f} 元（原价）")
        return

    if todo and not args.export_only:
        from openai import OpenAI
        load_env()
        client = OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"])
        raw.mkdir(parents=True, exist_ok=True)
        fh = {m: (raw / f"{m}.jsonl").open("a", encoding="utf-8") for m in models}
        n_err = 0
        try:
            with ThreadPoolExecutor(args.workers) as ex:
                futs = {ex.submit(call, client, m, p): (m, i) for m, i, g, p in todo}
                for fu in as_completed(futs):
                    m, i = futs[fu]
                    rec = {"key": key_of(m, items[i]["question"]), "model": m, "idx": i, **fu.result(),
                           "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
                    fh[m].write(json.dumps(rec, ensure_ascii=False) + "\n")
                    fh[m].flush()
                    if not rec["ok"]:
                        n_err += 1
                        print(f"  ! {m} #{i}：{rec['error']}")
        finally:
            for h in fh.values():
                h.close()
        print(f"本次失败 {n_err}")
        recs = {m: load(raw / f"{m}.jsonl") for m in models}
        done = {r["key"]: r for rs in recs.values() for r in rs if r.get("ok")}

    rows = []
    print(f"\n{'模型':<24} 完成 正确率 抽取失败 截断 平均输入 平均输出 思考 时延中位(s) 原价(元)")
    for m in models:
        rs = []
        for mm, i, g, p in jobs:
            if mm != m or key_of(m, p) not in done:
                continue
            r = done[key_of(m, p)]
            pred = extract(r["content"])
            rs.append((i, g, pred, r))
            rows.append({"model": m, "idx": i, "gold": g, "pred": pred or "", "correct": int(pred == g),
                         "extract_fail": int(pred is None), "finish_reason": r["finish_reason"],
                         "output_tokens": (r.get("usage") or {}).get("output"),
                         "served_model": r.get("served_model")})
        if not rs:
            continue
        u = [x[3].get("usage") or {} for x in rs]
        pi, po = PRICE[m]
        spent = sum((x.get("input") or 0) * pi + (x.get("output") or 0) * po for x in u) / 1e6
        print(f"{m:<24} {len(rs):>4} {sum(x[1] == x[2] for x in rs) / len(rs):>6.1%} {sum(x[2] is None for x in rs):>8}"
              f" {sum(x[3]['finish_reason'] == 'length' for x in rs):>4}"
              f" {statistics.mean(x.get('input') or 0 for x in u):>8.0f} {statistics.mean(x.get('output') or 0 for x in u):>8.0f}"
              f" {statistics.mean(x.get('reasoning') or 0 for x in u):>4.0f}"
              f" {statistics.median(x[3].get('latency_s') or 0 for x in rs):>11.1f} {spent:>8.3f}")
    if rows:
        OUT.mkdir(parents=True, exist_ok=True)
        with (OUT / "predictions.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"逐题结果 {len(rows)} 行 → {(OUT / 'predictions.csv').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
