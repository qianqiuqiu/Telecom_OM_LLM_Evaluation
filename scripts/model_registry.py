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
    # 流式读超时 180 秒：思考期间推理 token 持续下发，不会误触；只防止流卡住不动（Oct 15 思考对照冒烟时卡过 20 分钟）
    return OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"], timeout=180)


STALL_S, TOTAL_S = 120, 2400


def stream_chat(client, req, extra, stall_s=STALL_S, total_s=TOTAL_S):
    """流式调用，返回 {content, reasoning, finish_reason, served_model, usage, ttft_s, ttfa_s, latency_s}。

    看门狗：连续 stall_s 秒没有新的 token、或总时长超过 total_s，就关掉连接并抛 TimeoutError（由调用方重试）。
    原因：Oct 15 思考对照冒烟时 qwen3.8-max 开思考的流会中途卡住，连接一直保持（读超时不触发），一次卡了 20 多分钟。
    """
    import threading
    import time
    out = {"content": "", "reasoning": "", "finish_reason": None, "served_model": None, "usage": None,
           "ttft_s": None, "ttfa_s": None}
    t0 = time.monotonic()
    last = [t0]
    stream = client.chat.completions.create(**req, extra_body=extra)
    stop, killed = threading.Event(), []

    def watchdog():
        while not stop.wait(5):
            now = time.monotonic()
            if now - last[0] > stall_s or now - t0 > total_s:
                killed.append(f"{'无新 token ' + str(stall_s) + ' 秒' if now - last[0] > stall_s else '总时长超 ' + str(total_s) + ' 秒'}")
                try:
                    stream.response.close()
                except Exception:  # noqa: BLE001
                    pass
                return

    threading.Thread(target=watchdog, daemon=True).start()
    try:
        for chunk in stream:
            out["served_model"] = chunk.model or out["served_model"]
            if chunk.usage:
                out["usage"] = chunk.usage.model_dump()
            for ch in chunk.choices:
                c, r = ch.delta.content or "", getattr(ch.delta, "reasoning_content", None) or ""
                now = time.monotonic()
                if c or r:
                    last[0] = now
                if (c or r) and out["ttft_s"] is None:
                    out["ttft_s"] = round(now - t0, 2)  # 首 token（含推理）
                if c and out["ttfa_s"] is None:
                    out["ttfa_s"] = round(now - t0, 2)  # 首个答案 token
                out["content"] += c
                out["reasoning"] += r
                out["finish_reason"] = ch.finish_reason or out["finish_reason"]
    except Exception:
        if killed:
            raise TimeoutError(f"看门狗中断：{killed[0]}") from None
        raise
    finally:
        stop.set()
    if killed:
        raise TimeoutError(f"看门狗中断：{killed[0]}")
    out["latency_s"] = round(time.monotonic() - t0, 2)
    return out
