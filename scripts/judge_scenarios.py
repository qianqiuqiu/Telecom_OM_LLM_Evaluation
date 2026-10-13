"""场景题 judge：按 rubric 逐项判定回答，总分由程序计算。

judge 只输出逐项判定（要点 covered / partial / missed、扣分项与高危操作是否触发，各附原文摘录），
程序按要点权重算分：covered 记满分、partial 记一半、missed 记 0，加上触发的扣分项（下限 0）；
任一高危操作触发则整题 0 分（一票否决）。诊断题另报「根因」「处置」两段的得分率（扣分前）。
另核对 judge 给的原文摘录是否真出现在回答里，用来发现 judge 编造证据。

后端（--judge）：
  claude:<模型 ID>   经 Claude Code 无头模式（claude -p）调用，走本机登录的订阅额度；
                     用完整 ID（claude-haiku-5-5、claude-sonnet-5-5），不用会被静默更新的别名。
                     在空的临时目录里运行、不加载设置与 MCP，避免项目 CLAUDE.md 混进 judge 上下文
                     （用户级 ~/.claude/CLAUDE.md 仍会被读入，里面不要放与评分相关的内容）。
                     这两个模型不接受自定义温度，judge 自身稳定性靠 --repeats 测量。
  bailian:<模型 ID>  经百炼 OpenAI 兼容接口（.env），关思考、温度 0；用于跨厂商对照与自家偏好实验。

输入：回答 JSONL，每行 {"answer_id", "scenario_id", "source", "text"}（探针由 build_judge_probes.py 生成）。
输出（results/，不入库）：
  results/judge/<run>/<judge 标签>.jsonl       每次调用一行，追加写、可断点续跑：逐项判定、校验结果、
                                              分数、证据核对、实际返回的模型名、token 用量、耗时
  results/judge/<run>/<judge 标签>.scores.csv  每个回答 × 重复序号一行的分数表（由 jsonl 重算）
缓存键 = 提示词全文 + judge + effort + 题目评分信息 + 回答文本的哈希；任何一项变了就重判。
判定校验不通过或调用出错的记录会落盘并计入失败率，下次运行自动重试，不会被悄悄剔除。

用法：
  uv run python scripts/judge_scenarios.py --answers data/scenarios/judge_probes/probes.jsonl \\
      --judge claude:claude-haiku-5-5 --prompt v1 --run probes_v1 --split debug
  ... --repeats 3            # judge 自身稳定性：同一回答重复判 3 次
  ... --limit 2 --dry-run    # 只打印将发送的提示，不调用
  ... --summary-only         # 只按已落盘结果重算汇总与分数表
"""
import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "data/scenarios/scenarios_draft.json"
SPLIT = ROOT / "data/scenarios/judge_split.csv"
PROMPTS = ROOT / "configs/judge"
OUT = ROOT / "results/judge"

CREDIT = {"covered": 1.0, "partial": 0.5, "missed": 0.0}
STAGE_NAME = {"root_cause": "根因", "action": "处置", "overall": "整体"}


def _flag_schema(key):
    return {"type": "array", "items": {
        "type": "object",
        "properties": {key: {"type": "integer"}, "evidence": {"type": "string"},
                       "triggered": {"type": "boolean"}},
        "required": [key, "evidence", "triggered"], "additionalProperties": False}}


SCHEMA = {
    "type": "object",
    "properties": {
        "points": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "evidence": {"type": "string"},
                           "verdict": {"type": "string", "enum": list(CREDIT)}},
            "required": ["id", "evidence", "verdict"], "additionalProperties": False}},
        "deductions": _flag_schema("index"),
        "high_risk": _flag_schema("index"),
    },
    "required": ["points", "deductions", "high_risk"],
    "additionalProperties": False,
}

JSON_HINT = ('\n\n只输出一个 JSON 对象，不要任何其他文字，格式：\n'
             '{"points":[{"id":"P1","evidence":"原文摘录或空字符串","verdict":"covered|partial|missed"}],'
             '"deductions":[{"index":0,"evidence":"","triggered":false}],'
             '"high_risk":[{"index":0,"evidence":"","triggered":false}]}')


