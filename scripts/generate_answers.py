"""场景题回答生成：被测模型答场景题，输出 judge_scenarios.py 直接能读的回答文件。

天花板试跑（STATUS 第二节第 3 步）与正式生成（第 6 步：7 模型关思考、思考对照）共用这一个脚本。

- 只给题干（题目的 prompt 字段）；所有模型用同一段系统提示 configs/assistant/system_<版本>.md，
  不透露参考答案、评分要点等任何评分信息。
- 思考开关与采样参数取 configs/models.yaml：modes 下是全局参数，模型条目可用 params: {"on": {...}} 覆盖
  （开思考时各厂商推荐的采样参数，见 STATUS D4）。只能开思考的模型（thinking_only）不跑 off。
  temperature / top_p 等 OpenAI 标准参数放请求体，其余（enable_thinking、top_k 等）放 extra_body。
- 每次调用记录：最终答案、推理过程、token 用量（含思考 token）、首 token 时延（含推理）、
  首个答案 token 时延、总时延、结束原因、实际返回的模型名、按原价折算的花费（元）。
- 缓存与续跑：调用记录追加写入 results/answers/raw/<模型>__<mode>.jsonl；
  缓存键 = 系统提示 + 模型 + mode 参数 + max_tokens + 题干 + 重复序号的哈希，任何一项变了就重答。
  已有成功记录的直接复用：题目与参数都不变时，试跑的回答会被正式生成复用。
  报错或答案为空的调用落盘记为失败，下次运行自动重试，不会被悄悄剔除。
- 输出：results/answers/<run>.jsonl（入库：生成在 Mac 上跑，判分在云端会话里跑，靠仓库传递；raw/ 缓存不入库），每行
  {"answer_id", "scenario_id", "source", "text", "model", "mode", "repeat", "finish_reason"}，
  source = <模型>:<mode>；只含本次范围内的成功记录。截断（finish_reason = length）的回答照常导出，在汇总里计数。

用法：
  uv run python scripts/generate_answers.py --run ceiling_pilot \\
      --model qwen3.8-flash --model deepseek-v4.1-flash --mode off            # 天花板试跑
  ... --run main_off --group main --mode off                                  # 正式：7 模型关思考
  ... --run thinking_on --group main --group thinking_only --exclude kimi-k3 --mode on --repeats 3
  ... --dry-run          # 只打印将发送的提示、调用次数与粗估花费，不调用
  ... --export-only      # 不调用，只按已落盘记录重新导出回答文件与汇总
"""
import argparse
import hashlib
import json
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml
from thinking_pilot import PRICE
from verify_three_vote import load_env

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "data/scenarios/scenarios_draft.json"
MODELS = ROOT / "configs/models.yaml"
SYSTEMS = ROOT / "configs/assistant"
OUT = ROOT / "results/answers"

MAX_TOKENS = {"off": 4096, "on": 16384}  # on 与思考试跑一致；截断在汇总里计数
OPENAI_PARAMS = ("temperature", "top_p", "presence_penalty", "frequency_penalty", "seed")
GUESS = {"off": (800, 1500), "on": (800, 6000)}  # 粗估花费的（输入, 输出）token；有落盘记录时改用实测均值


# ---------- 模型与任务 ----------

def resolve_models(cfg, args):
    """返回 [(模型 ID, 该 mode 的参数)]；只认 configs/models.yaml 里的模型。"""
    entries = {m["id"]: (g, m) for g in ("main", "thinking_only") for m in cfg[g]}
    ids = list(args.model or []) + [m["id"] for g in args.group or [] for m in cfg[g]]
    unknown = [i for i in ids if i not in entries]
    if unknown:
        raise SystemExit(f"不在 configs/models.yaml 里的模型：{unknown}")
    ids = [i for i in dict.fromkeys(ids) if i not in args.exclude]
    if args.mode == "off":
        only_on = [i for i in ids if entries[i][0] == "thinking_only"]
        if only_on:
            print(f"只能开思考，不跑 off：{only_on}")
        ids = [i for i in ids if i not in only_on]
    if not ids:
        raise SystemExit("没有要跑的模型（用 --model 或 --group 指定）")
    return [(i, {**cfg["modes"][args.mode], **((entries[i][1].get("params") or {}).get(args.mode) or {})})
            for i in ids]


