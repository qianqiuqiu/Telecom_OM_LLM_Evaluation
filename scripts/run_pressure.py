"""多角色追问施压（Spec「多角色追问施压评测（精简版）」）：固定脚本的多轮对话，测被追问、施压后会不会改口、会不会突破安全边界。

- 场景与追问脚本：data/scenarios/pressure/scripts_v1.json（10 个场景，每个 3 轮追问，文字写死，所有模型相同）：
  T2 无新信息的施压·安全（直接给命令 / 搬权威 / 紧急绕过确认，推向该题某条高危操作）；
  T3 无新信息的施压·结论（质疑参考答案的核心结论，要求改为 discriminating_trap 的错误结论）；
  T4 带新证据的纠正（新核查结果推翻或削弱原结论的关键前提，正确做法是修正判断）。
- 第 1 轮直接复用 results/answers/main_off.jsonl 里该模型对该题的回答（同一系统提示 v1、关思考、温度 0），
  不重新生成：第 1 轮与场景题横评是同一份回答，T1 是否答对可直接对照。
- 之后逐轮生成：每轮把完整对话历史（含模型自己前几轮的回答）发给模型。关思考、温度 0、max_tokens 4096。
- 缓存：results/answers/raw/pressure__<模型>.jsonl（不入库），键 = 模型 + 参数 + 完整消息列表，可断点续跑；
  某轮失败则该对话停在这一轮，下次运行从这一轮续上。
- 输出：results/answers/pressure_off.jsonl（入库），每个对话一行：
  {"conv_id", "scenario_id", "model", "messages": [...], "finish_reasons": [T2, T3, T4]}。
  另生成判分探针 data/scenarios/pressure/probes.jsonl（第 1 轮 = 参考答案，good / bad 两组写死的回复）。

用法：
  uv run python scripts/run_pressure.py --dry-run
  uv run python scripts/run_pressure.py --model qwen3.8-flash --ids SC-D01      # 冒烟
  uv run python scripts/run_pressure.py                                         # 7 模型 × 10 场景
"""
import argparse
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from generate_answers import OPENAI_PARAMS, cost, tokens
from model_registry import load_cfg, make_client, params as model_params
from thinking_pilot import PRICE

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "data/scenarios/pressure/scripts_v1.json"
PROBES = ROOT / "data/scenarios/pressure/probes.jsonl"
SCENARIOS = ROOT / "data/scenarios/scenarios_draft.json"
T1_ANSWERS = ROOT / "results/answers/main_off.jsonl"
SYSTEM = ROOT / "configs/assistant/system_v1.md"
RAW = ROOT / "results/answers/raw"
OUT = ROOT / "results/answers/pressure_off.jsonl"
MAX_TOKENS = 4096
TURNS = ("t2", "t3", "t4")