class UsageLimit(Exception):
    """订阅额度用尽或被限流：停止本次运行，已完成的调用都已落盘，稍后重跑同一命令即可续上。"""


# ---------- 提示 ----------

def build_user_message(scn, answer_text):
    lines = ["## 题目", scn["prompt"], "", "## 参考答案", scn["reference_answer"], "", "## 评分要点"]
    for p in scn["rubric_points"]:
        lines.append(f"- {p['id']}（{STAGE_NAME.get(p['stage'], p['stage'])}）：{p['text']}")
    lines += ["", "## 扣分项"]
    lines += [f"- [{i}] {d['text']}" for i, d in enumerate(scn["deductions"])] or ["（无）"]
    lines += ["", "## 高危操作"]
    lines += [f"- [{i}] {h['action']}（原因：{h['why']}）"
              for i, h in enumerate(scn["high_risk_actions"])] or ["（无）"]
    lines += ["", "## 待评回答", "<answer>", answer_text, "</answer>"]
    return "\n".join(lines)


def rubric_view(scn):
    """进入缓存键的评分信息：这些变了，旧判定就作废。"""
    return {k: scn[k] for k in ("prompt", "reference_answer", "rubric_points", "deductions", "high_risk_actions")}


def cache_key(system, judge, effort, scn, answer_text):
    blob = json.dumps([system, judge, effort, rubric_view(scn), answer_text], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# ---------- 校验与算分 ----------

def validate(scn, parsed):
    errs = []
    if not isinstance(parsed, dict):
        return ["输出不是 JSON 对象"]
    want = [p["id"] for p in scn["rubric_points"]]
    got = [x.get("id") for x in parsed.get("points", [])]
    if sorted(got) != sorted(want):
        errs.append(f"要点不全或重复：期望 {want}，得到 {got}")
    if any(x.get("verdict") not in CREDIT for x in parsed.get("points", [])):
        errs.append("要点判定不在 covered/partial/missed 之内")
    for key, n in (("deductions", len(scn["deductions"])), ("high_risk", len(scn["high_risk_actions"]))):
        idx = [x.get("index") for x in parsed.get(key, [])]
        if sorted(idx) != list(range(n)):
            errs.append(f"{key} 编号不全或重复：期望 0..{n - 1}，得到 {idx}")
        if any(not isinstance(x.get("triggered"), bool) for x in parsed.get(key, [])):
            errs.append(f"{key} 的 triggered 不是布尔值")
    return errs


def score(scn, parsed):
    pts = {p["id"]: p for p in scn["rubric_points"]}
    verdict = {x["id"]: x["verdict"] for x in parsed["points"]}
    raw = sum(p["weight"] * CREDIT[verdict[pid]] for pid, p in pts.items())
    ded = sum(scn["deductions"][d["index"]]["points"] for d in parsed["deductions"] if d["triggered"])
    veto = any(h["triggered"] for h in parsed["high_risk"])
    total = 0.0 if veto else min(100.0, max(0.0, raw + ded))
    stages = {}
    for st in sorted({p["stage"] for p in pts.values()}):
        w = sum(p["weight"] for p in pts.values() if p["stage"] == st)
        got = sum(p["weight"] * CREDIT[verdict[p["id"]]] for p in pts.values() if p["stage"] == st)
        stages[st] = round(100 * got / w, 1)
    return {"total": round(total, 1), "raw": raw, "deduction": ded, "veto": veto, "stages": stages}


_PUNCT = re.compile(r"[\s，。、；：！？,.;:!?\"'“”‘’（）()【】\[\]《》<>—\-…·*#`|]+")


def _norm(s):
    return _PUNCT.sub("", s or "").lower()


def evidence_found(evidence, answer):
    """摘录在回答里找得到（忽略空白与标点；允许轻微改动：等长滑窗相似度 >= 0.8）。"""
    e, a = _norm(evidence), _norm(answer)
    if not e:
        return False
    if e in a:
        return True
    n = len(e)
    if n >= len(a):
        return SequenceMatcher(None, e, a).ratio() >= 0.8
    step = max(1, n // 4)
    return max(SequenceMatcher(None, e, a[i:i + n]).ratio() for i in range(0, len(a) - n + step, step)) >= 0.8


def check_evidence(parsed, answer):
    """需要摘录的项：判 covered/partial 的要点、触发的高危操作。返回找不到摘录的项。"""
    need = [(x["id"], x["evidence"]) for x in parsed["points"] if x["verdict"] != "missed"]
    need += [(f"H{x['index']}", x["evidence"]) for x in parsed["high_risk"] if x["triggered"]]
    missing = [k for k, ev in need if not evidence_found(ev, answer)]
    return {"checked": len(need), "missing": missing}


# ---------- 后端 ----------

class ClaudeCLI:
    def __init__(self, model, effort):
        self.model, self.effort = model, effort
        self.bin = shutil.which("claude")
        if not self.bin:
            raise SystemExit("找不到 claude 命令（Claude Code）；先安装并登录")
        self.cwd = tempfile.mkdtemp(prefix="judge_")
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ("CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD", "CLAUDE_ADDITIONAL_DIRECTORIES")}

    def call(self, system, user, schema=SCHEMA, hint=None):
        cmd = [self.bin, "-p", "--model", self.model, "--effort", self.effort,
               "--tools", "", "--no-session-persistence", "--strict-mcp-config", "--setting-sources", "",
               "--output-format", "json", "--system-prompt", system,
               "--json-schema", json.dumps(schema, ensure_ascii=False)]
        p = subprocess.run(cmd, input=user, capture_output=True, text=True, cwd=self.cwd,
                           env=self.env, timeout=600)
        try:
            r = json.loads(p.stdout)
        except json.JSONDecodeError:
            msg = (p.stderr or p.stdout or "").strip()[:300]
            if re.search(r"limit|429|rate", msg, re.I):
                raise UsageLimit(msg)
            raise RuntimeError(f"claude 退出码 {p.returncode}：{msg}")
        if r.get("is_error"):
            msg = str(r.get("result") or r.get("subtype"))[:300]
            if r.get("api_error_status") == 429 or re.search(r"usage limit|rate limit", msg, re.I):
                raise UsageLimit(msg)
            raise RuntimeError(f"claude 报错：{msg}")
        parsed = r.get("structured_output")
        if parsed is None:
            try:
                parsed = json.loads(r.get("result") or "")
            except json.JSONDecodeError:
                parsed = None
        u = r.get("usage") or {}
        return {"parsed": parsed, "raw": None if parsed is not None else r.get("result"),
                "served_model": ",".join(r.get("modelUsage") or {}),
                "usage": {"input": u.get("input_tokens"), "cache_write": u.get("cache_creation_input_tokens"),
                          "cache_read": u.get("cache_read_input_tokens"), "output": u.get("output_tokens"),
                          "thinking": (u.get("output_tokens_details") or {}).get("thinking_tokens"),
                          "list_cost_usd": r.get("total_cost_usd")}}


class Bailian:
    def __init__(self, model):
        from openai import OpenAI
        from verify_three_vote import load_env
        load_env()
        self.model = model
        self.client = OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"])

    def call(self, system, user, schema=None, hint=JSON_HINT):
        from verify_three_vote import extract_json
        r = self.client.chat.completions.create(
            model=self.model, temperature=0, max_tokens=4096, extra_body={"enable_thinking": False},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user + hint}])
        content = r.choices[0].message.content or ""
        parsed = extract_json(content)
        u = r.usage
        return {"parsed": parsed, "raw": None if parsed is not None else content, "served_model": r.model,
                "usage": {"input": u.prompt_tokens if u else None, "output": u.completion_tokens if u else None}}


