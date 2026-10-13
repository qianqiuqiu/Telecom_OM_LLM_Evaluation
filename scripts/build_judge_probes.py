"""judge 构造真值探针：用参考答案造出「应得判定已知」的回答，检验 judge 判得对不对。

不做大规模人工标注（Oct 13 决定），judge 的主要验证证据来自这里。分两步：

1. segment：让映射模型把参考答案逐字切成连续片段，标出每段覆盖哪些评分要点，
   并列出参考答案没写到的要点。映射模型不能与被检验的 judge 同一家（默认百炼 qwen3.8-max），
   否则 judge 与「真值」共享同一套理解，一致率虚高。片段必须是原文逐字子串、按顺序覆盖全文，
   程序逐条核对，不合格的题重试一次，仍不合格就只造不依赖映射的探针。
   结果缓存在 segments.json（参考答案或要点变了才重切）。
2. build：按映射机械地构造探针，每个探针带应得判定（expect）：
   full          参考答案原文。映射到的要点应 covered，没写到的应 missed（这一项依赖映射模型的判断）
   drop:Pk       删掉所有覆盖 Pk 的片段。Pk 应 missed；片段全保留的要点应 covered，部分被删的不计
   wrong_root    （诊断题）删掉根因段，换成一个已被题干排除的假设作为根因。根因要点应 missed
   risk_add:Hj   原文 + 一句建议执行第 j 条高危操作。Hj 应触发（要点不计入真值）
   risk_neg:Hj   原文 + 一句提醒不要这样做。不应触发任何高危操作（检验 judge 是否只认关键词）
   pad           原文前后加与题目无关的空话，长度约翻倍。判定应与 full 一致（长度偏差）
   empty         一句拒答。所有要点应 missed
   expect 里值为 null 的项表示不计入真值。
另输出：参考答案没写到的要点清单（场景题收尾时补参考答案或改要点）、drop 探针人工抽查表。

输出（入库，作为 judge 元评测的固定输入）：data/scenarios/judge_probes/
  segments.json  probes.jsonl  reference_gaps.md  spotcheck_drop.md / spotcheck_drop.csv
用法：
  uv run python scripts/build_judge_probes.py segment            # 切分映射（百炼，45 题约 ¥3）
  uv run python scripts/build_judge_probes.py segment --ids SC-D01 --mapper claude:claude-opus-5-5
  uv run python scripts/build_judge_probes.py build              # 构造探针（不调用模型）
"""
import argparse
import csv
import hashlib
import json
import random
import re
import time
from pathlib import Path

from judge_scenarios import SCENARIOS, SPLIT, load_split, make_backend

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/scenarios/judge_probes"
SEED = 20261013

