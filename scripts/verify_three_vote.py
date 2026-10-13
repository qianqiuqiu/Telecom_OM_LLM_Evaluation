"""场景题三票跨厂商核验：glm-5.2 / kimi-k2.6 / qwen3.8-27b 逐题挑事实错误。

每个模型对每题输出结构化 JSON，列出存疑的事实/根因/rubric 要点（点名 target、
严重程度、依据）。聚合规则：同一处被 >=2 家标为存疑 -> 必修清单；仅 1 家 -> 待人工。

只判定事实对错（标准/3GPP 引用、根因、表数据与答案一致性），不评风格；
verifiability=constructed 的合成数据本身不算错，除非内部自相矛盾。

用法：
  uv run python scripts/verify_three_vote.py                 # 全量
  uv run python scripts/verify_three_vote.py --limit 2       # 冒烟
  uv run python scripts/verify_three_vote.py --ids SC-D23 SC-D24
  uv run python scripts/verify_three_vote.py --aggregate-only # 只按已落盘原始结果重算聚合

输出（均在 results/，不入库）：
  results/scenarios/three_vote/raw/<model>.jsonl   逐题原始结构化判定（可增量补缺）
  results/scenarios/three_vote/verdicts.json       聚合结果
  results/scenarios/three_vote/three_vote.md       人读清单
"""
import argparse
import json
import os
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
MODELS = ["glm-5.2", "kimi-k2.6", "qwen3.8-27b"]
OUT = ROOT / "results/scenarios/three_vote"
RAW = OUT / "raw"

SYSTEM = "你是通信网络运维领域的资深事实核查员，熟悉 3GPP（TS 23.501/23.502/24.501/23.203/24.229/23.401/24.301/29.272/29.244 等）。"
INSTRUCT = """下面是一道中文运维场景题（含题干、参考答案、根因、评分要点及其依据来源）。请逐条核查其中的**事实性**内容，只挑真正的错误，不评文风、不评难度。

重点核查：
1. root_cause 与 reference_answer 的技术判断是否成立、有无自相矛盾或与题干表格数据对不上。
2. rubric_points 里 verifiability="standard" 的要点及其 source_note 引用的标准/机制是否属实（如 3GPP TS 编号、原因值、5QI/QCI 特性、接口名称）。
3. 题干内部数据是否自洽（如数值、单位、对照关系）。
4. unverified_residuals 是否漏标了本应标为"无法核验"的具体数值/命令/阈值。

注意：verifiability="constructed" 的合成数据是有意构造的，其"不真实"本身不算错，只有当它与题干其他部分**自相矛盾**时才算问题。

只输出如下 JSON，不要任何解释文字：
{"issues":[{"target":"root_cause 或 reference_answer 或 要点ID如P3","severity":"high|medium|low","claim":"被质疑的原文摘录","problem":"错在哪","evidence":"依据（标准条目或题干数据）"}],"missing_residuals":["应补进 unverified_residuals 的项"],"overall":"ok|suspect"}
若没有发现任何事实问题，输出 {"issues":[],"missing_residuals":[],"overall":"ok"}。

题目 JSON：
"""


def load_env():
    if (ROOT / ".env").exists():
        load_dotenv(ROOT / ".env")
        return ROOT / ".env"
    # worktree 无 .env 时回退到主仓库（从 .git 文件里的 gitdir 推主仓库根）
    gitf = ROOT / ".git"
    if gitf.is_file():
        gitdir = gitf.read_text().split("gitdir:")[1].strip()
        main = Path(gitdir).parents[2]
        if (main / ".env").exists():
            load_dotenv(main / ".env")
            return main / ".env"
    raise SystemExit("找不到 .env")


def extract_json(text):
    if not text:
        return None
    s, e = text.find("{"), text.rfind("}")
    if s < 0 or e < 0:
        return None
    try:
        return json.loads(text[s:e + 1])
    except json.JSONDecodeError:
        return None


def slim(q):
    """只把核查需要的字段给模型，省 token。"""
    return {
        "id": q["id"], "type": q["type"], "dimension": q["dimension"],
        "title": q["title"], "prompt": q["prompt"],
        "reference_answer": q["reference_answer"], "root_cause": q["root_cause"],
        "rubric_points": [{"id": p["id"], "stage": p["stage"], "text": p["text"],
                           "verifiability": p["verifiability"], "source_note": p["source_note"]}
                          for p in q["rubric_points"]],
        "unverified_residuals": q["unverified_residuals"],
    }


def ask(client, model, q):
    payload = INSTRUCT + json.dumps(slim(q), ensure_ascii=False, indent=1)
    strict = ("\n\n严格要求：字段值里不要写思考过程，不要出现未转义的引号或换行；"
              "problem 与 evidence 各不超过 80 字，直接给结论。")
    t0 = time.time()
    for attempt, (msg, temp) in enumerate([(payload, 0), (payload + strict, 0.3)]):
        try:
            r = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": msg}],
                temperature=temp, max_tokens=8192,
                extra_body={"enable_thinking": False},
            )
            content = r.choices[0].message.content or ""
            parsed = extract_json(content)
            if parsed is not None:
                return {"id": q["id"], "model": model, "ok": True, "parsed": parsed,
                        "retry": attempt, "usage": r.usage.model_dump() if r.usage else None,
                        "latency_s": round(time.time() - t0, 1)}
            last = {"raw": content}
        except Exception as e:
            last = {"error": f"{type(e).__name__}: {e}"}
    return {"id": q["id"], "model": model, "ok": False, "parsed": None,
            "raw": last.get("raw"), "error": last.get("error"),
            "latency_s": round(time.time() - t0, 1)}


