"""客观题横评：用 EvalScope 在测试子集（731 题 × orig / rep / s1–s3）上调用被测模型，关闭思考、温度 0。

每个模型一个工作目录 results/evalscope/objective/<模型>/，EvalScope 在其中落盘逐题预测与打分；
重跑同一命令会复用缓存（use_cache），只补跑缺失或失败的题。

前置：uv run python scripts/build_mcq_variants.py
用法：
  uv run python scripts/run_objective.py --limit 3 --models qwen3.8-flash   # 冒烟测试
  uv run python scripts/run_objective.py                                   # 全部 7 个主实验模型
  uv run python scripts/run_objective.py --models qwen3.8-27b-fp8          # 精度回归某一档（configs/models.yaml 的 regression 组）
精度回归的模型经 SSH 隧道访问 AutoDL 上的 SGLang，结果写到 results/evalscope/regression/<模型>/，
不进横评分析层（analysis/objective_analysis.py 只读 results/evalscope/objective/）。
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import evalscope_teleqna  # noqa: E402,F401  注册 teleqna_mcq
from model_registry import is_local, load_cfg, params as model_params  # noqa: E402
from evalscope import TaskConfig, run_task  # noqa: E402

DATA = ROOT / "results/evalscope_data/teleqna_ops"
SUBSETS = ["orig", "rep", "s1", "s2", "s3"]
MAX_TOKENS = 256  # 只需输出 'ANSWER: X'；留余量给不守格式的模型，抽取失败率另报


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="*")
    parser.add_argument("--subsets", nargs="*", default=SUBSETS)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--batch", type=int, default=8)
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    from verify_three_vote import load_env
    load_env()
    cfg = load_cfg()
    models = args.models or [m["id"] for m in cfg["main"]]
    for model in models:
        p = model_params(cfg, model, "off")
        local = is_local(cfg, model)
        tag = "smoke" if args.limit else ("regression" if local else "objective")
        work = ROOT / "results/evalscope" / tag / model
        task = TaskConfig(
            model=model,
            api_url=cfg["regression_base_url"] if local else os.environ["LLM_BASE_URL"],
            api_key="EMPTY" if local else os.environ["LLM_API_KEY"],
            eval_type="openai_api",
            datasets=["teleqna_mcq"],
            dataset_args={"teleqna_mcq": {"local_path": str(DATA), "subset_list": args.subsets}},
            generation_config={"temperature": p.pop("temperature"), "max_tokens": MAX_TOKENS, "extra_body": p},
            eval_batch_size=args.batch,
            work_dir=str(work),
            no_timestamp=True,
            use_cache=str(work) if work.exists() else None,
            limit=args.limit,
            seed=42,
        )
        print(f"=== {model} → {work.relative_to(ROOT)}")
        run_task(task)


if __name__ == "__main__":
    main()