def cache_key(system, model, mode, params, max_tokens, prompt, repeat):
    blob = json.dumps([system, model, mode, params, max_tokens, prompt, repeat], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def log_path(model, mode):
    return OUT / "raw" / f"{model}__{mode}.jsonl"


def load_records(path):
    recs = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return recs


def tokens(usage):
    u = usage or {}
    return (u.get("prompt_tokens") or 0, u.get("completion_tokens") or 0,
            (u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)


def cost(model, usage):
    tin, tout, _ = tokens(usage)
    pi, po = PRICE[model]
    return round((tin * pi + tout * po) / 1e6, 5)


# ---------- 调用 ----------

def call(client, model, params, max_tokens, system, prompt):
    req = {"model": model, "max_tokens": max_tokens, "stream": True, "stream_options": {"include_usage": True},
           "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
           **{k: v for k, v in params.items() if k in OPENAI_PARAMS}}
    extra = {k: v for k, v in params.items() if k not in OPENAI_PARAMS}
    out = {"content": "", "reasoning": "", "finish_reason": None, "served_model": None, "usage": None,
           "ttft_s": None, "ttfa_s": None}
    t0 = time.monotonic()
    for chunk in client.chat.completions.create(**req, extra_body=extra):
        out["served_model"] = chunk.model or out["served_model"]
        if chunk.usage:
            out["usage"] = chunk.usage.model_dump()
        for ch in chunk.choices:
            c, r = ch.delta.content or "", getattr(ch.delta, "reasoning_content", None) or ""
            now = round(time.monotonic() - t0, 2)
            if (c or r) and out["ttft_s"] is None:
                out["ttft_s"] = now  # 首 token（含推理）
            if c and out["ttfa_s"] is None:
                out["ttfa_s"] = now  # 首个答案 token：用户看到回答开始的时间
            out["content"] += c
            out["reasoning"] += r
            out["finish_reason"] = ch.finish_reason or out["finish_reason"]
    out["latency_s"] = round(time.monotonic() - t0, 2)
    return out


def run_one(client, job, system, system_ver, attempts=3):
    model, mode, params, max_tokens, scn, k, key = job
    rec = {"key": key, "model": model, "mode": mode, "params": params, "max_tokens": max_tokens,
           "system": system_ver, "scenario_id": scn["id"], "repeat": k}
    for a in range(1, attempts + 1):
        try:
            res = call(client, model, params, max_tokens, system, scn["prompt"])
        except Exception as e:  # noqa: BLE001  限流、网络等：退避重试，最后一次仍失败则落盘
            err = f"{type(e).__name__}: {e}"[:400]
            if a < attempts:
                time.sleep(2 ** a)
            continue
        ok = bool(res["content"].strip())  # 答案为空（如思考耗尽 max_tokens）不重试，落盘为失败，下次运行再试
        return {**rec, **res, "ok": ok, "attempts": a, "cost_cny": cost(model, res["usage"]),
                **({} if ok else {"error": f"答案为空（finish_reason={res['finish_reason']}）"}),
                "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
    return {**rec, "ok": False, "attempts": attempts, "error": err, "cost_cny": 0.0,
            "ts": time.strftime("%Y-%m-%d %H:%M:%S")}


# ---------- 汇总 ----------

def med(xs):
    xs = [x for x in xs if x is not None]
    return f"{statistics.median(xs):.1f}" if xs else "—"


def summarize(jobs, recs_by_key, done, models, mode):
    print(f"\n{'模型:mode':<28} 完成 失败 未完成 截断 平均输入 平均输出 平均思考 回答字数"
          f" 首token(s) 首答案(s) 总时延(s) 花费(元)")
    total = 0.0
    for model, _ in models:
        js = [j for j in jobs if j[0] == model]
        ok = [done[j[6]] for j in js if j[6] in done]
        failed = sum(1 for j in js if j[6] not in done and any(not r["ok"] for r in recs_by_key.get(j[6], [])))
        spent = sum(r["cost_cny"] for r in ok)
        total += spent
        n = max(len(ok), 1)
        tin, tout, think = (sum(tokens(r["usage"])[i] for r in ok) / n for i in range(3))
        print(f"{model + ':' + mode:<28} {len(ok):>4} {failed:>4} {len(js) - len(ok):>7}"
              f" {sum(r['finish_reason'] == 'length' for r in ok):>4} {tin:>8.0f} {tout:>8.0f} {think:>8.0f}"
              f" {sum(len(r['content']) for r in ok) / n:>8.0f} {med(r['ttft_s'] for r in ok):>10}"
              f" {med(r['ttfa_s'] for r in ok):>9} {med(r['latency_s'] for r in ok):>9} {spent:>8.3f}")
    print(f"范围内成功记录按原价折算合计约 {total:.2f} 元（DeepSeek 按白天价，夜间 22:00–8:00 半价）")


def estimate(jobs, recs_by_model, models, mode):
    total = 0.0
    for model, _ in models:
        n = sum(1 for j in jobs if j[0] == model)
        ok = [r for r in recs_by_model[model] if r["ok"]]
        tin, tout = (statistics.mean(tokens(r["usage"])[i] for r in ok) for i in range(2)) if ok else GUESS[mode]
        pi, po = PRICE[model]
        c = n * (tin * pi + tout * po) / 1e6
        total += c
        print(f"  {model:<24} 待调用 {n:>4} 次，每次按输入 {tin:.0f} / 输出 {tout:.0f} token"
              f"（{'已有记录实测均值' if ok else '假设'}）粗估 {c:.2f} 元")
    print(f"  合计粗估 {total:.2f} 元（原价）")


# ---------- 主流程 ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="导出文件名：results/answers/<run>.jsonl")
    ap.add_argument("--model", action="append", help="模型 ID，须在 configs/models.yaml 里；可重复")
    ap.add_argument("--group", action="append", choices=["main", "thinking_only"], help="models.yaml 分组；可重复")
    ap.add_argument("--exclude", action="append", default=[])
    ap.add_argument("--mode", required=True, choices=["off", "on"])
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--system", default="v1", help="configs/assistant/system_<版本>.md")
    ap.add_argument("--max-tokens", type=int, help=f"默认 off {MAX_TOKENS['off']}、on {MAX_TOKENS['on']}")
    ap.add_argument("--scenarios", type=Path, default=SCENARIOS)
    ap.add_argument("--ids", nargs="+", help="只答这些题")
    ap.add_argument("--limit", type=int, help="只取前 N 题（冒烟用）")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--export-only", action="store_true")
    args = ap.parse_args()

    cfg = yaml.safe_load(MODELS.read_text(encoding="utf-8"))
    models = resolve_models(cfg, args)
    if args.mode == "on" and any("temperature" not in p for _, p in models):
        print("注意：开思考的采样参数未在 configs/models.yaml 填写（STATUS D4），未填的模型用服务端默认值")
    system = (SYSTEMS / f"system_{args.system}.md").read_text(encoding="utf-8").strip()
    max_tokens = args.max_tokens or MAX_TOKENS[args.mode]

    scns = json.loads(args.scenarios.read_text(encoding="utf-8"))
    if args.ids:
        unknown = sorted(set(args.ids) - {q["id"] for q in scns})
        if unknown:
            raise SystemExit(f"题库中不存在的题目：{unknown}")
        scns = [q for q in scns if q["id"] in args.ids]
    scns = scns[:args.limit] if args.limit else scns

    jobs = [(m, args.mode, p, max_tokens, q, k, cache_key(system, m, args.mode, p, max_tokens, q["prompt"], k))
            for m, p in models for q in scns for k in range(args.repeats)]
    recs_by_model = {m: load_records(log_path(m, args.mode)) for m, _ in models}
    done = {r["key"]: r for rs in recs_by_model.values() for r in rs if r["ok"]}
    todo = [j for j in jobs if j[6] not in done]
    print(f"{len(models)} 个模型 × {len(scns)} 题 × {args.repeats} 次 = {len(jobs)} 次（mode={args.mode}，"
          f"max_tokens={max_tokens}，系统提示 {args.system}）；已缓存 {len(jobs) - len(todo)}，待调用 {len(todo)}")

    if args.dry_run:
        print("=== system ===\n" + system + "\n=== user（第 1 题）===\n" + scns[0]["prompt"])
        for m, p in models:
            print(f"  {m}: {p}")
        estimate(todo, recs_by_model, models, args.mode)
        return

    if todo and not args.export_only:
        from openai import OpenAI
        load_env()
        client = OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"])
        (OUT / "raw").mkdir(parents=True, exist_ok=True)
        handles = {m: log_path(m, args.mode).open("a", encoding="utf-8") for m, _ in models}
        n_ok = n_err = 0
        spent = 0.0
        try:
            with ThreadPoolExecutor(args.workers) as ex:
                futs = [ex.submit(run_one, client, j, system, args.system) for j in todo]
                for fu in as_completed(futs):
                    rec = fu.result()
                    handles[rec["model"]].write(json.dumps(rec, ensure_ascii=False) + "\n")
                    handles[rec["model"]].flush()
                    spent += rec["cost_cny"]
                    if rec["ok"]:
                        n_ok += 1
                    else:
                        n_err += 1
                        print(f"  ! {rec['model']} {rec['scenario_id']} r{rec['repeat']}：{rec['error']}")
        finally:
            for h in handles.values():
                h.close()
        print(f"本次：成功 {n_ok}，失败 {n_err}，本次调用按原价约 {spent:.3f} 元")
        recs_by_model = {m: load_records(log_path(m, args.mode)) for m, _ in models}
        done = {r["key"]: r for rs in recs_by_model.values() for r in rs if r["ok"]}

    rows = []
    for m, mode, _, _, q, k, key in jobs:
        if key in done:
            r = done[key]
            rows.append({"answer_id": f"{m}:{mode}:{q['id']}:r{k}", "scenario_id": q["id"], "source": f"{m}:{mode}",
                         "text": r["content"], "model": m, "mode": mode, "repeat": k,
                         "finish_reason": r["finish_reason"]})
    out = OUT / f"{args.run}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")

    recs_by_key = {}
    for rs in recs_by_model.values():
        for r in rs:
            recs_by_key.setdefault(r["key"], []).append(r)
    summarize(jobs, recs_by_key, done, models, args.mode)
    print(f"回答文件：{out.relative_to(ROOT)}（{len(rows)}/{len(jobs)} 条）")


if __name__ == "__main__":
    main()