SEG_SYSTEM = "你把一段参考答案切分成连续片段，并标出每个片段覆盖了哪些评分要点。只切分、不改写。"
SEG_INSTRUCT = """要求：
1. 按原文顺序把参考答案切成若干片段。每个片段是原文中连续的一段，逐字复制，标点也不改；所有片段按顺序拼起来应等于原文。一个片段通常是一句或半句。
2. 每个片段标出它覆盖的要点 ID，可以有多个；只起连接作用、没有实质内容的片段标空列表。片段本身写出了该要点的实质内容才标，只是沾边的不标。
3. 另列出参考答案完全没写到的要点 ID（uncovered）。"""
SEG_SCHEMA = {
    "type": "object",
    "properties": {
        "segments": {"type": "array", "items": {
            "type": "object",
            "properties": {"text": {"type": "string"}, "points": {"type": "array", "items": {"type": "string"}}},
            "required": ["text", "points"], "additionalProperties": False}},
        "uncovered": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["segments", "uncovered"], "additionalProperties": False,
}
SEG_HINT = ('\n\n只输出一个 JSON 对象，不要任何其他文字，格式：\n'
            '{"segments":[{"text":"原文片段","points":["P1"]}],"uncovered":["P8"]}')

PAD = ["以上分析基于题目给出的现象和数据。", "通信网络是一个复杂的系统，各个环节相互关联。",
       "不同厂商的设备在实现细节上可能存在一定差异。", "移动通信技术在不断演进，相关标准也在持续更新。",
       "网络运维工作需要扎实的专业知识和丰富的实践经验。", "随着网络规模扩大，运维工作的重要性日益突出。",
       "良好的团队沟通有助于提高工作效率。", "本回答力求全面，供参考。"]
EMPTY = "这个问题信息不足，我无法给出判断。"
_GAP = re.compile(r"[\s，。、；：！？,.;:!?“”\"'（）()]*")


def ref_sha(q):
    blob = json.dumps([q["reference_answer"], [(p["id"], p["text"]) for p in q["rubric_points"]]], ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def check_segments(q, parsed):
    """片段须是原文逐字子串、按顺序、片段之间只隔空白或标点，且覆盖原文 95% 以上字符。"""
    ref, ids = q["reference_answer"], {p["id"] for p in q["rubric_points"]}
    probs, cur, covered = [], 0, 0
    for n, seg in enumerate(parsed.get("segments", [])):
        pos = ref.find(seg["text"], cur)
        if not seg["text"] or pos < 0:
            probs.append(f"片段 {n} 不是原文（或顺序不对）：{seg['text'][:30]}")
            continue
        if not _GAP.fullmatch(ref[cur:pos]):
            probs.append(f"片段 {n} 前漏掉原文：{ref[cur:pos][:30]}")
        covered += len(seg["text"])
        cur = pos + len(seg["text"])
        bad = set(seg["points"]) - ids
        if bad:
            probs.append(f"片段 {n} 标了不存在的要点 {sorted(bad)}")
    if not _GAP.fullmatch(ref[cur:]):
        probs.append(f"结尾漏掉原文：{ref[cur:][:30]}")
    if covered < 0.95 * len(_GAP.sub("", ref)):
        probs.append(f"片段只覆盖原文 {covered}/{len(ref)} 字")
    mapped = {pid for s in parsed.get("segments", []) for pid in s["points"]}
    if mapped & set(parsed.get("uncovered", [])):
        probs.append(f"要点既被映射又列为未写到：{sorted(mapped & set(parsed['uncovered']))}")
    return probs


def segment(args, qs):
    path = args.out / "segments.json"
    store = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"items": {}}
    todo = [q for q in qs if not (store["items"].get(q["id"], {}).get("ok")
                                  and store["items"][q["id"]]["ref_sha"] == ref_sha(q))]
    print(f"待切分 {len(todo)} 题（共 {len(qs)} 题），映射模型 {args.mapper}")
    if not todo:
        return
    backend = make_backend(args.mapper, "medium")
    for q in todo:
        pts = "\n".join(f"- {p['id']}：{p['text']}" for p in q["rubric_points"])
        user = f"## 评分要点\n{pts}\n\n## 参考答案\n<reference>\n{q['reference_answer']}\n</reference>\n\n{SEG_INSTRUCT}"
        item = {"ok": False, "ref_sha": ref_sha(q), "mapper": args.mapper}
        for attempt in (1, 2):
            try:
                res = backend.call(SEG_SYSTEM, user, schema=SEG_SCHEMA, hint=SEG_HINT)
            except Exception as e:  # noqa: BLE001
                item["problems"] = [f"{type(e).__name__}: {e}"[:300]]
                continue
            parsed = res["parsed"] or {}
            probs = check_segments(q, parsed) if parsed else ["无法解析为 JSON"]
            item.update({"segments": parsed.get("segments", []), "uncovered": parsed.get("uncovered", []),
                         "problems": probs, "served_model": res.get("served_model"), "attempts": attempt,
                         "ts": time.strftime("%Y-%m-%d %H:%M:%S")})
            if not probs:
                item["ok"] = True
                break
        store["items"][q["id"]] = item
        print(f"  {q['id']}: {'ok' if item['ok'] else '不合格 ' + '; '.join(item['problems'])[:120]}")
        path.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")


def _join(segs):
    return "".join(s["text"] for s in segs)


def _expect_after_removal(q, segs, kept, uncovered):
    """删片段后：片段全保留的要点 covered，片段全被删的 missed，部分被删的不计（null）。"""
    exp = {}
    for p in q["rubric_points"]:
        idx = [i for i, s in enumerate(segs) if p["id"] in s["points"]]
        if p["id"] in uncovered or not idx:
            exp[p["id"]] = "missed"
        elif all(i in kept for i in idx):
            exp[p["id"]] = "covered"
        elif not any(i in kept for i in idx):
            exp[p["id"]] = "missed"
        else:
            exp[p["id"]] = None
    return exp


def probes_for(q, item, n_drops):
    rng = random.Random(f"{SEED}:{q['id']}")  # 每题独立种子：只重建部分题时抽样不变
    hr_none = {str(i): False for i in range(len(q["high_risk_actions"]))}
    out = []

    def add(kind, text, points, high_risk=None, invariant_to=None):
        out.append({"answer_id": f"{q['id']}|{kind}", "scenario_id": q["id"], "source": f"probe:{kind.split(':')[0]}",
                    "text": text, "expect": {"points": points, "high_risk": high_risk or hr_none,
                                             "invariant_to": invariant_to}})

    ref = q["reference_answer"]
    seg_ok = bool(item and item.get("ok"))
    if seg_ok:
        segs, unc = item["segments"], set(item["uncovered"])
        full_exp = _expect_after_removal(q, segs, set(range(len(segs))), unc)
    else:
        segs, unc, full_exp = [], set(), {p["id"]: None for p in q["rubric_points"]}

    add("full", ref, full_exp)
    if seg_ok:
        mapped = [p["id"] for p in q["rubric_points"] if full_exp[p["id"]] == "covered"]
        for pid in sorted(rng.sample(mapped, min(n_drops, len(mapped)))):
            kept = {i for i, s in enumerate(segs) if pid not in s["points"]}
            add(f"drop:{pid}", _join([segs[i] for i in sorted(kept)]), _expect_after_removal(q, segs, kept, unc))
        root = {p["id"] for p in q["rubric_points"] if p["stage"] == "root_cause"}
        if q["type"] == "diagnosis" and root and q.get("excluded_hypotheses"):
            kept = {i for i, s in enumerate(segs) if not root & set(s["points"])}
            hyp = re.split(r"[：:]", q["excluded_hypotheses"][0])[0].strip()
            exp = _expect_after_removal(q, segs, kept, unc)
            exp.update({pid: "missed" for pid in root})
            add("wrong_root", f"根因判断：{hyp}。" + _join([segs[i] for i in sorted(kept)]), exp)
    if q["high_risk_actions"]:
        j = rng.randrange(len(q["high_risk_actions"]))
        act = q["high_risk_actions"][j]["action"].rstrip("。. ")
        # risk_add 只检验高危判定；加了一句坏建议后要点该不该降档有争议，不计入要点真值
        add(f"risk_add:H{j}", f"{ref}\n\n另外，处置时可以直接这样做：{act}。",
            {pid: None for pid in full_exp}, {**hr_none, str(j): True})
        add(f"risk_neg:H{j}", f"{ref}\n\n注意，以下做法不可取：{act}。", full_exp)
    filler, k = [], 0
    while len("".join(filler)) < len(ref):
        filler.append(PAD[k % len(PAD)])
        k += 1
    half = len(filler) // 2
    add("pad", "".join(filler[:half]) + "\n\n" + ref + "\n\n" + "".join(filler[half:]), full_exp, invariant_to="full")
    add("empty", EMPTY, {p["id"]: "missed" for p in q["rubric_points"]})
    return out


def build(args, qs):
    path = args.out / "segments.json"
    items = json.loads(path.read_text(encoding="utf-8"))["items"] if path.exists() else {}
    probes, gaps, stale = [], [], []
    for q in qs:
        item = items.get(q["id"])
        if item and item["ref_sha"] != ref_sha(q):
            stale.append(q["id"])
            item = None
        probes += probes_for(q, item, args.drops)
        if item and item.get("ok"):
            miss = [p for p in q["rubric_points"] if p["id"] in item["uncovered"]
                    or not any(p["id"] in s["points"] for s in item["segments"])]
            gaps += [(q["id"], p["id"], p["weight"], p["text"]) for p in miss]
    with (args.out / "probes.jsonl").open("w", encoding="utf-8") as f:
        for p in probes:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    seg_ok = sum(1 for q in qs if items.get(q["id"], {}).get("ok") and q["id"] not in stale)
    lines = ["# 参考答案没写到的要点", "",
             f"由 `scripts/build_judge_probes.py build` 生成，请勿手改。依据 segments.json 的映射（{seg_ok}/{len(qs)} 题映射合格）。",
             "完美照抄参考答案也拿不到这些分；场景题定稿前应补参考答案，或改 / 删要点。", "",
             "| 题目 | 要点 | 权重 | 要点内容 |", "| --- | --- | --- | --- |"]
    lines += [f"| {sid} | {pid} | {w} | {t} |" for sid, pid, w, t in gaps] or ["| （无） | | | |"]
    (args.out / "reference_gaps.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # drop 探针抽查：剩下的文字里是否还写到了被删的要点？对照文字即可判断，不需要专业知识
    split = load_split()
    pool = [p for p in probes if p["answer_id"].split("|")[1].startswith("drop:")
            and split.get(p["scenario_id"]) == "debug"]
    picks = sorted(random.Random(SEED + 1).sample(pool, min(args.spotcheck, len(pool))), key=lambda p: p["answer_id"])
    by_id = {q["id"]: q for q in qs}
    md = ["# drop 探针抽查", "", "每条给出一个要点和删改后的回答。请判断：**回答里是否还写到了这个要点的内容？**",
          "在 `spotcheck_drop.csv` 的 human 列填 Y（还写到了）或 N（没写到），拿不准填 ?，可在 note 列说明。", ""]
    rows = []
    for n, p in enumerate(picks, 1):
        pid = p["answer_id"].split("drop:")[1]
        ptxt = next(x["text"] for x in by_id[p["scenario_id"]]["rubric_points"] if x["id"] == pid)
        md += [f"## {n}. {p['answer_id']}", "", f"**要点 {pid}**：{ptxt}", "", "**回答**：", "", p["text"], ""]
        rows.append([n, p["answer_id"], pid, "", ""])
    (args.out / "spotcheck_drop.md").write_text("\n".join(md), encoding="utf-8")
    csv_path = args.out / "spotcheck_drop.csv"
    old = []
    if csv_path.exists():
        with csv_path.open(encoding="utf-8") as f:
            old = list(csv.DictReader(f))
    if any(r["human"].strip() for r in old):
        print(f"  {csv_path.name} 已有填写结果，不覆盖"
              + ("；注意：抽中的探针已变，与 md 不一致" if [r["answer_id"] for r in old] != [r[1] for r in rows] else ""))
    else:
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerows([["no", "answer_id", "point", "human", "note"], *rows])

    kinds = {}
    for p in probes:
        k = p["answer_id"].split("|")[1].split(":")[0]
        kinds[k] = kinds.get(k, 0) + 1
    print(f"探针 {len(probes)} 个：{kinds}；映射合格 {seg_ok}/{len(qs)} 题"
          + (f"；映射过期 {stale}（先重跑 segment）" if stale else ""))
    print(f"参考答案没写到的要点 {len(gaps)} 个；抽查 {len(picks)} 条 → {args.out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["segment", "build"])
    ap.add_argument("--mapper", default="bailian:qwen3.8-max-0902",
                    help="映射模型，不能与被检验的 judge 同一家")
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--drops", type=int, default=2, help="每题 drop 探针数")
    ap.add_argument("--spotcheck", type=int, default=30, help="drop 探针抽查条数（只从调试集抽）")
    ap.add_argument("--scenarios", type=Path, default=SCENARIOS)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    qs = json.loads(args.scenarios.read_text(encoding="utf-8"))
    if args.ids:
        qs = [q for q in qs if q["id"] in set(args.ids)]
    if args.step == "segment":
        segment(args, qs)
    else:
        if not SPLIT.exists():
            raise SystemExit(f"缺少 {SPLIT}，先运行 scripts/make_judge_split.py")
        build(args, qs)


if __name__ == "__main__":
    main()
