"""把按模型分开产出的「思考对照」运行结果合并成分析脚本要读的单文件。

背景：思考对照生成时按模型分进程跑（`generate_answers.py --run thinking_on_<模型>`），
判分也按模型分目录（`results/judge/thinking_on_<模型>/`）；而 `analysis/thinking_analysis.py` 读的是
合并后的 `results/answers/thinking_on.jsonl` 与 `results/judge/thinking_on/`（第 39–40 行）。

用法：uv run python scripts/merge_thinking_runs.py

输出（按模型名排序后逐行拼接；同一 answer_id 只保留第一次出现，防重复运行叠加）：
- results/answers/thinking_on.jsonl
- results/judge/thinking_on/<judge>_<effort>.jsonl 与同名 .scores.csv

幂等：重复运行结果相同。只合并 results/ 下的既有文件，不产生新调用。
"""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANSWERS_DIR = ROOT / "results/answers"
JUDGE_DIR = ROOT / "results/judge"
ANSWERS_OUT = ANSWERS_DIR / "thinking_on.jsonl"
JUDGE_OUT = JUDGE_DIR / "thinking_on"


def answer_files():
    """按模型分开产出的开思考回答；不含合并结果本身与关思考运行。"""
    return sorted(p for p in ANSWERS_DIR.glob("thinking_on_*.jsonl"))

def judge_run_dirs():
    return sorted(p for p in JUDGE_DIR.glob("thinking_on_*") if p.is_dir())


def dedup_lines(paths, key):
    seen, out = set(), []
    for p in paths:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            k = rec.get(key)
            if k in seen:
                continue
            seen.add(k)
            out.append(line)
    return out


def merge_answers():
    src = answer_files()
    if not src:
        print("没有找到 thinking_on_*.jsonl，跳过回答合并")
        return
    lines = dedup_lines(src, "answer_id")
    ANSWERS_OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    per = {p.name: sum(1 for _ in p.open(encoding="utf-8")) for p in src}
    print(f"{ANSWERS_OUT.relative_to(ROOT)}：{len(lines)} 行（合并 {len(src)} 个文件：" +
          "，".join(f"{k} {v}" for k, v in per.items()) + "）")


def merge_judges():
    dirs = judge_run_dirs()
    if not dirs:
        print("没有找到 thinking_on_* 判分目录，跳过判分合并")
        return
    names = sorted({p.name for d in dirs for p in d.glob("*.jsonl")})
    JUDGE_OUT.mkdir(parents=True, exist_ok=True)
    for name in names:
        present = [d / name for d in dirs if (d / name).exists()]
        lines = dedup_lines(present, "answer_id")
        (JUDGE_OUT / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"{(JUDGE_OUT / name).relative_to(ROOT)}：{len(lines)} 行（来自 {len(present)} 个模型目录）")
        csvs = [d / name.replace(".jsonl", ".scores.csv") for d in dirs]
        csvs = [p for p in csvs if p.exists()]
        if not csvs:
            continue
        with (JUDGE_OUT / name.replace(".jsonl", ".scores.csv")).open("w", encoding="utf-8", newline="") as f:
            w = None
            for p in csvs:
                rows = list(csv.DictReader(p.open(encoding="utf-8")))
                if not rows:
                    continue
                if w is None:
                    w = csv.DictWriter(f, fieldnames=list(rows[0]))
                    w.writeheader()
                w.writerows(rows)
    missing = [d.name for d in dirs]
    print("已合并的判分目录：" + "，".join(missing))


def main():
    merge_answers()
    merge_judges()


if __name__ == "__main__":
    sys.exit(main())
