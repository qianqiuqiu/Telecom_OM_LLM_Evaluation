"""第 2 阶段跑模型前的费用估算（百炼北京区原价，元 / 百万 token，Oct 12 查自 help.aliyun.com/zh/model-studio/model-pricing）。

输入：data/processed/teleqna_test_subset.csv、data/raw/TeleQnA/TeleQnA.json（算平均输入长度）
输出：终端表格与 reports/cost_estimate.md

token 假设（可改下面的常量后重算）：
  - 客观题输入：按题干 + 选项 + 指令的平均字符数 / 3.0（以 probe 实测 54 token 的 PRB 题标定），再加 10 token 模板开销
  - 关思考输出：只答序号，5 token（kimi-k3 实测多几个字，取 10）
  - 开思考输出（思考 + 答案）：按 500 / 1500 / 3000 三档估算，另列试跑实测值（scripts/thinking_pilot.py，10 题 × 1 次，
    Oct 12；kimi-k3 未试跑，按 2000 假设；glm-5.3 只有 4 次成功且 2 次截断，实测值偏低）
  - 场景题关思考：按 main_off 逐模型实测的输入 / 输出 token（SCEN_MEASURED，7 模型 × 45 题 = 315 次调用，Oct 14）；
    原假设「输入 600、输出 800」偏小约 2 倍（实测总均值 409 / 1681），已弃用
  - 场景题开思考：额外思考 2000 token（假设，未实测）

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
THINK_OBJ_N = 300       # 思考对照：客观题分层抽样（原方案；Oct 12 定为 150 × 1 次、去掉 kimi-k3，见 main 末尾的定稿行）
THINK_RUNS = 3          # 开思考温度非 0，每题 3 次
THINK_OUT = (500, 1500, 3000)
# 试跑实测：每题平均输出 token（思考 + 答案），results/pilot/thinking_20261012-062633.jsonl
THINK_MEASURED = {"qwen3.8-max-0902": 2042, "qwen3.7-plus": 563, "qwen3.8-flash": 4883,
                  "deepseek-v4-pro-0813": 2236, "deepseek-v4.1-flash": 1177, "glm-5.2": 2137,
                  "kimi-k3": 2000, "glm-5.3": 9727}
SCEN_N, SCEN_THINK = 45, 2000
# 场景题关思考实测：每题平均 (输入, 输出) token，results/answers/raw/*__off.jsonl
# （run main_off，7 模型 × 45 题 = 315 次调用，Oct 14，提交 b07b877；0 失败、0 截断）
SCEN_MEASURED = {"qwen3.8-max-0902": (432, 1760), "qwen3.7-plus": (432, 1790),
                 "qwen3.8-flash": (432, 1838), "deepseek-v4-pro-0813": (384, 1465),
                 "deepseek-v4.1-flash": (385, 1634), "glm-5.2": (394, 1278),
                 "kimi-k3": (401, 1998)}
SCEN_FALLBACK = (409, 1681)   # 没跑过关思考的模型（glm-5.3）用 315 次调用的总均值
SCEN_SPENT = 17.67            # main_off 实际花费（元，原价），用来核对下表「场景题 1 遍」一列
CHARS_PER_TOKEN, TEMPLATE = 3.0, 10


def scen_tokens(model):
    return SCEN_MEASURED.get(model, SCEN_FALLBACK)


def scen_cost(model, n_calls, extra_think=0):
    tin, tout = scen_tokens(model)
    return cost(model, n_calls, tin, tout + extra_think)


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
    scen = {m: scen_cost(m, SCEN_N) for m in MAIN}
    think = {t: {m: cost(m, THINK_OBJ_N * THINK_RUNS, tin, t) + scen_cost(m, SCEN_N * THINK_RUNS, SCEN_THINK)
                 for m in PRICE} for t in THINK_OUT}
    meas = {m: cost(m, THINK_OBJ_N * THINK_RUNS, tin, THINK_MEASURED[m])
            + scen_cost(m, SCEN_N * THINK_RUNS, SCEN_THINK) for m in PRICE}

    lines = ["# 跑模型费用估算", "", "由 `analysis/cost_estimate.py` 生成，请勿手改。百炼北京区原价；DeepSeek 按白天价（夜间半价）。", "",
             f"客观题 {n} 题，平均输入约 {tin:.0f} token；横评每模型 {OBJ_RUNS} 遍（3 遍打乱 + 1 遍噪声底），关思考。",
             f"场景题 {SCEN_N} 题的输入 / 输出 token 按 `main_off` 逐模型实测（Oct 14，315 次调用），不再是假设值。", "",
             "| 模型 | 客观题横评（关思考） | 场景题 1 遍（关思考） | 思考对照（开思考，思考 500 / 1500 / 3000 token） | 思考对照（按试跑实测） |",
             "| --- | --- | --- | --- | --- |"]
    for m in PRICE:
        o = f"{obj[m]:.1f}" if m in obj else "—"
        s = f"{scen[m]:.1f}" if m in scen else "—"
        lines.append(f"| {m} | {o} | {s} | " + " / ".join(f"{think[t][m]:.0f}" for t in THINK_OUT)
                     + f" | {meas[m]:.0f}（{THINK_MEASURED[m]} token） |")
    lines.append(f"| **合计** | **{sum(obj.values()):.1f}** | **{sum(scen.values()):.1f}** | **"
                 + " / ".join(f"{sum(think[t].values()):.0f}" for t in THINK_OUT) + f"** | **{sum(meas.values()):.0f}** |")
    lines += ["", f"**场景题关思考已跑完（Oct 14，`b07b877`）**：315/315 成功、0 失败、0 截断，实际花费 ¥{SCEN_SPENT:.2f}；"
              f"上表同口径估 ¥{sum(scen.values()):.1f}。原假设「输出 800 token」给出的是 ¥9.0，偏小约 2 倍"
              "（实测平均输出 1681 token、输入 409），思考对照一列同样受影响，已随之上修。"]
    chosen = [m for m in PRICE if m != "kimi-k3"]
    final = sum(cost(m, 150, tin, THINK_MEASURED[m]) + scen_cost(m, SCEN_N * THINK_RUNS, SCEN_THINK)
                for m in chosen)
    lines += ["", f"**定稿（Oct 12 定的方案，费用按 Oct 14 场景题实测重算）**：思考对照 {len(chosen)} 个模型（去掉 kimi-k3）"
              f"× 客观题 150 题 × 1 次 + 场景题 {SCEN_N} 题 × {THINK_RUNS} 次，约 ¥{final:.0f}"
              f"（Oct 12 按旧假设批的是 ¥130，尚未花，花钱前需重新确认）；主实验 ¥{sum(obj.values()) + sum(scen.values()):.0f}。"]
    lines += ["", f"上表思考对照（原方案）：{len(PRICE)} 个模型（含只能开思考的 glm-5.3）× 客观题 {THINK_OBJ_N} 题 + 场景题 {SCEN_N} 题，每题 {THINK_RUNS} 次；"
              "关思考一侧复用横评与场景题主实验的结果，不另计。", "",
              "未计入：judge 打分、追问施压、污染检测改写对照、试跑与重跑。", ""]
    (ROOT / "reports/cost_estimate.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[4:]))


if __name__ == "__main__":
    main()