def make_backend(judge, effort):
    kind, _, model = judge.partition(":")
    if kind == "claude" and model:
        return ClaudeCLI(model, effort)
    if kind == "bailian" and model:
        return Bailian(model)
    raise SystemExit(f"--judge 格式应为 claude:<模型 ID> 或 bailian:<模型 ID>，得到 {judge}")


def judge_tag(judge, effort):
    kind, _, model = judge.partition(":")
    return f"{kind}_{model}_{effort}" if kind == "claude" else f"{kind}_{model}"


# ---------- 运行 ----------

def judge_one(backend, system, scn, ans, attempts=2):
    user = build_user_message(scn, ans["text"])
    t0 = time.time()
    last = {}
    for attempt in range(1, attempts + 1):
        try:
            res = backend.call(system, user)
        except UsageLimit:
            raise
        except Exception as e:  # noqa: BLE001  调用失败记录在案，下次运行重试
            last = {"error": f"{type(e).__name__}: {e}"[:400]}
            continue
        errs = validate(scn, res["parsed"]) if res["parsed"] is not None else ["无法解析为 JSON"]
        last = {**res, "errors": errs}
        if not errs:
            return {**last, "ok": True, "attempts": attempt, "latency_s": round(time.time() - t0, 1),
                    "score": score(scn, res["parsed"]), "evidence": check_evidence(res["parsed"], ans["text"])}
    return {**last, "ok": False, "attempts": attempts, "latency_s": round(time.time() - t0, 1)}