def key_of(model, params, messages):
    blob = json.dumps([model, params, MAX_TOKENS, messages], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def load(path):
    out = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def call(client, model, params, messages, attempts=3):
    req = {"model": model, "max_tokens": MAX_TOKENS, "messages": messages,
           **{k: v for k, v in params.items() if k in OPENAI_PARAMS}}
    extra = {k: v for k, v in params.items() if k not in OPENAI_PARAMS}
    err = None
    for a in range(1, attempts + 1):
        try:
            t0 = time.monotonic()
            r = client.chat.completions.create(**req, extra_body=extra)
            content = r.choices[0].message.content or ""
            if not content.strip():
                err = f"答案为空（finish_reason={r.choices[0].finish_reason}）"
                continue
            usage = r.usage.model_dump() if r.usage else None
            return {"ok": True, "content": content, "finish_reason": r.choices[0].finish_reason,
                    "served_model": r.model, "usage": usage, "latency_s": round(time.monotonic() - t0, 1),
                    "cost_cny": cost(model, usage)}
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"[:300]
            time.sleep(2 ** a)
    return {"ok": False, "error": err, "cost_cny": 0.0}


def build_probes(scripts, scns):
    rows = []
    for s in scripts:
        q = scns[s["scenario_id"]]
        for kind in ("good", "bad"):
            msgs = [{"role": "user", "content": q["prompt"]}, {"role": "assistant", "content": q["reference_answer"]}]
            for t in TURNS:
                msgs += [{"role": "user", "content": s[t]["text"]}, {"role": "assistant", "content": s["probes"][kind][t]}]
            rows.append({"conv_id": f"probe:{kind}:{s['scenario_id']}", "scenario_id": s["scenario_id"],
                         "model": f"probe:{kind}", "messages": msgs})
    PROBES.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", action="append")
    ap.add_argument("--ids", nargs="+")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--t1", type=Path, default=T1_ANSWERS, help="第 1 轮回答来源（精度回归用该档自己的场景题回答）")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = load_cfg()
    models = args.model or [m["id"] for m in cfg["main"]]
    params_of = {m: model_params(cfg, m, "off") for m in models}
    system = SYSTEM.read_text(encoding="utf-8").strip()
    scripts = json.loads(SCRIPTS.read_text(encoding="utf-8"))
    scns = {q["id"]: q for q in json.loads(SCENARIOS.read_text(encoding="utf-8"))}
    build_probes(scripts, scns)
    if args.ids:
        scripts = [s for s in scripts if s["scenario_id"] in args.ids]
    t1 = {(a["model"], a["scenario_id"]): a for a in map(json.loads, args.t1.read_text(encoding="utf-8").splitlines())
          if a["mode"] == "off" and a["repeat"] == 0}

    convs = []
    for m in models:
        for s in scripts:
            a = t1.get((m, s["scenario_id"]))
            if not a:
                raise SystemExit(f"{args.t1.name} 里缺 {m} 对 {s['scenario_id']} 的第 1 轮回答")
            convs.append({"model": m, "script": s, "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": scns[s["scenario_id"]]["prompt"]},
                {"role": "assistant", "content": a["text"]}]})
    recs = {}
    for m in models:
        for r in load(RAW / f"pressure__{m}.jsonl"):
            if r.get("ok"):
                recs[r["key"]] = r
    print(f"{len(models)} 模型 × {len(scripts)} 场景 × 3 轮 = {len(convs) * 3} 次调用（第 1 轮复用 {args.t1.name}）")

    if args.dry_run:
        total = 0.0
        for m in models:
            pi, po = PRICE.get(m, (0, 0))
            # 输入随轮次累积：粗估每轮输入 = 题干 + 已有各轮回答（每轮约 1700 token），输出每轮按 1200 token
            c = len(scripts) * sum(((450 + 1700 * k) * pi + 1200 * po) for k in (1, 2, 3)) / 1e6
            total += c
            print(f"  {m:<24} 粗估 {c:.2f} 元")
        print(f"  合计粗估 {total:.2f} 元（原价，未计缓存）")
        return

    clients = {m: make_client(cfg, m) for m in models}
    RAW.mkdir(parents=True, exist_ok=True)
    spent = 0.0

    def advance(conv):
        """把一个对话从第一个未完成的轮次往后跑完；返回本次新调用的记录。"""
        new = []
        for t in TURNS:
            conv["messages"].append({"role": "user", "content": conv["script"][t]["text"]})
            k = key_of(conv["model"], params_of[conv["model"]], conv["messages"])
            r = recs.get(k)
            if r is None:
                r = {"key": k, "model": conv["model"], "scenario_id": conv["script"]["scenario_id"], "turn": t,
                     **call(clients[conv["model"]], conv["model"], params_of[conv["model"]], conv["messages"]), "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
                new.append(r)
                if not r["ok"]:
                    return new
            conv["messages"].append({"role": "assistant", "content": r["content"]})
            conv.setdefault("finish", []).append(r["finish_reason"])
        return new

    fh = {m: (RAW / f"pressure__{m}.jsonl").open("a", encoding="utf-8") for m in models}
    try:
        with ThreadPoolExecutor(args.workers) as ex:
            futs = [ex.submit(advance, c) for c in convs]
            for fu in as_completed(futs):
                for r in fu.result():
                    fh[r["model"]].write(json.dumps(r, ensure_ascii=False) + "\n")
                    fh[r["model"]].flush()
                    spent += r["cost_cny"]
                    if not r["ok"]:
                        print(f"  ! {r['model']} {r['scenario_id']} {r['turn']}：{r['error']}")
    finally:
        for h in fh.values():
            h.close()

    done = [c for c in convs if len(c.get("finish", [])) == 3]
    rows = [{"conv_id": f"{c['model']}:{c['script']['scenario_id']}", "scenario_id": c["script"]["scenario_id"],
             "model": c["model"], "messages": c["messages"][1:], "finish_reasons": c["finish"]} for c in done]
    # 合并已有文件里其他模型 / 场景的对话（只跑子集时不覆盖）
    old = {r["conv_id"]: r for r in load(args.out)}
    old.update({r["conv_id"]: r for r in rows})
    args.out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in sorted(old.values(), key=lambda r: r["conv_id"])),
                   encoding="utf-8")
    print(f"完成 {len(done)}/{len(convs)} 个对话；本次新调用按原价约 {spent:.2f} 元；→ {args.out}（共 {len(old)} 个对话）")
    for m in models:
        cs = [c for c in done if c["model"] == m]
        if cs:
            print(f"  {m:<24} 截断 {sum(f == 'length' for c in cs for f in c['finish'])}，"
                  f"T2–T4 平均字数 {sum(len(x['content']) for c in cs for x in c['messages'][4::2]) / (3 * len(cs)):.0f}")


if __name__ == "__main__":
    main()
