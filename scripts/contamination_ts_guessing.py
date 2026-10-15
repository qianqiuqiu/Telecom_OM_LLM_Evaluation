"""污染检测 TS-Guessing（Spec「污染检测」；Deng et al. 2024 的 question-multichoice 设定）。

遮住每题一个错误选项（[MASK]），其余选项（含正确答案，不标出）照原序给出，让被测模型补出被遮住的选项原文。
能逐字补出原文视为背过原题。7 个主实验模型，关思考、温度 0。

- 题目：客观题测试集 731 题（results/evalscope_data/teleqna_ops/orig_val.jsonl，原题原序）。
- 遮哪个选项：错误选项里去掉「以上都 / 都不」和编号引用类后，按种子（20261015 + 题号）随机取一个；
  没有可遮选项的题跳过（no_shuffle 题与只剩正确答案的题），在汇总里计数。
- 判定：EM = 规范化后（小写、去首尾标点与选项字母前缀、合并空白）与原文完全相同；
  另算 ROUGE-L F1（词级 LCS）。被遮选项按词数分短（≤ 5 词）/ 长（≥ 6 词）：短选项可能靠可猜性补出，
  长选项逐字补出更难靠猜。判定规则与报告口径见 STATUS 决定日志（Oct 15）。
- 缓存：results/contamination/raw/<模型>.jsonl（含原文，不入库），键 = 模型 + 提示 + 参数；可断点续跑，
  报错落盘为失败、下次重试。逐题结果 results/contamination/ts_guessing.csv（只有 ID 与指标，入库）。

用法：
  uv run python scripts/contamination_ts_guessing.py --dry-run           # 调用次数与粗估花费
  uv run python scripts/contamination_ts_guessing.py --limit 3 --model qwen3.8-flash   # 冒烟
  uv run python scripts/contamination_ts_guessing.py                     # 全部 7 个模型
  uv run python scripts/contamination_ts_guessing.py --export-only       # 只按已落盘记录重算逐题结果
"""
import argparse
import csv
import hashlib
import json
import os
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml
from audit_teleqna import INDEX_REF_RE, POSITION_REF_RE
from thinking_pilot import PRICE
from verify_three_vote import load_env

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "results/evalscope_data/teleqna_ops/orig_val.jsonl"
MODELS = ROOT / "configs/models.yaml"
OUT = ROOT / "results/contamination"
SEED = 20261015
LETTERS = "ABCDE"
MAX_TOKENS = 96
LONG = 6  # 词数 ≥ 6 为长选项

PROMPT = """Please fill in the [MASK] in option {letter} based on your benchmark knowledge.

The crucial rule is that you should provide a different answer from the other options below.

Question: {question}

Options:
{options}

Reply with the content of option {letter} only, no explanation."""


def pick_mask(d):
    cand = [k for k in LETTERS if d.get(k) and k != d["answer"]
            and not POSITION_REF_RE.match(d[k]) and not INDEX_REF_RE.match(d[k])]
    if not cand or any(INDEX_REF_RE.match(d[k]) for k in LETTERS if d.get(k)):
        return None
    return random.Random(f"{SEED}:{d['id']}").choice(cand)


def build(d, letter):
    opts = "\n".join(f"{k}: {'[MASK]' if k == letter else d[k]}" for k in LETTERS if d.get(k))
    return PROMPT.format(letter=letter, question=d["question"], options=opts)


_PREFIX = re.compile(r"^\s*(option\s*)?[A-E]\s*[:.)\-]\s*", re.I)


def normalize(s):
    s = (s or "").strip().splitlines()[0] if (s or "").strip() else ""
    s = _PREFIX.sub("", s).strip().strip("\"'“”‘’`*").strip()
    s = re.sub(r"\s+", " ", s.lower())
    return s.strip(" .;,:")


def tokens(s):
    return re.findall(r"[a-z0-9]+", s.lower())