def run_calls(client, qs, models):
    RAW.mkdir(parents=True, exist_ok=True)
    done = defaultdict(set)
    for m in models:
        f = RAW / f"{m}.jsonl"
        if f.exists():
            for line in f.read_text().splitlines():
                try:
                    rec = json.loads(line)
                    if rec.get("ok"):  # 只把成功解析的记为已完成，失败的重跑补缺
                        done[m].add(rec["id"])
                except Exception:
                    pass
    jobs = [(m, q) for m in models for q in qs if q["id"] not in done[m]]
    print(f"待调用 {len(jobs)}（{len(qs)} 题 × {len(models)} 模型，已缓存 {sum(len(v) for v in done.values())}）")
    handles = {m: (RAW / f"{m}.jsonl").open("a", encoding="utf-8") for m in models}
    n_ok = n_err = 0
    with ThreadPoolExecutor(6) as ex:
        futs = [ex.submit(ask, client, m, q) for m, q in jobs]
        for fu in futs:
            rec = fu.result()
            handles[rec["model"]].write(json.dumps(rec, ensure_ascii=False) + "\n")
            handles[rec["model"]].flush()
            if rec.get("ok"):
                n_ok += 1
            else:
                n_err += 1
                print(f"  ! {rec['id']} {rec['model']} 失败/解析失败: {str(rec.get('error') or rec.get('raw'))[:90]}")
    for h in handles.values():
        h.close()
    print(f"调用完成：成功 {n_ok}，失败 {n_err}")


def load_raw(models):
    per = defaultdict(dict)  # qid -> model -> parsed
    for m in models:
        f = RAW / f"{m}.jsonl"
        if not f.exists():
            continue
        for line in f.read_text().splitlines():
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("ok") and rec.get("parsed"):
                per[rec["id"]][m] = rec["parsed"]
    return per


def norm_target(t):
    t = (t or "").strip().lower()
    m = re.match(r"p\d+", t)
    if m:
        return m.group(0)
    if "root_cause" in t or "根因" in t:
        return "root_cause"
    if "reference" in t or "参考答案" in t:
        return "reference_answer"
    return t[:24]


def aggregate(per, models, qs):
    by_id = {q["id"]: q for q in qs}
    rows = []
    for qid in sorted(by_id):
        votes = per.get(qid, {})
        flags = defaultdict(list)  # (target) -> [(model, severity, problem)]
        missing = defaultdict(list)
        for m, parsed in votes.items():
            for iss in parsed.get("issues", []):
                flags[norm_target(iss.get("target"))].append((m, iss.get("severity", "?"), iss.get("problem", "")))
            for mr in parsed.get("missing_residuals", []) or []:
                missing[mr[:40]].append(m)
        must, maybe = [], []
        for target, hits in flags.items():
            n = len({h[0] for h in hits})
            item = {"target": target, "n_votes": n,
                    "severity": sorted({h[1] for h in hits}),
                    "models": sorted({h[0] for h in hits}),
                    "problems": [h[2] for h in hits]}
            (must if n >= 2 else maybe).append(item)
        must.sort(key=lambda x: -x["n_votes"])
        rows.append({"id": qid, "title": by_id[qid]["title"], "n_models": len(votes),
                     "overall": {m: v.get("overall") for m, v in votes.items()},
                     "must_fix": must, "maybe": maybe,
                     "missing_residuals": [{"text": k, "n": len(v)} for k, v in missing.items() if len(v) >= 1]})
    return rows


def write_outputs(rows, models):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "verdicts.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    n_must = sum(len(r["must_fix"]) for r in rows)
    n_maybe = sum(len(r["maybe"]) for r in rows)
    q_must = [r["id"] for r in rows if r["must_fix"]]
    lines = [f"# 场景题三票核验结果（{ ' / '.join(models) }）", "",
             f"- 覆盖题数：{len(rows)}；每家投票数见 verdicts.json",
             f"- 必修项（≥2 家标同一处）：{n_must} 处，涉及 {len(q_must)} 题：{', '.join(q_must) or '无'}",
             f"- 待人工（仅 1 家标）：{n_maybe} 处", ""]
    for r in rows:
        if not (r["must_fix"] or r["maybe"] or r["missing_residuals"]):
            continue
        lines.append(f"## {r['id']} {r['title']}")
        lines.append(f"overall: {r['overall']}")
        for it in r["must_fix"]:
            lines.append(f"- **[必修 {it['n_votes']}票]** `{it['target']}` {it['severity']}：{' | '.join(p[:120] for p in it['problems'])}")
        for it in r["maybe"]:
            lines.append(f"- [待人工 1票] `{it['target']}` {it['severity']}：{' | '.join(p[:120] for p in it['problems'])}")
        for mr in r["missing_residuals"]:
            lines.append(f"- [漏标residual {mr['n']}票] {mr['text']}")
        lines.append("")
    (OUT / "three_vote.md").write_text("\n".join(lines))
    print(f"\n必修 {n_must} 处（{len(q_must)} 题）；待人工 {n_maybe} 处")
    print(f"聚合：{OUT/'verdicts.json'}\n清单：{OUT/'three_vote.md'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--aggregate-only", action="store_true")
    args = ap.parse_args()

    qs = json.loads((ROOT / "data/scenarios/scenarios_draft.json").read_text())
    if args.ids:
        qs = [q for q in qs if q["id"] in set(args.ids)]
    if args.limit:
        qs = qs[:args.limit]

    if not args.aggregate_only:
        env = load_env()
        print(f"用 .env: {env}")
        client = OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"])
        run_calls(client, qs, MODELS)

    per = load_raw(MODELS)
    rows = aggregate(per, MODELS, qs)
    write_outputs(rows, MODELS)


if __name__ == "__main__":
    main()
