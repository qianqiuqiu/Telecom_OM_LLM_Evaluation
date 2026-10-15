"""被测模型注册：configs/models.yaml 的分组、每个模型在某个 mode 下的请求参数、对应的 API 客户端。

- main / thinking_only：经百炼（.env 的 LLM_BASE_URL / LLM_API_KEY），参数 = modes[mode] 再叠加条目里的 params[mode]。
- regression：精度回归的自部署模型（SGLang），经 regression_base_url（SSH 隧道）访问，参数只取条目里的 params[mode]，
  不与 modes 合并（百炼的 enable_thinking 顶层参数对 SGLang 无效，关思考改用 chat_template_kwargs）。
"""
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "configs/models.yaml"
GROUPS = ("main", "thinking_only", "regression")


def load_cfg():
    return yaml.safe_load(MODELS.read_text(encoding="utf-8"))


def entries(cfg):
    """{模型 ID: (分组, 条目)}"""
    return {m["id"]: (g, m) for g in GROUPS for m in cfg.get(g) or []}


def params(cfg, model, mode):
    group, entry = entries(cfg)[model]
    own = (entry.get("params") or {}).get(mode)
    if group == "regression":
        if own is None:
            raise SystemExit(f"{model} 没有 mode={mode} 的参数")
        return dict(own)
    return {**cfg["modes"][mode], **(own or {})}


def is_local(cfg, model):
    return entries(cfg)[model][0] == "regression"


def make_client(cfg, model):
    from openai import OpenAI
    if is_local(cfg, model):
        return OpenAI(base_url=cfg["regression_base_url"], api_key="EMPTY", timeout=1800)
    from verify_three_vote import load_env
    load_env()
    return OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"])
