"""TeleLogs 子集（Spec「故障诊断的客观参照」）：5G 路测数据根因分析，8 类根因，规则判分，不依赖 judge。

- 题目：data/raw/TeleLogs/troubleshooting/test.json（864 题，8 类各 108 题）中按类分层抽 200 题
  （每类 25 题，种子 20261015），题号 = 测试集中的下标，清单写入 data/processed/telelogs_sample.csv（只有题号与类别）。
- 调用：7 个主实验模型，关思考、温度 0；只发原题文本（题面自带「把编号写进 \\boxed{}」的要求），不加系统提示。
- 判分：取回答里最后一个 \\boxed{...}，从中抽 C1–C8（也接受只写数字）；抽不到记错，抽取失败在汇总里单列。
  被截断（finish_reason = length）的回答照常判分并计数。
- 缓存：results/telelogs/raw/<模型>.jsonl（含原文，不入库）；逐题结果 results/telelogs/predictions.csv（入库）。
- 开思考对照（--thinking，STATUS 第二节第 9 项，Oct 16 定）：kimi-k3 经 OpenCode Go（Chat Completions，模型 ID 记为
  kimi-k3-ocgo）× 50 题子样本（从 200 题里按类分层：C1 / C2 各 7、其余 6 类各 6，种子 20261016，
  清单 data/processed/telelogs_sub50.csv）。K3 恒开思考、温度与 top_p 由厂商固定（1.0 / 0.95，传别的值会报错），
  所以不传采样参数；思考强度 reasoning_effort = low（官方可选 low / high / max，默认 max；用户定只作参考、调低）；
  max_tokens 16384。关思考一侧复用 predictions.csv 里百炼的 kimi-k3。
  花费按 Go 价目折美元累计，超过 --budget-usd 就不再发新请求；Go 返回限额错误（429 / limit）立即停，窗口重置后重跑续上。
  缓存 raw/kimi-k3-ocgo__on.jsonl，逐题结果 predictions_thinking.csv（入库）。

用法：
  uv run python scripts/run_telelogs.py --dry-run
  uv run python scripts/run_telelogs.py --limit 2                 # 试跑：每个模型 2 题，看输出长度
  uv run python scripts/run_telelogs.py                           # 全量
  uv run python scripts/run_telelogs.py --export-only
  uv run python scripts/run_telelogs.py --thinking --limit 3 --budget-usd 1   # 开思考试跑
  uv run python scripts/run_telelogs.py --thinking --budget-usd 7             # 开思考 50 题
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
SUB = ROOT / "data/processed/telelogs_sub50.csv"
SUB_SEED = 20261016
SUB_N = {"C1": 7, "C2": 7}  # 其余类各 6
GO_BASE = "https://opencode.ai/inference/go/v1"
GO_MODEL = {"kimi-k3-ocgo": "kimi-k3"}
GO_PRICE_USD = {"kimi-k3-ocgo": (3.0, 15.0, 0.30)}  # 输入 / 输出 / 缓存命中，每百万 token（Go 文档）
THINK_MAX_TOKENS = 16384
REASONING_EFFORT = "low"

_BOXED = re.compile(r"\\boxed\{+\s*([^{}]*?)\s*\}+")
# Oct 16 事后修正（看过 kimi-k3 开思考结果后）：允许 \boxed 里嵌一层花括号，如 \boxed{\text{C4}}、\boxed{\mathrm{C2}}；
# 原正则不认嵌套，这类答案被记为抽取失败。已核对主实验全部原始回答（5 个模型 × 200 题，另有两个 qwen 的试跑），改前改后抽取结果完全一致。
_BOXED_NESTED = re.compile(r"\\boxed\{((?:[^{}]|\{[^{}]*\})*)\}")
_WRAP = re.compile(r"\\(?:text|mathrm|textbf|mathbf)\{([^{}]*)\}")


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


def sub50(picked):
    """从 200 题抽样里按类分层取 50 题；单个 rng 按类名顺序、类内按题号排序后抽。"""
    if SUB.exists():
        return [(int(r["idx"]), r["gold"]) for r in csv.DictReader(SUB.open(encoding="utf-8"))]
    by = defaultdict(list)
    for i, g in picked:
        by[g].append(i)
    rng = random.Random(SUB_SEED)
    out = sorted((i, c) for c in sorted(by) for i in rng.sample(sorted(by[c]), SUB_N.get(c, 6)))
    with SUB.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["idx", "gold"])
        w.writerows(out)
    return out


def gold_of(it):
    m = re.search(r"C\s*([1-8])", str(it["answer"]))
    return f"C{m.group(1)}"


def extract(text, strict=False):
    """strict=True 是跑之前定的原规则（不认嵌套），只用于开思考对照的敏感性分析。"""
    hits = (_BOXED if strict else _BOXED_NESTED).findall(text or "")
    if not hits:
        return None
    m = re.search(r"C?\s*([1-8])\b", _WRAP.sub(r"\1", hits[-1]), re.I)
    return f"C{m.group(1)}" if m else None


def key_of(model, prompt):
    if model in GO_MODEL:
        return hashlib.sha256(json.dumps([model, prompt, THINK_MAX_TOKENS, "on", REASONING_EFFORT], ensure_ascii=False).encode()).hexdigest()[:16]
    return hashlib.sha256(json.dumps([model, prompt, MAX_TOKENS, "off", 0], ensure_ascii=False).encode()).hexdigest()[:16]


def go_cost(model, u):
    pi, po, pc = GO_PRICE_USD[model]
    cached = u.get("cached") or 0
    return ((u["input"] - cached) * pi + cached * pc + u["output"] * po) / 1e6


def call_go(client, model, prompt, attempts=3):
    """开思考，流式（model_registry.stream_chat 的看门狗）；Go 的限额错误抛 UsageLimit，不重试。"""
    from model_registry import stream_chat
    err = None
    req = {"model": GO_MODEL[model], "max_tokens": THINK_MAX_TOKENS, "stream": True,
           "stream_options": {"include_usage": True}, "reasoning_effort": REASONING_EFFORT,
           "messages": [{"role": "user", "content": prompt}]}
    for a in range(1, attempts + 1):
        try:
            r = stream_chat(client, req, {}, stall_s=300, total_s=3600)
        except Exception as e:  # noqa: BLE001
            msg = f"{type(e).__name__}: {e}"[:300]
            if re.search(r"429|usage limit|rate limit|limit exceeded|quota", msg, re.I):
                raise UsageLimit(msg) from None
            err = msg
            time.sleep(2 ** a)
            continue
        u = r["usage"] or {}
        det = u.get("completion_tokens_details") or {}
        return {"ok": True, "content": r["content"], "reasoning": r["reasoning"], "served_model": r["served_model"],
                "finish_reason": r["finish_reason"], "latency_s": r["latency_s"], "ttfa_s": r["ttfa_s"],
                "usage": {"input": u.get("prompt_tokens") or 0, "output": u.get("completion_tokens") or 0,
                          "reasoning": det.get("reasoning_tokens") or 0,
                          "cached": (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0}}
    return {"ok": False, "error": err}


class UsageLimit(Exception):
    pass


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
    ap.add_argument("--thinking", action="store_true", help="kimi-k3 经 OpenCode Go 开思考 × 50 题子样本")
    ap.add_argument("--budget-usd", type=float, default=7.0, help="--thinking 的花费上限（按 Go 价目折美元）")
    args = ap.parse_args()

    cfg = yaml.safe_load(MODELS.read_text(encoding="utf-8"))
    models = args.model or [m["id"] for m in cfg["main"]]
    items, picked = sample()
    if args.thinking:
        return run_thinking(args, items, picked)
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


def run_thinking(args, items, picked):
    import threading

    from openai import OpenAI
    model = "kimi-k3-ocgo"
    sub = sub50(picked)
    sub = sub[:args.limit] if args.limit else sub
    path = OUT / "raw" / f"{model}__on.jsonl"
    recs = load(path)
    done = {r["key"]: r for r in recs if r.get("ok")}
    spent = sum(go_cost(model, r["usage"]) for r in recs if r.get("ok") and r.get("usage"))
    todo = [(i, g) for i, g in sub if key_of(model, items[i]["question"]) not in done]
    print(f"{model} 开思考 × {len(sub)} 题；已缓存 {len(sub) - len(todo)}，待调用 {len(todo)}；"
          f"已花 ${spent:.2f} / 上限 ${args.budget_usd:.2f}")
    if args.dry_run:
        return
    if todo and not args.export_only:
        load_env()
        client = OpenAI(base_url=GO_BASE, api_key=os.environ["OPENCODE_API_KEY"], timeout=180,
                        default_headers={"User-Agent": "telecom-om-eval/0.1"})
        lock, stop, cost = threading.Lock(), threading.Event(), [spent]
        path.parent.mkdir(parents=True, exist_ok=True)

        def job(i):
            if stop.is_set():
                return None
            with lock:
                if cost[0] >= args.budget_usd:
                    stop.set()
                    print(f"  已花 ${cost[0]:.2f}，达到上限，不再发新请求")
                    return None
            # Go 要求每个对话带固定的 x-opencode-session；这里每次调用是一个对话
            c = client.with_options(default_headers={"User-Agent": "telecom-om-eval/0.1",
                                                     "x-opencode-session": hashlib.sha256(str(i).encode()).hexdigest()[:32]})
            try:
                return call_go(c, model, items[i]["question"])
            except UsageLimit as e:
                stop.set()
                print(f"  ! Go 限额：{e}")
                return None

        with path.open("a", encoding="utf-8") as fh, ThreadPoolExecutor(min(args.workers, 4)) as ex:
            futs = {ex.submit(job, i): i for i, g in todo}
            for fu in as_completed(futs):
                i, res = futs[fu], fu.result()
                if res is None:
                    continue
                rec = {"key": key_of(model, items[i]["question"]), "model": model, "idx": i, **res,
                       "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
                if rec["ok"]:
                    with lock:
                        cost[0] += go_cost(model, rec["usage"])
                    u = rec["usage"]
                    print(f"  #{i} {rec['finish_reason']} 输出 {u['output']}（思考 {u['reasoning']}）"
                          f" 预测 {extract(rec['content'])} 累计 ${cost[0]:.2f}")
                else:
                    print(f"  ! #{i}：{rec['error']}")
        recs = load(path)
        done = {r["key"]: r for r in recs if r.get("ok")}

    rows = []
    for i, g in sub:
        r = done.get(key_of(model, items[i]["question"]))
        if not r:
            continue
        pred = extract(r["content"])
        strict = extract(r["content"], strict=True)
        rows.append({"model": model, "idx": i, "gold": g, "pred": pred or "", "correct": int(pred == g),
                     "extract_fail": int(pred is None), "pred_strict": strict or "", "correct_strict": int(strict == g),
                     "finish_reason": r["finish_reason"], "output_tokens": r["usage"]["output"], "reasoning_tokens": r["usage"]["reasoning"],
                     "input_tokens": r["usage"]["input"], "cost_usd": round(go_cost(model, r["usage"]), 5),
                     "latency_s": r.get("latency_s"), "served_model": r.get("served_model")})
    print(f"完成 {len(rows)}/{len(sub)}，正确 {sum(x['correct'] for x in rows)}，"
          f"截断 {sum(x['finish_reason'] == 'length' for x in rows)}，抽取失败 {sum(x['extract_fail'] for x in rows)}，"
          f"累计 ${sum(x['cost_usd'] for x in rows):.2f}")
    if rows:
        with (OUT / "predictions_thinking.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"逐题结果 → {(OUT / 'predictions_thinking.csv').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