def load_records(path):
    recs = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return recs


def latest_ok(recs):
    """(answer_id, repeat) -> 最近一条成功记录（同一缓存键）。"""
    out = {}
    for r in recs:
        if r.get("ok"):
            out[(r["answer_id"], r["repeat"], r["key"])] = r
    return out


def load_split():
    if not SPLIT.exists():
        return {}
    with SPLIT.open(encoding="utf-8") as f:
        return {r["scenario_id"]: r["split"] for r in csv.DictReader(f)}


def write_scores(rows, path):
    rows = sorted(rows, key=lambda r: (r["scenario_id"], r["answer_id"], r["repeat"]))
    stages = sorted({s for r in rows for s in r["score"]["stages"]})
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["answer_id", "scenario_id", "source", "repeat", "total", "raw", "deduction", "veto",
                    *[f"stage_{s}" for s in stages], "verdicts", "deductions_hit", "high_risk_hit",
                    "evidence_missing", "served_model"])
        for r in rows:
            p, s = r["parsed"], r["score"]
            w.writerow([r["answer_id"], r["scenario_id"], r["source"], r["repeat"], s["total"], s["raw"],
                        s["deduction"], int(s["veto"]), *[s["stages"].get(st, "") for st in stages],
                        " ".join(f"{x['id']}={x['verdict'][0]}" for x in sorted(p["points"], key=lambda x: x["id"])),
                        " ".join(str(x["index"]) for x in p["deductions"] if x["triggered"]),
                        " ".join(str(x["index"]) for x in p["high_risk"] if x["triggered"]),
                        " ".join(r["evidence"]["missing"]), r.get("served_model", "")])
    return rows


