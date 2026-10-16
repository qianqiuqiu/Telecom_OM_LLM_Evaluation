"""思考对照的客观题一侧：开思考答 150 道抽样客观题（orig 子集），与横评关思考的 orig 结果逐题配对。

- 抽样（STATUS 决定日志 Oct 15「思考对照预注册」）：731 题按「天花板（7 模型 × 5 子集 35 次全对）/ 其余」分两层，
  天花板层抽 50、其余层抽 100，层内按能力维度按比例分配（最大余数法），种子 20261015。
  抽样表 data/processed/thinking_mcq_sample.csv 首次运行生成，之后只读不改（换抽样须删表并在 STATUS 记录）。
- 提示：与关思考完全相同——取横评 orig 子集 EvalScope 记录里发出的 user 消息原文（无系统提示），
  只改思考开关与采样参数（configs/models.yaml 的 modes.on + 模型条目 params.on），max_tokens 16384（同思考试跑）。
- 抽取：调用 EvalScope 同一个 parse_answers，只看最终答案（content），不看推理过程；抽不出记错。
- 缓存与续跑：逐调用记录追加到 results/objective_thinking/raw/<模型>.jsonl（含原题文本，不入库）；
  键 = 模型 + 参数 + max_tokens + 提示的哈希；失败或答案为空的落盘为失败，下次运行重试。
- 输出（入库）：results/objective_thinking/answers_on.csv（逐题开思考结果）、off_orig.csv（同 150 题关思考 orig 结果，
  取自本地 results/evalscope/objective/，供分析复算）。

用法：
  uv run python scripts/run_objective_thinking.py --model qwen3.8-max-0902 --dry-run
  uv run python scripts/run_objective_thinking.py --model glm-5.2 --model deepseek-v4.1-flash
  uv run python scripts/run_objective_thinking.py --model qwen3.8-flash --budget 3   # 扣现金的模型加花费上限
  uv run python scripts/run_objective_thinking.py --export-only
"""
import argparse
import csv
import hashlib
import json
import random
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from types import SimpleNamespace

from evalscope.utils.multi_choices import parse_answers
from model_registry import stream_chat, load_cfg, make_client, params as model_params
from thinking_pilot import PRICE

ROOT = Path(__file__).resolve().parents[1]
REVIEWS = ROOT / "results/evalscope/objective"
SUBSET_CSV = ROOT / "data/processed/teleqna_test_subset.csv"
SAMPLE_CSV = ROOT / "data/processed/thinking_mcq_sample.csv"
OUT = ROOT / "results/objective_thinking"
SUBSETS = ["orig", "rep", "s1", "s2", "s3"]
SEED = 20261015
N_STRATUM = {"ceiling": 50, "other": 100}
MAX_TOKENS = 16384
OPENAI_PARAMS = ("temperature", "top_p", "presence_penalty", "frequency_penalty", "seed")
SPENT = {"cny": 0.0}
LOCK = threading.Lock()


# ---------- 关思考结果与抽样 ----------

def load_reviews(model, subset):
    """{qid: {"prompt", "target", "pred", "correct"}}"""
    path = REVIEWS / model / "reviews" / model / f"teleqna_mcq_{subset}.jsonl"
    out = {}
    for line in path.open(encoding="utf-8"):
        r = json.loads(line)
        sc = r["sample_score"]["score"]
        out[r["sample_score"]["sample_metadata"]["id"]] = {
            "prompt": r["messages"][0]["content"], "target": r["target"][0],
            "pred": (sc.get("extracted_prediction") or "").strip(), "correct": int(sc["value"]["accuracy"])}
    return out


