"""第 2 阶段跑模型前的费用估算（百炼北京区原价，元 / 百万 token，Oct 12 查自 help.aliyun.com/zh/model-studio/model-pricing）。

输入：data/processed/teleqna_test_subset.csv、data/raw/TeleQnA/TeleQnA.json（算平均输入长度）
输出：终端表格与 reports/cost_estimate.md

token 假设（可改下面的常量后重算）：
  - 客观题输入：按题干 + 选项 + 指令的平均字符数 / 3.0（以 probe 实测 54 token 的 PRB 题标定），再加 10 token 模板开销
  - 关思考输出：只答序号，5 token（kimi-k3 实测多几个字，取 10）
  - 开思考输出（思考 + 答案）：未实测，按 500 / 1500 / 3000 三档估算；需小规模试跑确定
  - 场景题：输入 600、关思考输出 800、开思考额外思考 2000 token（均为假设）

用法：uv run python analysis/cost_estimate.py
"""

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (输入价, 输出价)，元 / 百万 token；DeepSeek 按白天高峰价（夜间 22:00–8:00 半价）
PRICE = {
    "qwen3.8-max-0902": (12, 36),
    "qwen3.7-plus": (2, 8),
    "qwen3.8-flash": (0.8, 2.7),
    "deepseek-v4-pro-0813": (9, 27),
    "deepseek-v4.1-flash": (2, 8),
    "glm-5.2": (8, 28),
    "kimi-k3": (20, 100),
    "glm-5.3": (8, 28),  # 只能开思考，仅参与思考对照
}
MAIN = [m for m in PRICE if m != "glm-5.3"]
OFF_OUT = {m: (10 if m == "kimi-k3" else 5) for m in PRICE}
OBJ_RUNS = 4            # 3 遍打乱 + 1 遍噪声底
THINK_OBJ_N = 300       # 思考对照：客观题分层抽样
THINK_RUNS = 3          # 开思考温度非 0，每题 3 次
THINK_OUT = (500, 1500, 3000)
SCEN_N, SCEN_IN, SCEN_OUT, SCEN_THINK = 45, 600, 800, 2000
CHARS_PER_TOKEN, TEMPLATE = 3.0, 10


def cost(model, n_calls, tin, tout):
    pi, po = PRICE[model]
    return n_calls * (tin * pi + tout * po) / 1e6


def main():
    raw = json.loads((ROOT / "data/raw/TeleQnA/TeleQnA.json").read_text(encoding="utf-8"))
    with (ROOT / "data/processed/teleqna_test_subset.csv").open(encoding="utf-8") as f:
        ids = [r["id"] for r in csv.DictReader(f)]
    chars = []
    for q in ids:
        v = raw[q]
        opts = [v[k] for k in v if k.startswith("option ")]
        chars.append(len("Answer the following multiple-choice question about telecommunications. "
                          "Reply with the option number only.\n\n" + v["question"]) + sum(len(o) + 4 for o in opts))
    tin = sum(chars) / len(chars) / CHARS_PER_TOKEN + TEMPLATE
    n = len(ids)

    obj = {m: cost(m, n * OBJ_RUNS, tin, OFF_OUT[m]) for m in MAIN}
    scen = {m: cost(m, SCEN_N, SCEN_IN, SCEN_OUT) for m in MAIN}
    think = {t: {m: cost(m, THINK_OBJ_N * THINK_RUNS, tin, t) + cost(m, SCEN_N * THINK_RUNS, SCEN_IN, SCEN_OUT + SCEN_THINK)
                 for m in PRICE} for t in THINK_OUT}

    lines = ["# 跑模型费用估算", "", "由 `analysis/cost_estimate.py` 生成，请勿手改。百炼北京区原价；DeepSeek 按白天价（夜间半价）。", "",
             f"客观题 {n} 题，平均输入约 {tin:.0f} token；横评每模型 {OBJ_RUNS} 遍（3 遍打乱 + 1 遍噪声底），关思考。", "",
             "| 模型 | 客观题横评（关思考） | 场景题 1 遍（关思考） | 思考对照（开思考，思考 500 / 1500 / 3000 token） |",
             "| --- | --- | --- | --- |"]
    for m in PRICE:
        o = f"{obj[m]:.1f}" if m in obj else "—"
        s = f"{scen[m]:.1f}" if m in scen else "—"
        lines.append(f"| {m} | {o} | {s} | " + " / ".join(f"{think[t][m]:.0f}" for t in THINK_OUT) + " |")
    lines.append(f"| **合计** | **{sum(obj.values()):.1f}** | **{sum(scen.values()):.1f}** | **"
                 + " / ".join(f"{sum(think[t].values()):.0f}" for t in THINK_OUT) + "** |")
    lines += ["", f"思考对照：{len(PRICE)} 个模型（含只能开思考的 glm-5.3）× 客观题 {THINK_OBJ_N} 题 + 场景题 {SCEN_N} 题，每题 {THINK_RUNS} 次；"
              "关思考一侧复用横评与场景题主实验的结果，不另计。", "",
              "未计入：judge 打分、追问施压、污染检测改写对照、试跑与重跑。", ""]
    (ROOT / "reports/cost_estimate.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[4:]))


if __name__ == "__main__":
    main()