def rouge_l(a, b):
    x, y = tokens(a), tokens(b)
    if not x or not y:
        return 0.0
    prev = [0] * (len(y) + 1)
    for i in range(1, len(x) + 1):
        cur = [0] * (len(y) + 1)
        for j in range(1, len(y) + 1):
            cur[j] = prev[j - 1] + 1 if x[i - 1] == y[j - 1] else max(prev[j], cur[j - 1])
        prev = cur
    lcs = prev[-1]
    if lcs == 0:
        return 0.0
    p, r = lcs / len(x), lcs / len(y)
    return 2 * p * r / (p + r)


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
            r = client.chat.completions.create(
                model=model, temperature=0, max_tokens=MAX_TOKENS, extra_body={"enable_thinking": False},
                messages=[{"role": "user", "content": prompt}])
            u = r.usage
            return {"ok": True, "content": r.choices[0].message.content or "", "served_model": r.model,
                    "finish_reason": r.choices[0].finish_reason,
                    "usage": {"input": u.prompt_tokens, "output": u.completion_tokens} if u else None}
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"[:300]
            time.sleep(2 ** a)
    return {"ok": False, "error": err}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", action="append")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--export-only", action="store_true")
    args = ap.parse_args()

    cfg = yaml.safe_load(MODELS.read_text(encoding="utf-8"))
    models = args.model or [m["id"] for m in cfg["main"]]
    items = [json.loads(l) for l in DATA.open(encoding="utf-8")]
    items = items[:args.limit] if args.limit else items
    masked = [(d, pick_mask(d)) for d in items]
    skipped = sum(1 for _, m in masked if m is None)
    masked = [(d, m) for d, m in masked if m]
    jobs = [(m, d, letter, build(d, letter)) for m in models for d, letter in masked]
    raw = OUT / "raw"
    recs = {m: load(raw / f"{m}.jsonl") for m in models}
    done = {r["key"]: r for rs in recs.values() for r in rs if r.get("ok")}
    todo = [j for j in jobs if key_of(j[0], j[3]) not in done]
    print(f"{len(models)} 模型 × {len(masked)} 题 = {len(jobs)} 次（跳过无可遮选项 {skipped} 题）；"
          f"已缓存 {len(jobs) - len(todo)}，待调用 {len(todo)}")

    if args.dry_run:
        print(jobs[0][3])
        total = 0.0
        for m in models:
            n = sum(1 for j in todo if j[0] == m)
            pi, po = PRICE[m]
            c = n * (220 * pi + 25 * po) / 1e6
            total += c
            print(f"  {m:<24} {n:>4} 次，按输入 220 / 输出 25 token 粗估 {c:.2f} 元")
        print(f"  合计粗估 {total:.2f} 元（原价）")
        return

    if todo and not args.export_only:
        from openai import OpenAI
        load_env()
        client = OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"])
        raw.mkdir(parents=True, exist_ok=True)
        fh = {m: (raw / f"{m}.jsonl").open("a", encoding="utf-8") for m in models}
        try:
            with ThreadPoolExecutor(args.workers) as ex:
                futs = {ex.submit(call, client, m, p): (m, d, letter, p) for m, d, letter, p in todo}
                n_err = 0
                for fu in as_completed(futs):
                    m, d, letter, p = futs[fu]
                    rec = {"key": key_of(m, p), "model": m, "id": d["id"], "masked": letter, **fu.result(),
                           "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
                    fh[m].write(json.dumps(rec, ensure_ascii=False) + "\n")
                    fh[m].flush()
                    n_err += not rec["ok"]
            print(f"本次失败 {n_err}")
        finally:
            for h in fh.values():
                h.close()
        recs = {m: load(raw / f"{m}.jsonl") for m in models}
        done = {r["key"]: r for rs in recs.values() for r in rs if r.get("ok")}

    rows, cost = [], {}
    for m, d, letter, p in jobs:
        r = done.get(key_of(m, p))
        if not r:
            continue
        truth = d[letter]
        guess = normalize(r["content"])
        u = r.get("usage") or {}
        pi, po = PRICE[m]
        cost[m] = cost.get(m, 0) + ((u.get("input") or 0) * pi + (u.get("output") or 0) * po) / 1e6
        rows.append({"model": m, "id": d["id"], "masked": letter, "n_words": len(tokens(truth)),
                     "long": int(len(tokens(truth)) >= LONG), "em": int(guess == normalize(truth)),
                     "rouge_l": round(rouge_l(guess, normalize(truth)), 4),
                     "finish_reason": r.get("finish_reason")})
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "ts_guessing.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"逐题结果 {len(rows)}/{len(jobs)} 行 → {(OUT / 'ts_guessing.csv').relative_to(ROOT)}")
    for m in models:
        rs = [r for r in rows if r["model"] == m]
        if rs:
            print(f"  {m:<24} EM {sum(r['em'] for r in rs) / len(rs):6.1%}  长选项 EM "
                  f"{sum(r['em'] for r in rs if r['long']) / max(1, sum(r['long'] for r in rs)):6.1%}  "
                  f"ROUGE-L {sum(r['rouge_l'] for r in rs) / len(rs):.3f}  原价约 {cost.get(m, 0):.2f} 元")


if __name__ == "__main__":
    main()