def build_sample(main_models):
    meta = {r["id"]: r["dimension"] for r in csv.DictReader(SUBSET_CSV.open(encoding="utf-8"))}
    rev = {(m, s): load_reviews(m, s) for m in main_models for s in SUBSETS}
    total = {q: sum(rev[(m, s)][q]["correct"] for m in main_models for s in SUBSETS) for q in meta}
    full = len(main_models) * len(SUBSETS)
    strata = {q: ("ceiling" if total[q] == full else "other") for q in meta}
    rng = random.Random(SEED)
    rows = []
    for st, n in N_STRATUM.items():
        pool = defaultdict(list)
        for q in sorted(meta, key=lambda x: int(x.split()[-1])):
            if strata[q] == st:
                pool[meta[q]].append(q)
        size = sum(len(v) for v in pool.values())
        quota = {d: n * len(v) / size for d, v in pool.items()}
        alloc = {d: int(x) for d, x in quota.items()}
        for d in sorted(quota, key=lambda d: -(quota[d] - alloc[d]))[:n - sum(alloc.values())]:
            alloc[d] += 1
        for d in sorted(pool):
            for q in rng.sample(pool[d], alloc[d]):
                rows.append({"id": q, "stratum": st, "dimension": d, "stratum_size": size})
    SAMPLE_CSV.parent.mkdir(parents=True, exist_ok=True)
    with SAMPLE_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"抽样表已生成：{SAMPLE_CSV.relative_to(ROOT)}（" + "，".join(
        f"{st} {sum(r['stratum'] == st for r in rows)} 题 / 层内 {rows[[r['stratum'] for r in rows].index(st)]['stratum_size']}"
        for st in N_STRATUM) + "）")
    return rows


# ---------- 调用 ----------