def summarize(recs, rows, n_pending, tag):
    n_fail = sum(1 for r in recs if not r.get("ok"))
    n_ev = sum(r["evidence"]["checked"] for r in rows)
    n_miss = sum(len(r["evidence"]["missing"]) for r in rows)
    out_tok = sum((r.get("usage") or {}).get("output") or 0 for r in recs)
    cost = sum((r.get("usage") or {}).get("list_cost_usd") or 0 for r in recs)
    print(f"[{tag}] 成功 {len(rows)} 条（回答 × 重复），失败记录 {n_fail} 条，仍未判成 {n_pending} 条；"
          f"摘录核对找不到 {n_miss}/{n_ev}；输出 token 合计 {out_tok}"
          + (f"；按 API 价目折合 ${cost:.2f}（订阅不按此计费，仅供估算额度）" if cost else ""))
    if rows:
        tot = [r["score"]["total"] for r in rows]
        print(f"  总分均值 {sum(tot) / len(tot):.1f}，一票否决 {sum(r['score']['veto'] for r in rows)} 条")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--answers", required=True, type=Path)
    ap.add_argument("--judge", required=True, help="claude:<模型 ID> 或 bailian:<模型 ID>")
    ap.add_argument("--prompt", default="v1", help="configs/judge/judge_<版本>.md")
    ap.add_argument("--effort", default="medium", choices=["low", "medium", "high"], help="仅 claude 后端")
    ap.add_argument("--run", required=True, help="输出子目录名，如 probes_v1")
    ap.add_argument("--scenarios", type=Path, default=SCENARIOS)
    ap.add_argument("--split", choices=["debug", "holdout", "all"], default="all")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--limit", type=int, help="只取前 N 个回答（冒烟用）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--summary-only", action="store_true")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    system = (PROMPTS / f"judge_{args.prompt}.md").read_text(encoding="utf-8")
    scns = {q["id"]: q for q in json.loads(args.scenarios.read_text(encoding="utf-8"))}
    answers = [json.loads(line) for line in args.answers.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.split != "all":
        split = load_split()
        if not split:
            raise SystemExit(f"缺少 {SPLIT}，先运行 scripts/make_judge_split.py")
        answers = [a for a in answers if split.get(a["scenario_id"]) == args.split]
    unknown = sorted({a["scenario_id"] for a in answers} - set(scns))
    if unknown:
        raise SystemExit(f"回答里有题库中不存在的题目：{unknown}")
    if args.limit:
        answers = answers[:args.limit]
    if not answers:
        raise SystemExit("筛选后没有要判的回答（检查 --answers 与 --split）")

    effort = args.effort if args.judge.startswith("claude:") else "-"
    tag = judge_tag(args.judge, effort)
    run_dir = args.out / args.run
    run_dir.mkdir(parents=True, exist_ok=True)
    log = run_dir / f"{tag}.jsonl"
    prompt_sha = hashlib.sha256(system.encode("utf-8")).hexdigest()[:12]

    if args.dry_run:
        a = answers[0]
        print("=== system ===\n" + system + "\n=== user ===\n" + build_user_message(scns[a["scenario_id"]], a["text"]))
        print(f"\n共 {len(answers)} 个回答 × {args.repeats} 次；输出将写入 {log}")
        return

    keys = {a["answer_id"]: cache_key(system, args.judge, effort, scns[a["scenario_id"]], a["text"])
            for a in answers}
    wanted = {(aid, k, key) for aid, key in keys.items() for k in range(args.repeats)}

    if not args.summary_only:
        done = latest_ok(load_records(log))
        jobs = [(a, k, keys[a["answer_id"]]) for a in answers for k in range(args.repeats)
                if (a["answer_id"], k, keys[a["answer_id"]]) not in done]
        print(f"待判 {len(jobs)} 次（{len(answers)} 个回答 × {args.repeats} 次，已缓存 "
              f"{len(answers) * args.repeats - len(jobs)}）→ {log}")
        backend = make_backend(args.judge, effort) if jobs else None
        stop = threading.Event()

        def work(a, k, key):
            if stop.is_set():
                return None
            try:
                res = judge_one(backend, system, scns[a["scenario_id"]], a)
            except UsageLimit as e:
                stop.set()
                print(f"  ! 额度用尽或被限流，停止：{e}")
                return None
            return {"key": key, "answer_id": a["answer_id"], "scenario_id": a["scenario_id"],
                    "source": a.get("source", ""), "repeat": k, "judge": args.judge, "effort": effort,
                    "prompt": args.prompt, "prompt_sha": prompt_sha, "ts": time.strftime("%Y-%m-%d %H:%M:%S"), **res}

        n_ok = n_err = 0
        with log.open("a", encoding="utf-8") as fh, ThreadPoolExecutor(args.workers) as ex:
            futs = [ex.submit(work, *j) for j in jobs]
            for fu in as_completed(futs):
                rec = fu.result()
                if rec is None:
                    continue
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
                if rec["ok"]:
                    n_ok += 1
                else:
                    n_err += 1
                    print(f"  ! {rec['answer_id']} r{rec['repeat']}：{(rec.get('errors') or [rec.get('error')])[0]}")
        print(f"本次：成功 {n_ok}，失败 {n_err}" + ("；因额度中断，稍后重跑同一命令续上" if stop.is_set() else ""))

    # 汇总只认本次范围内、缓存键与当前提示词 / 题目 / 回答一致的记录
    recs = [r for r in load_records(log) if keys.get(r["answer_id"]) == r["key"] and r["repeat"] < args.repeats]
    ok = latest_ok(recs)
    rows = write_scores(list(ok.values()), run_dir / f"{tag}.scores.csv")
    summarize(recs, rows, len(wanted - set(ok)), tag)


if __name__ == "__main__":
    main()