def cache_key(model, params, prompt):
    blob = json.dumps([model, params, MAX_TOKENS, prompt], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def extract(content, prompt):
    n_opts = sum(1 for line in prompt.splitlines() if len(line) > 2 and line[1] == ")" and line[0].isupper())
    state = SimpleNamespace(choices=[None] * n_opts, output=SimpleNamespace(completion=content))
    return "".join(sorted(parse_answers(state, completion=content)))


def call(client, model, params, prompt):
    req = {"model": model, "max_tokens": MAX_TOKENS, "stream": True, "stream_options": {"include_usage": True},
           "messages": [{"role": "user", "content": prompt}],
           **{k: v for k, v in params.items() if k in OPENAI_PARAMS}}
    extra = {k: v for k, v in params.items() if k not in OPENAI_PARAMS}
    return stream_chat(client, req, extra)


def tokens(usage):
    u = usage or {}
    return (u.get("prompt_tokens") or 0, u.get("completion_tokens") or 0,
            (u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)


def cost(model, usage):
    tin, tout, _ = tokens(usage)
    pi, po = PRICE[model]
    return round((tin * pi + tout * po) / 1e6, 5)


def run_one(client, model, params, qid, item, key, budget, attempts=3):
    if budget is not None:
        with LOCK:
            if SPENT["cny"] >= budget:
                return None
    rec = {"key": key, "model": model, "params": params, "max_tokens": MAX_TOKENS, "id": qid, "gold": item["target"]}
    err = ""
    for a in range(1, attempts + 1):
        try:
            res = call(client, model, params, item["prompt"])
        except Exception as e:  # noqa: BLE001  限流、网络：退避重试，最后仍失败则落盘
            err = f"{type(e).__name__}: {e}"[:400]
            if a < attempts:
                time.sleep(2 ** a)
            continue
        ok = bool(res["content"].strip())
        rec.update(res, ok=ok, attempts=a, cost_cny=cost(model, res["usage"]),
                   pred=extract(res["content"], item["prompt"]) if ok else "",
                   ts=time.strftime("%Y-%m-%d %H:%M:%S"))
        if not ok:
            rec["error"] = f"答案为空（finish_reason={res['finish_reason']}）"
        break
    else:
        rec.update(ok=False, attempts=attempts, error=err, cost_cny=0.0, ts=time.strftime("%Y-%m-%d %H:%M:%S"))
    with LOCK:
        SPENT["cny"] += rec["cost_cny"]
    return rec


def load_records(model):
    path = OUT / "raw" / f"{model}.jsonl"
    recs = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return recs


# ---------- 导出 ----------

def export(cfg, sample, prompts, main_models):
    on_rows, models = [], [m["id"] for g in ("main", "thinking_only") for m in cfg[g]]
    for m in models:
        recs = load_records(m)
        if not recs:
            continue
        p = model_params(cfg, m, "on")
        done = {r["key"]: r for r in recs if r["ok"]}
        for s in sample:
            r = done.get(cache_key(m, p, prompts[s["id"]]["prompt"]))
            if r is None:
                continue
            tin, tout, think = tokens(r["usage"])
            on_rows.append({"model": m, "id": s["id"], "stratum": s["stratum"], "dimension": s["dimension"],
                            "gold": r["gold"], "pred": r["pred"], "correct": int(r["pred"] == r["gold"]),
                            "finish_reason": r["finish_reason"], "prompt_tokens": tin, "completion_tokens": tout,
                            "reasoning_tokens": think, "ttfa_s": r["ttfa_s"], "latency_s": r["latency_s"],
                            "cost_cny": r["cost_cny"]})
    OUT.mkdir(parents=True, exist_ok=True)
    if on_rows:
        with (OUT / "answers_on.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(on_rows[0]))
            w.writeheader()
            w.writerows(on_rows)
    off_rows = []
    for m in main_models:
        rev = load_reviews(m, "orig")
        preds = {}
        path = REVIEWS / m / "predictions" / m / "teleqna_mcq_orig.jsonl"
        for line in path.open(encoding="utf-8"):
            r = json.loads(line)
            u = r["model_output"].get("usage") or {}
            preds[r["metadata"]["id"]] = (u.get("input_tokens"), u.get("output_tokens"), r["model_output"].get("time"))
        for s in sample:
            q = s["id"]
            tin, tout, lat = preds.get(q, (None, None, None))
            off_rows.append({"model": m, "id": q, "stratum": s["stratum"], "dimension": s["dimension"],
                             "gold": rev[q]["target"], "pred": rev[q]["pred"], "correct": rev[q]["correct"],
                             "prompt_tokens": tin, "completion_tokens": tout, "latency_s": lat})
    with (OUT / "off_orig.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(off_rows[0]))
        w.writeheader()
        w.writerows(off_rows)
    by = Counter(r["model"] for r in on_rows)
    print(f"导出：answers_on.csv {len(on_rows)} 行（" + "，".join(f"{m} {k}" for m, k in by.items()) + "）；off_orig.csv")


# ---------- 主流程 ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", action="append", default=[])
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, help="只取前 N 题（冒烟用）")
    ap.add_argument("--budget", type=float, help="本次调用按原价累计的花费上限（元）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--export-only", action="store_true")
    args = ap.parse_args()

    cfg = load_cfg()
    main_models = [m["id"] for m in cfg["main"]]
    if SAMPLE_CSV.exists():
        sample = list(csv.DictReader(SAMPLE_CSV.open(encoding="utf-8")))
    else:
        sample = build_sample(main_models)
    prompts = load_reviews(main_models[0], "orig")
    if args.export_only:
        export(cfg, sample, prompts, main_models)
        return
    items = sample[:args.limit] if args.limit else sample

    for m in args.model:
        p = model_params(cfg, m, "on")
        recs = load_records(m)
        done = {r["key"] for r in recs if r["ok"]}
        todo = [(s["id"], cache_key(m, p, prompts[s["id"]]["prompt"])) for s in items]
        todo = [(q, k) for q, k in todo if k not in done]
        ok_prev = [r for r in recs if r["ok"]]
        est_out = sum(tokens(r["usage"])[1] for r in ok_prev) / len(ok_prev) if ok_prev else 2500
        pi, po = PRICE[m]
        print(f"{m}：{len(items)} 题，已缓存 {len(items) - len(todo)}，待调用 {len(todo)}，参数 {p}；"
              f"按输出 {est_out:.0f} token 粗估 {len(todo) * (140 * pi + est_out * po) / 1e6:.2f} 元")
        if args.dry_run or not todo:
            continue
        client = make_client(cfg, m)
        (OUT / "raw").mkdir(parents=True, exist_ok=True)
        n_ok = n_err = n_skip = 0
        spent0 = SPENT["cny"]
        with (OUT / "raw" / f"{m}.jsonl").open("a", encoding="utf-8") as h, ThreadPoolExecutor(args.workers) as ex:
            futs = [ex.submit(run_one, client, m, p, q, prompts[q], k, args.budget) for q, k in todo]
            for fu in as_completed(futs):
                rec = fu.result()
                if rec is None:
                    n_skip += 1
                    continue
                h.write(json.dumps(rec, ensure_ascii=False) + "\n")
                h.flush()
                if rec["ok"]:
                    n_ok += 1
                else:
                    n_err += 1
                    print(f"  ! {m} {rec['id']}：{rec['error']}")
        print(f"  本次成功 {n_ok}，失败 {n_err}，按原价约 {SPENT['cny'] - spent0:.3f} 元"
              + (f"；到预算上限未发 {n_skip} 个" if n_skip else ""))
    if not args.dry_run:
        export(cfg, sample, prompts, main_models)


if __name__ == "__main__":
    main()
